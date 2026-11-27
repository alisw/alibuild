"""Run builds inside an OCI builder image with bubblewrap, without a daemon.

The image (the same one --docker uses) is pulled anonymously from its
registry over the OCI distribution API and unpacked once into a rootfs under
WORK_DIR/CONTAINERS/<digest>/rootfs. Commands and build.sh then run in that
rootfs through `bwrap` in unprivileged user namespaces, as children of
aliBuild: they stay in its process group and cgroup, and die with it.

As with the macOS --sandbox, only what the docker runtime runs in a container
runs in bwrap; checkouts, the store and uploads stay in aliBuild.
"""

import fcntl
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
from shlex import quote

from alibuild_helpers.log import debug, info, warning, dieOnError
from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.sandbox import package_write_paths

MANIFEST_TYPES = (
  "application/vnd.oci.image.index.v1+json",
  "application/vnd.docker.distribution.manifest.list.v2+json",
  "application/vnd.oci.image.manifest.v1+json",
  "application/vnd.docker.distribution.manifest.v2+json",
)
INDEX_TYPES = MANIFEST_TYPES[:2]
DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WHITEOUT = ".wh."
OPAQUE = ".wh..wh..opq"


class ImageError(Exception):
  """The image cannot be fetched, or a layer is unsafe or unsupported."""


# Image references and the registry API

def parse_image_reference(image):
  """Split IMAGE into (registry API host, repository, tag or digest), with
  Docker's defaults: docker.io, library/ for official images, :latest."""
  name, reference = image, "latest"
  if "@" in name:
    name, reference = name.split("@", 1)
  elif ":" in name.rsplit("/", 1)[-1]:
    name, reference = name.rsplit(":", 1)
  first, _, rest = name.partition("/")
  if rest and ("." in first or ":" in first or first == "localhost"):
    registry, repository = first, rest
  else:
    registry, repository = "docker.io", name
  if registry == "docker.io":
    registry = "registry-1.docker.io"
    if "/" not in repository:
      repository = "library/" + repository
  return registry, repository, reference


class Registry:
  """Anonymous, read-only client for one repository of an OCI registry."""

  def __init__(self, registry, repository, session=None):
    import requests
    self.base = "https://%s/v2/%s" % (registry, repository)
    self.session = session or requests.Session()
    self.token = None

  def _authenticate(self, challenge):
    # e.g. Bearer realm="https://registry.cern.ch/service/token",
    #      service="harbor-registry",scope="repository:alisw/x:pull"
    if not challenge.lower().startswith("bearer "):
      raise ImageError("unsupported registry authentication: %s" % challenge)
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = params.pop("realm", None)
    if not realm:
      raise ImageError("no token realm in registry challenge: %s" % challenge)
    resp = self.session.get(realm, params=params, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    self.token = body.get("token") or body.get("access_token")

  def get(self, path, accept=None, stream=False):
    for _ in range(2):
      headers = {"Accept": accept} if accept else {}
      if self.token:
        headers["Authorization"] = "Bearer " + self.token
      resp = self.session.get(self.base + path, headers=headers, stream=stream, timeout=60)
      if resp.status_code == 401 and not self.token:
        self._authenticate(resp.headers.get("WWW-Authenticate", ""))
        continue
      resp.raise_for_status()
      return resp
    raise ImageError("registry refused anonymous access to %s" % (self.base + path))

  def manifest(self, reference):
    """Return (media type, digest, parsed manifest) for a tag or digest."""
    resp = self.get("/manifests/" + reference, accept=", ".join(MANIFEST_TYPES))
    body = resp.content
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    if reference.startswith("sha256:") and reference != digest:
      raise ImageError("manifest %s has digest %s" % (reference, digest))
    manifest = json.loads(body)
    media_type = manifest.get("mediaType") or resp.headers.get("Content-Type", "").split(";")[0]
    return media_type, resp.headers.get("Docker-Content-Digest", digest), manifest

  def blob(self, digest, dest):
    """Download blob DIGEST to file DEST, checking its digest."""
    algorithm, _, expected = digest.partition(":")
    if algorithm != "sha256":
      raise ImageError("unsupported digest algorithm: %s" % digest)
    hasher = hashlib.sha256()
    with self.get("/blobs/" + digest, stream=True) as resp, open(dest, "wb") as out:
      for chunk in resp.iter_content(chunk_size=1 << 20):
        hasher.update(chunk)
        out.write(chunk)
    if hasher.hexdigest() != expected:
      raise ImageError("blob %s has digest sha256:%s" % (digest, hasher.hexdigest()))


def select_platform(index, platform):
  """Pick the manifest for PLATFORM ("linux/arm64") from an image index."""
  osname, _, arch = platform.partition("/")
  arch, _, variant = arch.partition("/")
  for entry in index.get("manifests", []):
    plat = entry.get("platform", {})
    if plat.get("os") == osname and plat.get("architecture") == arch and \
       (not variant or plat.get("variant") == variant):
      return entry["digest"]
  raise ImageError("image has no manifest for platform %s" % platform)


def host_platform():
  machine = os.uname().machine
  return "linux/" + {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)


# Unpacking layers

def _split(name):
  """Return the components of the tar member NAME, refusing any that are
  absolute or contain '..', i.e. that may point outside the rootfs."""
  parts = [p for p in name.split("/") if p not in ("", ".")]
  if name.startswith("/") or ".." in parts:
    raise ImageError("refusing layer path escaping the rootfs: %s" % name)
  return parts


def resolve_in_root(root, parts, create=False):
  """Return the host path of directory PARTS inside ROOT, resolving symlinks
  as they would be inside the container: absolute targets restart at ROOT and
  '..' stops at ROOT. Nothing found this way is outside ROOT. Missing
  directories are created if CREATE is set; otherwise None is returned."""
  pending, current, hops = list(reversed(parts)), [], 0
  while pending:
    part = pending.pop()
    if part in ("", "."):
      continue
    if part == "..":
      if current:
        current.pop()
      continue
    path = os.path.join(root, *current, part)
    try:
      mode = os.lstat(path).st_mode
    except FileNotFoundError:
      if not create:
        return None
      os.mkdir(path, 0o755)
      mode = stat.S_IFDIR
    if stat.S_ISLNK(mode):
      hops += 1
      if hops > 40:
        raise ImageError("too many levels of symlinks in %s" % "/".join(parts))
      target = os.readlink(path)
      if target.startswith("/"):
        current = []
      pending.extend(reversed(target.split("/")))
      continue
    if not stat.S_ISDIR(mode):
      if not create:
        return None
      raise ImageError("%s is not a directory" % "/".join(parts))
    current.append(part)
  return os.path.join(root, *current)


def _remove(path):
  if os.path.isdir(path) and not os.path.islink(path):
    shutil.rmtree(path)
  elif os.path.lexists(path):
    os.unlink(path)


def _apply_whiteouts(root, layer):
  """Delete what LAYER's whiteouts hide in the layers below it. All are
  applied before LAYER's own content, so an opaque directory keeps what LAYER
  itself puts in it."""
  for member in layer:
    parts = _split(member.name)
    if not parts or not parts[-1].startswith(WHITEOUT):
      continue
    parent = resolve_in_root(root, parts[:-1])
    if parent is None:
      continue
    if parts[-1] == OPAQUE:
      for entry in os.listdir(parent):
        _remove(os.path.join(parent, entry))
    elif not parts[-1].startswith(WHITEOUT + WHITEOUT):
      _remove(os.path.join(parent, parts[-1][len(WHITEOUT):]))


def _extract(root, layer):
  """Write LAYER's entries into ROOT. Owners are not kept (everything belongs
  to the invoking user), nor are setuid/setgid bits or device nodes. The owner
  can always read entries and enter and write directories, so later layers and
  removing the cache work."""
  skipped = 0
  for member in layer:
    parts = _split(member.name)
    if not parts or parts[-1].startswith(WHITEOUT):
      continue
    parent = resolve_in_root(root, parts[:-1], create=True)
    path = os.path.join(parent, parts[-1])
    mode = member.mode & 0o1777
    if member.isdir():
      if not (os.path.isdir(path) and not os.path.islink(path)):
        _remove(path)
        os.mkdir(path)
      os.chmod(path, mode | 0o700)
      continue
    _remove(path)
    if member.isreg():
      fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
      with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(layer.extractfile(member), out, 1 << 20)
      os.chmod(path, mode | 0o400)
    elif member.issym():
      os.symlink(member.linkname, path)
    elif member.islnk():
      target_parts = _split(member.linkname)
      target_parent = resolve_in_root(root, target_parts[:-1]) if target_parts else None
      if target_parent is None:
        raise ImageError("hard link %s to missing %s" % (member.name, member.linkname))
      os.link(os.path.join(target_parent, target_parts[-1]), path, follow_symlinks=False)
    elif member.isfifo():
      os.mkfifo(path, mode | 0o600)
    else:   # character and block devices need privileges; /dev is a bwrap mount
      skipped += 1
      continue
    try:
      os.utime(path, (member.mtime, member.mtime), follow_symlinks=False)
    except (NotImplementedError, OSError):
      pass
  if skipped:
    debug("Skipped %d device nodes", skipped)


def apply_layer(root, layer_path):
  """Apply the layer tarball LAYER_PATH (any compression tarfile reads) onto
  the rootfs ROOT, whiteouts first."""
  with open(layer_path, "rb") as f:
    if f.read(4) == b"\x28\xb5\x2f\xfd":
      raise ImageError("zstd-compressed layers are not supported")
  for apply in (_apply_whiteouts, _extract):
    with tarfile.open(layer_path, "r|*") as layer:
      apply(root, layer)


# The rootfs cache

class Image:
  """A container image, resolved to a digest and unpacked on first use under
  CACHE_DIR/<digest>/ (rootfs/ and image.json), keyed by the digest of the
  manifest for the platform, so concurrent aliBuild processes share it."""

  def __init__(self, image, cache_dir, platform=None):
    self.image = image
    self.cache_dir = cache_dir
    self.platform = platform or host_platform()
    self.digest = None            # what the tag pointed to, like docker's RepoDigests
    self._manifest_digest = None  # the platform's image manifest (the cache key)
    self._manifest = None
    self._config = None

  def _ref_file(self):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", "%s_%s" % (self.image, self.platform))
    return os.path.join(self.cache_dir, "refs", safe)

  def resolve(self):
    """Resolve the image reference to a digest, once per run. Without the
    registry, fall back to the digest the reference had when last pulled."""
    if self.digest:
      return self.digest
    registry, repository, reference = parse_image_reference(self.image)
    try:
      self._registry = Registry(registry, repository)
      media_type, digest, manifest = self._registry.manifest(reference)
      manifest_digest = digest
      if media_type in INDEX_TYPES or "manifests" in manifest:
        manifest_digest = select_platform(manifest, self.platform)
        _, _, manifest = self._registry.manifest(manifest_digest)
      name = self.image.split("@")[0]
      if ":" in name.rsplit("/", 1)[-1]:
        name = name.rsplit(":", 1)[0]
      self.digest = "%s@%s" % (name, digest)
      self._manifest_digest, self._manifest = manifest_digest, manifest
      os.makedirs(os.path.dirname(self._ref_file()), exist_ok=True)
      with open(self._ref_file() + ".tmp%d" % os.getpid(), "w") as f:
        json.dump({"digest": self.digest, "manifest": manifest_digest}, f)
      os.replace(self._ref_file() + ".tmp%d" % os.getpid(), self._ref_file())
    except Exception as exc:   # pylint: disable=broad-except
      try:
        with open(self._ref_file()) as f:
          cached = json.load(f)
      except (OSError, ValueError):
        raise ImageError("cannot resolve image %s: %s" % (self.image, exc)) from exc
      warning("Cannot reach the registry for %s (%s); using %s, pulled before",
              self.image, exc, cached["digest"])
      self.digest, self._manifest_digest = cached["digest"], cached["manifest"]
    return self.digest

  @property
  def path(self):
    self.resolve()
    return os.path.join(self.cache_dir, self._manifest_digest.replace(":", "-"))

  @property
  def rootfs(self):
    return os.path.join(self.ensure(), "rootfs")

  @property
  def config(self):
    """The image's runtime config (Env, WorkingDir, ...)."""
    if self._config is None:
      with open(os.path.join(self.ensure(), "image.json")) as f:
        self._config = json.load(f)["config"].get("config") or {}
    return self._config

  def ensure(self):
    """Unpack the image if it is not in the cache yet, and return its
    directory. A lock serialises concurrent unpacks of one digest, and the
    complete directory is renamed into place, so readers never see a partial
    rootfs."""
    path = self.path
    if os.path.exists(path):
      return path
    os.makedirs(self.cache_dir, exist_ok=True)
    with open(path + ".lock", "w") as lock:
      fcntl.flock(lock, fcntl.LOCK_EX)
      if os.path.exists(path):
        return path
      for stale in os.listdir(self.cache_dir):   # left by an interrupted unpack
        if stale.startswith(os.path.basename(path) + ".tmp-"):
          shutil.rmtree(os.path.join(self.cache_dir, stale), ignore_errors=True)
      dieOnError(self._manifest is None,
                 "Image %s is not in %s and the registry is unreachable" % (self.image, self.cache_dir))
      tmp = tempfile.mkdtemp(dir=self.cache_dir, prefix=os.path.basename(path) + ".tmp-")
      try:
        self._unpack(tmp)
        os.rename(tmp, path)
      finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return path

  def _unpack(self, tmp):
    registry, manifest = self._registry, self._manifest
    config_file = os.path.join(tmp, "config.blob")
    registry.blob(manifest["config"]["digest"], config_file)
    with open(config_file) as f:
      config = json.load(f)
    os.unlink(config_file)
    rootfs = os.path.join(tmp, "rootfs")
    os.mkdir(rootfs)
    layers = manifest.get("layers", [])
    for i, layer in enumerate(layers, 1):
      info("Unpacking %s: layer %d/%d (%.0f MB)", self.image, i, len(layers),
           layer.get("size", 0) / 1e6)
      layer_file = os.path.join(tmp, "layer")
      registry.blob(layer["digest"], layer_file)
      apply_layer(rootfs, layer_file)
      os.unlink(layer_file)
    with open(os.path.join(tmp, "image.json"), "w") as f:
      json.dump({"image": self.image, "digest": self.digest,
                 "manifest": self._manifest_digest, "config": config}, f, indent=2)


# Running commands

HOST_PROC_OPT_IN = ("--container-allow-host-proc (or ALIBUILD_CONTAINER_ALLOW_HOST_PROC=1) "
                    "binds the host's /proc instead, which shows the build every process "
                    "of the host's PID namespace")


@functools.lru_cache(maxsize=None)
def fresh_proc():
  """Return (works, error) for mounting a new /proc in a sandbox. The kernel
  refuses it in a user namespace when the visible /proc has parts masked by
  bind mounts, as inside Docker, runc or Apple's container."""
  err, out = getstatusoutput(["bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/",
                              "--proc", "/proc", "true"])
  return not err, out.strip()


@functools.lru_cache(maxsize=None)
def proc_args(host_proc=False):
  """Mount a new /proc, or bind the host's if HOST_PROC allows it."""
  works, out = fresh_proc()
  if works:
    return ("--proc", "/proc")
  dieOnError(not host_proc, "bwrap cannot mount a new /proc here (%s). %s." % (out, HOST_PROC_OPT_IN))
  warning("bwrap cannot mount a new /proc here (%s); binding the host's, as "
          "--container-allow-host-proc asks", out)
  return ("--ro-bind", "/proc", "/proc")


def bwrap_check(host_proc=False):
  """Return why bwrap cannot run sandboxes here, or None if it can."""
  if not shutil.which("bwrap"):
    return "bwrap (bubblewrap) is not installed"
  err, out = getstatusoutput(["bwrap", "--unshare-user", "--ro-bind", "/", "/", "true"])
  if err:
    return ("bwrap cannot create an unprivileged user namespace: %s (check "
            "user.max_user_namespaces and, on Ubuntu, "
            "kernel.apparmor_restrict_unprivileged_userns)" % out.strip())
  works, out = fresh_proc()
  if not works and not host_proc:
    return "it cannot mount a new /proc here (%s); %s" % (out, HOST_PROC_OPT_IN)
  return None


def parse_volume(volume):
  """Return (source, destination, read_only) for a docker-style -v
  SRC[:DEST[:OPTIONS]]."""
  parts = volume.split(":")
  dieOnError(not parts[0].startswith("/"), "bwrap supports only host paths as volumes, not %s" % volume)
  dest = parts[1] if len(parts) > 1 and parts[1] else parts[0]
  return parts[0], dest, len(parts) > 2 and "ro" in parts[2].split(",")


def bwrap_command(image, binds=(), env=(), network=True, extra_args=(), host_proc=False, tmp=None):
  """Return the bwrap argument list running in IMAGE with the BINDS (source,
  destination, read_only) and environment ENV on top of the image's. /tmp is
  the host directory TMP, or a tmpfs. The rootfs is read-only to the command:
  it is bound writable only so bwrap can create the mount points, then
  remounted read-only before the command runs."""
  config = image.config
  cmd = ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
         "--die-with-parent", "--new-session"]
  if not network:
    # This also hides the host's loopback, so services on its localhost (a
    # recc/bb-storage cache on :8980, proxy routes on 127.0.0.1) are gone too.
    # To keep them, they would have to listen on Unix sockets bound into the
    # sandbox, with a forwarder inside it if the client wants TCP.
    cmd.append("--unshare-net")
  cmd += ["--bind", image.rootfs, "/"] + list(proc_args(host_proc)) + ["--dev", "/dev"]
  cmd += ["--bind", tmp, "/tmp"] if tmp else ["--tmpfs", "/tmp"]
  if network:
    for f in ("/etc/resolv.conf", "/etc/hosts"):
      cmd += ["--ro-bind-try", f, f]
  for source, dest, read_only in binds:
    cmd += ["--ro-bind" if read_only else "--bind", source, dest]
  cmd += ["--remount-ro", "/", "--clearenv", "--setenv", "PATH", DEFAULT_PATH, "--setenv", "HOME", "/tmp"]
  for var, value in [e.partition("=")[::2] for e in config.get("Env") or []] + list(env):
    cmd += ["--setenv", var, value]
  cmd += ["--chdir", config.get("WorkingDir") or "/"]
  return cmd + list(extra_args)


class BwrapRunner:
  """Run commands in IMAGE under bwrap; same interface as DockerRunner."""

  def __init__(self, image, docker_image, docker_run_args=(), extra_env={}, extra_volumes=[],
               host_proc=False) -> None:
    self._image = image
    self._run_args = docker_run_args
    self._extra_env = extra_env
    self._extra_volumes = extra_volumes
    self._host_proc = host_proc

  def __enter__(self):
    cmd = bwrap_command(self._image, [parse_volume(v) for v in self._extra_volumes],
                        self._extra_env.items(), extra_args=self._run_args, host_proc=self._host_proc)

    def getstatusoutput_bwrap(command, cwd=None):
      debug("bwrap exec: %s", command)
      return getstatusoutput(cmd + ["bash", "-c", command], cwd=cwd)
    return getstatusoutput_bwrap

  def __exit__(self, exc_type, exc_value, traceback):
    return False


def confined_paths(spec, work_dir, architecture, devel_prefix):
  """Under --sandbox, what build.sh may write in the read-only work dir: the
  areas the macOS sandbox allows (package_write_paths), as bind mounts.
  Returns (trees, symlinks): host directories to bind writable, and the
  -latest symlinks, which aliBuild sets itself, as a bind mount cannot make
  a single symlink writable (see set_links). ARCH/PKG stays read-only, so the
  build can change no other version of the package."""
  work_dir = os.path.abspath(work_dir)
  subpaths, literals = package_write_paths(spec, work_dir, work_dir, architecture, devel_prefix)
  sources = os.path.join(work_dir, "SOURCES") + os.sep
  # SOURCEDIR only if checked out: a development package's is a symlink to its
  # checkout, bound writable at /PKG already.
  trees = [p for p in subpaths
           if not (p.startswith(sources) and (os.path.islink(p) or not os.path.isdir(p)))]
  return trees, literals


def set_links(spec, args, done):
  """Point the -latest symlinks of a confined build where build.sh would: those
  in BUILD at its start (DONE false), those in ARCH/PKG once it has succeeded
  (DONE true), which build.sh skips as it cannot write there."""
  _, links = confined_paths(spec, args.workDir, args.architecture, _devel_prefix(spec, args))
  build_dir = os.path.join(os.path.abspath(args.workDir), "BUILD")
  for link in links:
    in_build = os.path.dirname(link) == build_dir
    if in_build == done:
      continue
    target = spec["hash"] if in_build else "%s-%s" % (spec["version"], spec["revision"])
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if not (os.path.islink(link) and os.readlink(link) == target):
      os.symlink(target, link + ".tmp%d" % os.getpid())
      os.replace(link + ".tmp%d" % os.getpid(), link)


def _in_sandbox(path, work_dir):
  work_dir = os.path.abspath(work_dir)
  if path == work_dir or path.startswith(work_dir + os.sep):
    return "/sw" + path[len(work_dir):]
  return path


def bwrap_run_string(image, args, dockerImage, workDir, configDir, scriptDir, docker_extra_args,
                     spec, specs, volumes, buildEnvironment):
  """The bwrap counterpart of _docker_run_string: build.sh with the same
  mounts and environment as docker gives it. With --sandbox, the work dir is
  read-only, except for the areas the package owns (see confined_paths).
  /tmp is TMP/<hash> in the work dir, emptied first, so that temporary files
  count against the disk, not the memory, of the task."""
  workDir = os.path.abspath(workDir)
  confine = getattr(args, "sandbox", False)
  tmp = os.path.join(workDir, "TMP", spec["hash"])
  shutil.rmtree(tmp, ignore_errors=True)
  os.makedirs(tmp)
  # The image cache is under the work dir: keep it read-only, or a build could
  # change the image for all later ones.
  binds = [(workDir, "/sw", confine),
           (os.path.join(workDir, "CONTAINERS"), "/sw/CONTAINERS", True),
           (os.path.abspath(configDir), "/alidist", True),
           (os.path.join(scriptDir, "build.sh"), "/build.sh", True)]
  if "reference" in spec:
    binds.append((os.path.dirname(spec["reference"]), "/mirror", confine))
  if confine:
    trees, _ = confined_paths(spec, workDir, args.architecture, _devel_prefix(spec, args))
    # build.sh creates these, which it cannot do in the read-only work dir.
    for path in trees + [os.path.join(workDir, d) for d in ("BUILD", "SOURCES", "TARS", "SPECS")]:
      os.makedirs(path, exist_ok=True)
    set_links(spec, args, done=False)
    for path in getattr(args, "sandboxAllowWrite", []):
      if os.path.exists(path):
        trees.append(os.path.abspath(path))
      else:
        warning("Not allowing writes to %s, which does not exist", path)
    binds += [(p, _in_sandbox(p, workDir), False) for p in trees]
  else:
    # Make TMP/<hash> a mount point, so build.sh can empty it but not remove
    # it from under /tmp (with --sandbox, it is one of the trees).
    binds.append((tmp, _in_sandbox(tmp, workDir), False))
  for s in specs.values():
    if s["is_devel_pkg"]:
      pkg = s["package"]
      binds.append((os.path.join(os.getcwd(), os.readlink(pkg) if os.path.islink(pkg) else pkg),
                    "/" + pkg, False))
  binds += [parse_volume(v) for v in volumes]
  env = list(buildEnvironment) + [("WORK_DIR_OVERRIDE", "/sw"), ("ALIBUILD_CONFIG_DIR_OVERRIDE", "/alidist"),
                                  ("TMPDIR", "/tmp")]
  cmd = bwrap_command(image, binds, env, network=getattr(args, "containerNetwork", "host") != "none",
                      extra_args=docker_extra_args, host_proc=allow_host_proc(args), tmp=tmp)
  return " ".join(map(quote, cmd + ["bash", "-ex", "/build.sh"]))


def bwrap_failure_hint(spec, args, log_path):
  trees, symlinks = confined_paths(spec, args.workDir, args.architecture, _devel_prefix(spec, args))
  return ("This build ran in a bwrap sandbox, where the work directory is read-only except\n"
          "for the package's own directories:\n%s\n"
          "Writes elsewhere fail with \"Read-only file system\". To check:\n"
          "  grep 'Read-only file system' %s\n"
          "Allow more with --sandbox-allow-write PATH, or rebuild with --no-sandbox.\n"
          % ("".join("  %s\n" % p for p in trees + symlinks), quote(log_path)))


def _devel_prefix(spec, args):
  # As DEVEL_PREFIX in build.sh: only development packages have one.
  return getattr(args, "develPrefix", None) if spec["is_devel_pkg"] else None


def allow_host_proc(args):
  return bool(getattr(args, "containerAllowHostProc", False) or
              os.environ.get("ALIBUILD_CONTAINER_ALLOW_HOST_PROC", "") not in ("", "0"))


_images = {}


def get_image(args):
  """The Image for this run's --docker-image, shared by all callers."""
  extra = list(args.docker_extra_args)
  platform = extra[extra.index("--platform") + 1] if "--platform" in extra[:-1] else None
  key = (os.path.abspath(args.workDir), args.dockerImage, platform)
  if key not in _images:
    _images[key] = Image(args.dockerImage, os.path.join(key[0], "CONTAINERS"), platform)
  return _images[key]


def runtime(args):
  """Return the (ContainerRunner, container_run_string) pair for bwrap."""
  image = get_image(args)
  extra = list(args.docker_extra_args)
  if "--platform" in extra[:-1]:   # added for docker by args.py; it selects the image here
    del extra[extra.index("--platform"):extra.index("--platform") + 2]

  def runner(docker_image, docker_run_args=(), extra_env={}, extra_volumes=[]):
    return BwrapRunner(image, docker_image, extra, extra_env, extra_volumes, allow_host_proc(args))

  def run_string(dockerImage, workDir, configDir, scriptDir, docker_extra_args, *rest):
    return bwrap_run_string(image, args, dockerImage, workDir, configDir, scriptDir, extra, *rest)
  return runner, run_string
