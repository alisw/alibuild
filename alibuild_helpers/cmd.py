try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput
from alibuild_helpers.log import debug
from alibuild_helpers.utilities import is_string, cache
import subprocess

@cache
def bashInterpreter():
  # Given we started by enforcing /bin/bash we keep enforcing it, however if it's
  # somewhere else on system, e.g. on NixOS, we fallback to the one in path.
  return "bash" if getstatusoutput("/bin/bash --version")[0] else "/bin/bash"

def execute(command, printer=debug):
  popen = subprocess.Popen(command, shell=is_string(command), stdout=subprocess.PIPE)
  lines_iterator = iter(popen.stdout.readline, "")
  for line in lines_iterator:
    if not line: break
    printer(line.decode('utf-8', 'ignore').strip("\n"))  # yield line
  output = popen.communicate()[0]
  printer(output)
  exitCode = popen.returncode
  return exitCode

def getStatusOutputBash(command):
  if is_string(command):
    command = [ bashInterpreter(), "-c", command ]
  popen = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
  lines_iterator = iter(popen.stdout.readline, "")
  txt = ""
  for line in lines_iterator:
    if not line: break
    txt += line.decode('utf-8', "ignore") # yield line
  txt += popen.communicate()[0].decode('utf-8', 'ignore')
  return (popen.returncode, txt)
