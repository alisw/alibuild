import sys
from subprocess import Popen, PIPE, STDOUT
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
try:
  from shlex import quote  # Python 3.3+
except ImportError:
  from pipes import quote  # Python 2.7

from alibuild_helpers.log import debug, dieOnError

BASH = "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"

# Keep the linter happy
if sys.version_info[0] >= 3:
  basestring = None


def is_string(s):
  if sys.version_info[0] >= 3:
    return isinstance(s, str)
  return isinstance(s, basestring)


def getoutput(command):
  """Run command, check it succeeded, and return its stdout as a string."""
  proc = Popen(command, shell=is_string(command), stdout=PIPE, stderr=PIPE,
               universal_newlines=True)
  stdout, stderr = proc.communicate()
  dieOnError(proc.returncode, "Command %s failed with code %d: %s" %
             (command, proc.returncode, stderr))
  return stdout


def execute(command, printer=debug):
  popen = Popen(command, shell=is_string(command), stdout=PIPE,
                universal_newlines=True)
  lines_iterator = iter(popen.stdout.readline, "")
  for line in lines_iterator:
    if not line: break
    printer("%s", line.strip("\n"))
  out = popen.communicate()[0].strip("\n")
  if out:
    printer(out)
  return popen.returncode


def getStatusOutputBash(command):
  assert is_string(command), "only strings accepted as command"
  popen = Popen([BASH, "-c", command], shell=False, stdout=PIPE, stderr=STDOUT,
                universal_newlines=True)
  out, _ = popen.communicate()
  return popen.returncode, out


def dockerStatusOutput(cmd, dockerImage=None, executor=getstatusoutput):
  return executor("docker run --rm --entrypoint= {image} bash -c {command}"
                  .format(image=dockerImage, command=quote(cmd))
                  if dockerImage else cmd)
