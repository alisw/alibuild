import os
import os.path
import sys
from subprocess import Popen, PIPE, STDOUT
from textwrap import dedent
try:
  from shlex import quote  # Python 3.3+
except ImportError:
  from pipes import quote  # Python 2.7

from alibuild_helpers.log import debug, dieOnError

# Keep the linter happy
if sys.version_info[0] >= 3:
  basestring = str


def is_string(s):
  if sys.version_info[0] >= 3:
    return isinstance(s, str)
  return isinstance(s, basestring)


def getoutput(command):
  """Run command, check it succeeded, and return its stdout as a string."""
  kwargs = {} if sys.version_info.major < 3 else {"encoding": "utf-8"}
  proc = Popen(command, shell=is_string(command), stdout=PIPE, stderr=PIPE,
               universal_newlines=True, **kwargs)
  stdout, stderr = proc.communicate()
  dieOnError(proc.returncode, "Command %s failed with code %d: %s" %
             (command, proc.returncode, stderr))
  return stdout


def getstatusoutput(command):
  """Run command and return its return code and output (stdout and stderr)."""
  kwargs = {} if sys.version_info.major < 3 else {"encoding": "utf-8"}
  proc = Popen(command, shell=is_string(command), stdout=PIPE, stderr=STDOUT,
               universal_newlines=True, **kwargs)
  merged_output, _ = proc.communicate()
  # Strip a single trailing newline, if one exists, to match the behaviour of
  # subprocess.getstatusoutput.
  if merged_output.endswith("\n"):
    merged_output = merged_output[:-1]
  return proc.returncode, merged_output


def execute(command, printer=debug):
  kwargs = {} if sys.version_info.major < 3 else {"encoding": "utf-8"}
  popen = Popen(command, shell=is_string(command), stdout=PIPE,
                universal_newlines=True, **kwargs)
  lines_iterator = iter(popen.stdout.readline, "")
  for line in lines_iterator:
    if not line: break
    printer("%s", line.strip("\n"))
  out = popen.communicate()[0].strip("\n")
  if out:
    printer(out)
  return popen.returncode


BASH = "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"


class DockerRunner:
  """A context manager for running commands inside a Docker container.

  If the Docker image given is None or empty, the commands are run on the host
  instead.
  """

  def __init__(self, docker_image, docker_run_args=()):
    self._docker_image = docker_image
    self._docker_run_args = docker_run_args
    self._container = None

  def __enter__(self):
    if self._docker_image:
      # "sleep inf" pauses forever, until we kill it.
      cmd = ["docker", "run", "--detach", "--rm"]
      cmd += self._docker_run_args
      cmd += [self._docker_image, "sleep", "inf"]
      self._container = getoutput(cmd).strip()

    def getstatusoutput_docker(cmd):
      if self._container is None:
        return getstatusoutput("{} -c {}".format(BASH, quote(cmd)))
      return getstatusoutput("docker container exec {} bash -c {}"
                             .format(quote(self._container), quote(cmd)))

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
  os.environ["PATH"] = script_dir + ":" + os.environ["PATH"]
