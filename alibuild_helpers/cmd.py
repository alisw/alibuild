try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from alibuild_helpers.log import debug
from alibuild_helpers.utilities import is_string, to_unicode
import subprocess

BASH = "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"

def execute(command, printer=debug):
  popen = subprocess.Popen(command, shell=is_string(command), stdout=subprocess.PIPE)
  lines_iterator = iter(popen.stdout.readline, "")
  for line in lines_iterator:
    if not line: break
    printer(to_unicode(line).strip("\n")) # yield line
  out = to_unicode(popen.communicate()[0]).strip("\n")
  if out:
    printer(out)
  return popen.returncode

def getStatusOutputBash(command):
  assert is_string(command), "only strings accepted as command"
  popen = subprocess.Popen([ BASH, "-c", command ], shell=False,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  out = to_unicode(popen.communicate()[0])
  return (popen.returncode, out)
