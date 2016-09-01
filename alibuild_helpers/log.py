import logging
import sys
from os import getenv
import socket, time
from alibuild_helpers.utilities import format

debug, error, warning, info, success, riemannStream = (None, None, None, None, None, None)

# A stream object which will end up pushing data to a riemann server
class RiemannStream(object):
  def __init__(self, host, port):
    self.currentHost = socket.gethostname()
    self.buffer = ""
    self.state = None
    self.enabled = False
    self.attributes = {}
    self.begin = time.time()
    if not host:
      return
    try:
      import bernhard
      self.client = bernhard.Client(host=host, port=port)
      self.client.send({'host': self.currentHost, 'state': 'ok', 'service': "alibuild started"})
      self.enabled = True
      info("Sending log data to %s:%s" % (host, port))
    except Exception as e:
      info("RIEMANN_HOST %s:%s specified, however there was a problem initialising:"  % (host, port))
      info(e)

  def setAttributes(self, **attributes):
    self.attributes = attributes
    self.begin = time.time()
    self.attributes["start_time"] = self.begin

  def setState(self, state):
    self.state = state

  def write(self, s):
    self.buffer += s

  def flush(self):
    for x in self.buffer.strip("\n").split("\n"):
      serviceLabel = ""
      if "package" in self.attributes:
        serviceLabel += " %(package)s@%(package_hash)s" % self.attributes
      if "architecture" in self.attributes:
        serviceLabel += " " + self.attributes["architecture"]
      payload = {'host': self.currentHost,
                 'service': 'alibuild_log%s' % serviceLabel,
                 'description': x.decode('utf-8').encode('ascii','ignore'),
                 'ttl': getenv("RIEMANN_TTL", 60),
                 'metric': time.time() - self.begin
                }
      payload.update({'attributes': self.attributes})
      if self.state:
        payload['state'] = self.state
      try:
        self.client.send(payload)
      except:
        pass
    self.buffer = ""

class LogFormatter(logging.Formatter):
  def __init__(self, fmtstr):
    self.fmtstr = fmtstr
    self.COLOR_RESET = "\033[m" if sys.stdout.isatty() else ""
    self.LEVEL_COLORS = { logging.WARNING:  "\033[4;33m",
                          logging.ERROR:    "\033[4;31m",
                          logging.CRITICAL: "\033[1;37;41m",
                          logging.SUCCESS:  "\033[1;32m" } if sys.stdout.isatty() else {}
  def format(self, record):
    if record.levelno == logging.BANNER and sys.stdout.isatty():
      lines = str(record.msg).split("\n")
      return "\n\033[1;34m==>\033[m \033[1m%s\033[m" % lines[0] + \
             "".join([ "\n    \033[1m%s\033[m" % x for x in lines[1:] ])
    elif record.levelno == logging.INFO or record.levelno == logging.BANNER:
      return str(record.msg)
    return "\n".join([ format(self.fmtstr,
                              levelname=self.LEVEL_COLORS.get(record.levelno, self.COLOR_RESET) +
                                        record.levelname +
                                        self.COLOR_RESET,
                              message=x)
                       for x in str(record.msg).split("\n") ])

class ProgressPrint:
  def __init__(self, begin_msg=""):
    self.count = -1
    self.lasttime = 0
    self.STAGES = [ ".", "..", "...", "....", ".....", "....", "...", ".." ]
    self.begin_msg = begin_msg
  def __call__(self, txt):
    if time.time()-self.lasttime < 0.5:
      return
    if self.count == -1 and self.begin_msg:
      sys.stderr.write("\033[1;35m==>\033[m "+self.begin_msg)
    self.erase()
    self.count = (self.count+1) % len(self.STAGES)
    sys.stderr.write(self.STAGES[self.count])
    self.lasttime = time.time()
  def erase(self):
    nerase = len(self.STAGES[self.count]) if self.count > -1 else 0
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

riemannStream = RiemannStream(host=getenv("RIEMANN_HOST"),
                              port=getenv("RIEMANN_PORT", "5555"))
# If the RiemannStreamer can be used, we add it to those use during
# printout.
if riemannStream.enabled:
  logger.addHandler(logging.StreamHandler(riemannStream))
