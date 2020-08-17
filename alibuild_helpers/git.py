try:
  from commands import getstatusoutput
except ImportError:
  from subprocess import getstatusoutput

def __partialCloneFilter():
  err, out = getstatusoutput("LANG=C git clone --filter=blob:none 2>&1 | grep 'unknown option'")
  return err and "--filter=blob:none" or ""

partialCloneFilter = __partialCloneFilter()
