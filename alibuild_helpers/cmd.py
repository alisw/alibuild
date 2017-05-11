from alibuild_helpers.log import debug
from alibuild_helpers.utilities import is_string
import subprocess

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

