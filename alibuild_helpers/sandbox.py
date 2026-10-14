"""Confine macOS builds with seatbelt (sandbox-exec).

The recipe of each package runs under a profile which allows everything except
writing outside the areas that package owns in the work directory: its BUILD,
INSTALLROOT, TMP and TARS entries, its final installation directory and its own
SOURCEDIR. Temporary and per-user cache directories stay writable, as compilers
and Xcode's tools need them. Reads and network access are not restricted.

Source checkout, remote store access and uploads all happen in aliBuild itself,
outside the sandbox. Only build.sh is confined: the recipe, plus the unpacking,
relocation and packaging around it.
"""

import os
import subprocess
import sys
from os.path import abspath, dirname, expanduser, join, realpath
from shlex import quote

from alibuild_helpers.utilities import short_commit_hash

SANDBOX_EXEC = "/usr/bin/sandbox-exec"

# Writable everywhere: compilers, xcrun and friends put their scratch files and
# caches here, and none of it ends up in a package.
COMMON_WRITABLE_SUBPATHS = ["/private/tmp", "/private/var/tmp"]
COMMON_WRITABLE_LITERALS = ["/dev/null", "/dev/zero", "/dev/tty", "/dev/ptmx",
                            "/dev/dtracehelper"]
COMMON_WRITABLE_REGEXES = [r"^/dev/fd/", r"^/dev/ttys[0-9]+$"]

# What creating or updating a directory needs, without allowing anything to be
# written inside it. rsync and mkdir -p touch the parents of what they create.
DIRECTORY_OPERATIONS = ("file-write-create", "file-write-mode", "file-write-owner",
                        "file-write-times", "file-write-flags")


def sandbox_check():
  """Return None if builds can be sandboxed here, or the reason they cannot."""
  if sys.platform != "darwin":
    return "--sandbox is only supported on macOS"
  if not os.path.exists(SANDBOX_EXEC):
    return "%s not found" % SANDBOX_EXEC
  # Seatbelt sandboxes do not nest: if we are already running in one (e.g. a CI
  # agent or another tool's sandbox), applying ours fails.
  try:
    err = subprocess.call([SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  except OSError as exc:
    return "cannot run %s: %s" % (SANDBOX_EXEC, exc)
  if err:
    return ("%s does not work here; are we already running in a sandbox? "
            "Seatbelt sandboxes cannot be nested" % SANDBOX_EXEC)
  return None


def _darwin_user_dir(name):
  try:
    out = subprocess.check_output(["/usr/bin/getconf", name], stderr=subprocess.DEVNULL)
  except (OSError, subprocess.CalledProcessError):
    return None
  return out.decode().strip() or None


def _variants(path):
  """The path as given and resolved: seatbelt matches the resolved path (e.g.
  /private/tmp rather than /tmp), but keeping both does no harm."""
  path = abspath(path)
  return list(dict.fromkeys([path, realpath(path)]))


def sandbox_paths(spec, work_dir, build_work_dir, architecture, devel_prefix,
                  extra_writable=(), environ=os.environ):
  """Compute what the build of spec may write to.

  Returns (subpaths, literals, directories): trees which are fully writable,
  single paths (the -latest symlinks) which are, and parent directories which may
  be created and have their metadata updated, but not be written into.
  """
  pkg, version, revision, pkghash = spec["package"], spec["version"], spec["revision"], spec["hash"]
  pkgpath = join(architecture, pkg, "%s-%s" % (version, revision))
  # Must match SOURCEDIR in build_template.sh. For development packages, this
  # is a symlink to the user's checkout, which we resolve below.
  sourcedir = join(work_dir, "SOURCES", pkg, version, short_commit_hash(spec))

  subpaths = [
    join(build_work_dir, "BUILD", pkghash),
    join(work_dir, "INSTALLROOT", pkghash),
    join(work_dir, "TMP", pkghash),
    join(work_dir, "TARS", architecture, "store", pkghash[:2], pkghash),
    join(work_dir, "TARS", architecture, pkg),
    join(work_dir, pkgpath),
    sourcedir,
  ]
  subpaths += [p for p in extra_writable if p]
  if environ.get("CCACHE_DIR"):
    subpaths.append(environ["CCACHE_DIR"])
  for name in ("DARWIN_USER_TEMP_DIR", "DARWIN_USER_CACHE_DIR"):
    user_dir = _darwin_user_dir(name)
    if user_dir:
      subpaths.append(user_dir)
  subpaths.append(expanduser("~/Library/Caches"))

  literals = [
    join(build_work_dir, "BUILD", pkg + "-latest"),
    join(work_dir, architecture, pkg, "latest"),
  ]
  if devel_prefix:
    literals.append(join(build_work_dir, "BUILD", "%s-latest-%s" % (pkg, devel_prefix)))
  if spec.get("build_family"):
    literals.append(join(work_dir, architecture, pkg, "latest-" + spec["build_family"]))

  # Every directory between the work directory and what we write to, as the
  # build script creates them with mkdir -p and rsync updates their metadata.
  directories = []
  for top in (work_dir, build_work_dir):
    top = abspath(top)
    for path in subpaths + literals:
      path = dirname(abspath(path))
      while path.startswith(top + os.sep) or path == top:
        directories.append(path)
        if path == top:
          break
        path = dirname(path)
  for top in (work_dir, build_work_dir):
    directories += [join(top, d) for d in ("BUILD", "SOURCES", "TARS", "SPECS", "INSTALLROOT", "TMP")]

  def expand(paths):
    return list(dict.fromkeys(v for p in paths for v in _variants(p)))
  return expand(subpaths), expand(literals), expand(directories)


def _string(path):
  return '"%s"' % path.replace("\\", "\\\\").replace('"', '\\"')


def sandbox_profile(subpaths, literals, directories):
  """Render a seatbelt profile allowing writes only to the given paths."""
  lines = [
    ";; Generated by aliBuild. Replay a build with:",
    ";;   sandbox-exec -f <this file> /bin/bash -e -x build.sh",
    "(version 1)",
    "(allow default)",
    "(deny file-write*)",
    "(allow file-write*",
  ]
  lines += ["  (subpath %s)" % _string(p) for p in COMMON_WRITABLE_SUBPATHS + list(subpaths)]
  lines += ["  (literal %s)" % _string(p) for p in COMMON_WRITABLE_LITERALS + list(literals)]
  lines += ["  (regex #%s)" % _string(r) for r in COMMON_WRITABLE_REGEXES]
  lines[-1] += ")"
  if directories:
    lines.append("(allow %s" % " ".join(DIRECTORY_OPERATIONS))
    lines += ["  (literal %s)" % _string(p) for p in directories]
    lines[-1] += ")"
  return "\n".join(lines) + "\n"


def sandboxed_command(profile_path, command):
  """Prefix a shell command line so that it runs under the given profile."""
  return "%s -f %s %s" % (SANDBOX_EXEC, quote(profile_path), command)


def write_sandbox_profile(script_dir, spec, work_dir, build_work_dir, architecture,
                          devel_prefix, extra_writable=()):
  """Write the profile for spec next to its build.sh, and return its path."""
  profile = sandbox_profile(*sandbox_paths(spec, work_dir, build_work_dir, architecture,
                                           devel_prefix, extra_writable))
  profile_path = join(script_dir, "sandbox.sb")
  with open(profile_path, "w") as f:
    f.write(profile)
  return profile_path


def sandbox_failure_hint(script_dir, log_path):
  # Denials are not reliably visible in the unified log (recent macOS versions
  # redact or drop them), so point at what can be checked: the build log, where
  # blocked writes fail with EPERM, and the profile which was applied.
  return ("This build ran in a macOS sandbox, which only allows writing to the package's\n"
          "own directories. To check if it blocked something:\n"
          "  grep 'Operation not permitted' %s\n"
          "The profile used is %s.\n"
          "Allow more with --sandbox-allow-write PATH, or rebuild with --no-sandbox.\n"
          % (quote(log_path), join(script_dir, "sandbox.sb")))
