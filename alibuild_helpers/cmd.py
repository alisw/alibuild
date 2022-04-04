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
  unicode = None


def is_string(s):
  if sys.version_info[0] >= 3:
    return isinstance(s, str)
  return isinstance(s, basestring)


def decode_with_fallback(data):
  """Try to decode DATA as utf-8; if that doesn't work, fall back to latin-1.

  This combination should cover every possible byte string, as latin-1 covers
  every possible single byte.
  """
  if sys.version_info[0] >= 3:
    if isinstance(data, bytes):
      try:
        return data.decode("utf-8")
      except UnicodeDecodeError:
        return data.decode("latin-1")
    else:
      return str(data)
  elif isinstance(data, str):
    return unicode(data, "utf-8")  # utf-8 is a safe assumption
  elif not isinstance(data, unicode):
    return unicode(str(data))
  return data


def getoutput(command):
  """Run command, check it succeeded, and return its stdout as a string."""
  proc = Popen(command, shell=is_string(command), stdout=PIPE, stderr=PIPE)
  stdout, stderr = proc.communicate()
  dieOnError(proc.returncode, "Command %s failed with code %d: %s" %
             (command, proc.returncode, decode_with_fallback(stderr)))
  return decode_with_fallback(stdout)


def getstatusoutput(command):
  """Run command and return its return code and output (stdout and stderr)."""
  proc = Popen(command, shell=is_string(command), stdout=PIPE, stderr=STDOUT)
  merged_output, _ = proc.communicate()
  merged_output = decode_with_fallback(merged_output)
  # Strip a single trailing newline, if one exists, to match the behaviour of
  # subprocess.getstatusoutput.
  if merged_output.endswith("\n"):
    merged_output = merged_output[:-1]
  return proc.returncode, merged_output


def execute(command, printer=debug):
  popen = Popen(command, shell=is_string(command), stdout=PIPE, stderr=STDOUT)
  for line in iter(popen.stdout.readline, b""):
    printer("%s", decode_with_fallback(line).strip("\n"))
  out = decode_with_fallback(popen.communicate()[0]).strip("\n")
  if out:
    printer("%s", out)
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
