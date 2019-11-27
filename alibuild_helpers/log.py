import logging
import sys
import re
from os import getenv
import socket, time
import datetime
from alibuild_helpers.utilities import format, to_unicode

debug, error, warning, info, success = (None, None, None, None, None)

def dieOnError(err, msg):
  if err:
    error(msg)
    sys.exit(1)

class LogFormatter(logging.Formatter):
  def __init__(self, fmtstr):
    self.fmtstr = fmtstr
    self.COLOR_RESET = "\033[m" if sys.stdout.isatty() else ""
    self.LEVEL_COLORS = { logging.WARNING:  "\033[4;33m",
                          logging.ERROR:    "\033[4;31m",
                          logging.CRITICAL: "\033[1;37;41m",
                          logging.SUCCESS:  "\033[1;32m" } if sys.stdout.isatty() else {}
  def format(self, record):
    record.msg = to_unicode(record.msg)
    if record.levelno == logging.BANNER and sys.stdout.isatty():
      lines = record.msg.split("\n")
      return "\n\033[1;34m==>\033[m \033[1m%s\033[m" % lines[0] + \
             "".join([ "\n    \033[1m%s\033[m" % x for x in lines[1:] ])
    elif record.levelno == logging.INFO or record.levelno == logging.BANNER:
      return record.msg
    return "\n".join([ format(self.fmtstr,
                              asctime = datetime.datetime.now().strftime("%Y-%m-%d@%H:%M:%S"),
                              levelname=self.LEVEL_COLORS.get(record.levelno, self.COLOR_RESET) +
                                        record.levelname +
                                        self.COLOR_RESET,
                              message=x)
                       for x in record.msg.split("\n") ])

class ProgressPrint:
  def __init__(self, begin_msg=""):
    self.count = -1
    self.lasttime = 0
    self.STAGES = [ ".", "..", "...", "....", ".....", "....", "...", ".." ]
    self.begin_msg = begin_msg
    self.percent = -1
  def __call__(self, txt):
    if time.time()-self.lasttime < 0.5:
      return
    if self.count == -1 and self.begin_msg:
      sys.stderr.write("\033[1;35m==>\033[m "+self.begin_msg)
    self.erase()
    m = re.search("((^|[^0-9])([0-9]{1,2})%|\[([0-9]+)/([0-9]+)\])", txt)
    if m:
      if m.group(3) is not None:
        self.percent = int(m.group(3))
      else:
        num = int(m.group(4))
        den = int(m.group(5))
        if num >= 0 and den > 0:
          self.percent = 100 * num / den
    if self.percent > -1:
      sys.stderr.write(" [%2d%%] " % self.percent)
    self.count = (self.count+1) % len(self.STAGES)
    sys.stderr.write(self.STAGES[self.count])
    self.lasttime = time.time()
  def erase(self):
    nerase = len(self.STAGES[self.count]) if self.count > -1 else 0
    if self.percent > -1:
      nerase = nerase + 7
    sys.stderr.write("\b"*nerase+" "*nerase+"\b"*nerase)
  def end(self, msg="", error=False):
    if self.count == -1:
      return
    self.erase()
    if msg:
      sys.stderr.write(": %s%s\033[m" % ("\033[31m" if error else "\033[32m", msg))
    sys.stderr.write("\n")

# Add loglevel BANNER (same as INFO but with more emphasis on ttys)
logging.BANNER = 25
logging.addLevelName(logging.BANNER, "BANNER")
def log_banner(self, message, *args, **kws):
  if self.isEnabledFor(logging.BANNER):
    self._log(logging.BANNER, message, args, **kws)
logging.Logger.banner = log_banner

# Add loglevel SUCCESS (same as ERROR, but green)
logging.SUCCESS = 45
logging.addLevelName(logging.SUCCESS, "SUCCESS")
def log_success(self, message, *args, **kws):
  if self.isEnabledFor(logging.SUCCESS):
    self._log(logging.SUCCESS, message, args, **kws)
logging.Logger.success = log_success

logger = logging.getLogger('alibuild')
logger_handler = logging.StreamHandler()
logger.addHandler(logger_handler)
logger_handler.setFormatter(LogFormatter("%(levelname)s: %(message)s"))

debug = logger.debug
error = logger.error
warning = logger.warning
info = logger.info
banner = logger.banner
success = logger.success
