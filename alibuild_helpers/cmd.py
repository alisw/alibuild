import os
import os.path
import time
from subprocess import Popen, PIPE, STDOUT
from textwrap import dedent
from subprocess import TimeoutExpired
from shlex import quote
import platform

from alibuild_helpers.log import debug, error, dieOnError

def decode_with_fallback(data):
  """Try to decode DATA as utf-8; if that doesn't work, fall back to latin-1.

  This combination should cover every possible byte string, as latin-1 covers
  every possible single byte.
  """
  if isinstance(data, bytes):
    try:
      return data.decode("utf-8")
    except UnicodeDecodeError:
      return data.decode("latin-1")
  else:
    return str(data)


def getoutput(command, timeout=None):
  """Run command, check it succeeded, and return its stdout as a string."""
  proc = Popen(command, shell=isinstance(command, str), stdout=PIPE, stderr=PIPE)
  try:
    stdout, stderr = proc.communicate(timeout=timeout)
  except TimeoutExpired:
    error("Process %r timed out; terminated", command)
    proc.terminate()
    stdout, stderr = proc.communicate()
  dieOnError(proc.returncode, "Command %s failed with code %d: %s" %
             (command, proc.returncode, decode_with_fallback(stderr)))
  return decode_with_fallback(stdout)


def getstatusoutput(command, timeout=None, cwd=None):
  """Run command and return its return code and output (stdout and stderr)."""
  proc = Popen(command, shell=isinstance(command, str), stdout=PIPE, stderr=STDOUT, cwd=cwd)
  try:
    merged_output, _ = proc.communicate(timeout=timeout)
  except TimeoutExpired:
    error("Process %r timed out; terminated", command)
    proc.terminate()
    merged_output, _ = proc.communicate()
  merged_output = decode_with_fallback(merged_output)
  # Strip a single trailing newline, if one exists, to match the behaviour of
  # subprocess.getstatusoutput.
  if merged_output.endswith("\n"):
    merged_output = merged_output[:-1]
  return proc.returncode, merged_output


def execute(command, printer=debug, timeout=None):
  popen = Popen(command, shell=isinstance(command, str), stdout=PIPE, stderr=STDOUT)
  start_time = time.time()
  for line in iter(popen.stdout.readline, b""):
    printer("%s", decode_with_fallback(line).strip("\n"))
    if timeout is not None and time.time() > start_time + timeout:
      popen.terminate()
      break
  out = decode_with_fallback(popen.communicate()[0]).strip("\n")
  if out:
    printer("%s", out)
  return popen.returncode


BASH = "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"

class AppleContainerRunner:
    """A context manager for running commands inside a Apple Container (see https://github.com/apple/container)
       If the image given is None or empty, the commands are run on the host instead.
    """
    def __init__(self, container_image, container_run_args, extra_env, extra_volumes) -> None:
        self._container_image = container_image
        self._container_run_args = container_run_args
        self._container = None
        self._extra_env = extra_env
        self._extra_volumes = extra_volumes

    def __enter__(self):
        if not self._container_image:
            return
        envOpts = [opt for k, v in self._extra_env.items() for opt in ("-e", f"{k}={v}")]
        volumes = [opt for v in self._extra_volumes for opt in ("-v", v)]
        # Apple Container is more picky about missing entrypoints, so we always override it
        # with /bin/sleep.
        cmd = ["container", "run", "--detach"] + envOpts + volumes + ["--rm", "--entrypoint=/bin/sleep"]
        cmd += self._container_run_args
        cmd += [self._container_image, "inf"]
        self._container = getoutput(cmd).strip()

        def getstatusoutput_container(cmd, cwd=None):
            if self._container is None:
                command_prefix=""
                if self._extra_env:
                    command_prefix="env " + " ".join("{}={}".format(k, quote(v)) for (k,v) in self._extra_env.items()) + " "
                return getstatusoutput("{}{} -c {}".format(command_prefix, BASH, quote(cmd))
                                    , cwd=cwd)
            envOpts = [opt for k, v in self._extra_env.items() for opt in ("-e", f"{k}={v}")]
            exec_cmd = ["container", "exec"] + envOpts + [self._container, "bash", "-c", cmd]
            return getstatusoutput(exec_cmd, cwd=cwd)

        return getstatusoutput_container

    def __exit__(self, exc_type, exc_value, traceback):
        if self._container is not None:
            getstatusoutput("container kill " + quote(self._container))
        self._container = None
        return False  # propagate any exception that may have occurred


class DockerRunner:
  """A context manager for running commands inside a Docker container.

  If the Docker image given is None or empty, the commands are run on the host
  instead.
  """

  def __init__(self, docker_image, docker_run_args=(), extra_env={}, extra_volumes=[]) -> None:
    self._docker_image = docker_image
    self._docker_run_args = docker_run_args
    self._container = None
    self._extra_env = extra_env
    self._extra_volumes = extra_volumes

  def __enter__(self):
    if self._docker_image:
      # "sleep inf" pauses forever, until we kill it.
      envOpts = [opt for k, v in self._extra_env.items() for opt in ("-e", f"{k}={v}")]
      volumes = [opt for v in self._extra_volumes for opt in ("-v", v)]
      cmd = ["docker", "run", "--detach"] + envOpts + volumes + ["--rm", "--entrypoint="]
      cmd += self._docker_run_args
      cmd += [self._docker_image, "sleep", "inf"]
      self._container = getoutput(cmd).strip()

    def getstatusoutput_docker(cmd, cwd=None):
      if self._container is None:
        command_prefix=""
        if self._extra_env:
          command_prefix="env " + " ".join(f"{k}={quote(v)}" for (k,v) in self._extra_env.items()) + " "
        return getstatusoutput(f"{command_prefix}{BASH} -c {quote(cmd)}"
                             , cwd=cwd)
      envOpts = []
      for env in self._extra_env.items():
        envOpts.append("-e")
        envOpts.append(f"{env[0]}={env[1]}")
      exec_cmd = ["docker", "container", "exec"] + envOpts + [self._container, "bash", "-c", cmd]
      return getstatusoutput(exec_cmd, cwd=cwd)

    return getstatusoutput_docker

  def __exit__(self, exc_type, exc_value, traceback):
    if self._container is not None:
      # 'docker container stop' sends SIGTERM, which doesn't work on 'sleep'
      # for some reason. Kill it directly instead, so we don't have to wait.
      getstatusoutput("docker container kill " + quote(self._container))
    self._container = None
    return False   # propagate any exception that may have occurred


def install_wrapper_script(name, work_dir):
  script_dir = os.path.join(work_dir, "wrapper-scripts")
  try:
    os.makedirs(script_dir)
  except OSError as exc:
    # Errno 17 means the directory already exists.
    if exc.errno != 17:
      raise
  # Create a wrapper script that cleans up the environment, so we don't see the
  # OpenSSL built by aliBuild.
  with open(os.path.join(script_dir, name), "w") as scriptf:
    # Compute the "real" executable path each time, as the wrapper script might
    # be called on the host or in a container.
    scriptf.write(dedent("""\
    #!/bin/sh
    exec env -u LD_LIBRARY_PATH -u DYLD_LIBRARY_PATH \\
         "$(which -a "$(basename "$0")" | grep -Fxv "$0" | head -1)" "$@"
    """))
    os.fchmod(scriptf.fileno(), 0o755)  # make the wrapper script executable
  # If $PATH is empty, this is bad, because we need to fall back to the "real"
  # executable that our script is wrapping.
  dieOnError(not os.environ.get("PATH"),
             "$PATH is unset or empty. Cannot find any executables. Try "
             "rerunning this command inside a login shell (e.g. `bash -l`). "
             "If that doesn't work, run `export PATH` manually.")
  os.environ["PATH"] = script_dir + ":" + os.environ["PATH"]

def to_int(s: str) -> int:
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _apple_run_string(dockerImage, workDir, configDir, scriptDir, docker_extra_args, spec, specs, volumes, buildEnvironment):
    build_command = (
        "container run --rm --entrypoint=/bin/bash --user $(id -u):$(id -g) "
        "--mount type=bind,source={workdir},target=/sw "
        "--mount type=bind,source={configDir},target=/alidist,readonly "
        "--mount type=bind,source={scriptDir},target=/scripts,readonly "
        "{mirrorVolume} {develVolumes} {additionalEnv} {additionalVolumes} "
        "-e WORK_DIR_OVERRIDE=/sw -e ALIBUILD_CONFIG_DIR_OVERRIDE=/alidist {extraArgs} {image} -ex /scripts/build.sh"
    ).format(
        image=quote(dockerImage),
        workdir=quote(os.path.abspath(workDir)),
        configDir=quote(os.path.abspath(configDir)),
        scriptDir=quote(scriptDir),
        extraArgs=" ".join(map(quote, docker_extra_args)),
        additionalEnv=" ".join(
            "-e {}={}".format(var, quote(value)) for var, value in buildEnvironment
        ),
        # Used e.g. by O2DPG-sim-tests to find the O2DPG repository.
        develVolumes=" ".join(
            '--mount type=bind,source="$PWD/$(readlink {pkg} || echo {pkg})",target=/{pkg},readonly'.format(
                pkg=quote(s["package"])
            )
            for s in specs.values()
            if s["is_devel_pkg"]
        ),
        additionalVolumes=" ".join("--mount type=bind,source=%s" % quote(volume) for volume in volumes),
        mirrorVolume=(
            "--mount source=%s,target=/mirror" % quote(os.path.dirname(spec["reference"]))
            if "reference" in spec
            else ""
        ),
    )
    print(build_command)
    return build_command

def _docker_run_string( dockerImage, workDir, configDir, scriptDir, docker_extra_args, spec, specs, volumes, buildEnvironment):
    build_command = (
        "docker run --rm --entrypoint=/bin/bash --user $(id -u):$(id -g) "
        "-v {workdir}:/sw -v{configDir}:/alidist:ro -v {scriptDir}/build.sh:/build.sh:ro "
        "{mirrorVolume} {develVolumes} {additionalEnv} {additionalVolumes} "
        "-e WORK_DIR_OVERRIDE=/sw -e ALIBUILD_CONFIG_DIR_OVERRIDE=/alidist {extraArgs} --network=host {image} bash -ex /build.sh"
    ).format(
        image=quote(dockerImage),
        workdir=quote(os.path.abspath(workDir)),
        configDir=quote(os.path.abspath(configDir)),
        scriptDir=quote(scriptDir),
        extraArgs=" ".join(map(quote, docker_extra_args)),
        additionalEnv=" ".join(
            "-e {}={}".format(var, quote(value)) for var, value in buildEnvironment
        ),
        # Used e.g. by O2DPG-sim-tests to find the O2DPG repository.
        develVolumes=" ".join(
            '-v "$PWD/$(readlink {pkg} || echo {pkg})":/{pkg}:rw'.format(
                pkg=quote(spec["package"])
            )
            for spec in specs.values()
            if spec["is_devel_pkg"]
        ),
        additionalVolumes=" ".join("-v %s" % quote(volume) for volume in volumes),
        mirrorVolume=(
            "-v %s:/mirror" % quote(os.path.dirname(spec["reference"]))
            if "reference" in spec
            else ""
        ),
    )
    return build_command


if to_int(platform.mac_ver()[0].split(".")[0]) >= 26:
    ContainerRunner = AppleContainerRunner
    container_run_string = _apple_run_string
else:
    ContainerRunner = DockerRunner
    container_run_string = _docker_run_string
