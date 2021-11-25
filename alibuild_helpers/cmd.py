import subprocess
import sys
try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
try:
  from shlex import quote  # Python 3.3+
except ImportError:
  from pipes import quote  # Python 2.7

from alibuild_helpers.log import debug

BASH = "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"

# Keep the linter happy
if sys.version_info[0] >= 3:
  basestring = None


def is_string(s):
  if sys.version_info[0] >= 3:
    return isinstance(s, str)
  return isinstance(s, basestring)


def execute(command, printer=debug):
  popen = subprocess.Popen(command, shell=is_string(command), stdout=subprocess.PIPE,
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
  popen = subprocess.Popen([ BASH, "-c", command ], shell=False,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
  out = popen.communicate()[0]
  return (popen.returncode, out)

def dockerStatusOutput(cmd, dockerImage=None, executor=getstatusoutput):
  return executor("docker run --rm --entrypoint= {image} bash -c {command}"
                  .format(image=dockerImage, command=quote(cmd))
                  if dockerImage else cmd)
