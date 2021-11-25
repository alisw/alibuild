#!/usr/bin/env python
import os, subprocess, sys
from os.path import exists, expanduser
from os import unlink

from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.log import debug, banner


def generate_analytics_id():
  getstatusoutput("mkdir -p  ~/.config/alibuild")
  err, output = getstatusoutput("uuidgen >  ~/.config/alibuild/analytics-uuid")
  # If an error is found while generating the unique user ID, we disable
  # the analytics on the machine.
  if err:
    debug("Could not generate unique ID for user. Disabling analytics")
    getstatusoutput("touch ~/.config/alibuild/disable-analytics")
    return False
  return True

def askForAnalytics():
  banner("In order to improve user experience, aliBuild would like to gather "
         "analytics about your builds.\nYou can find all the details at:\n\n"
         "  https://github.com/alisw/alibuild/blob/master/ANALYTICS.md\n")
  # raw_input and input are different between python 2 and 3
  try: _input = raw_input
  except NameError: _input = input
  a = _input("Is that ok for you [YES/no]? ")
  if a.strip() and a.strip().lower().startswith("n"):
    debug("User requsted disabling analytics.")
    return disable_analytics()
  return generate_analytics_id()

# Helper function to decide whether or not we should run analytics.
# It's done this way so that we can easily test all the alternatives.
# This is the rationale to enable the analytics:
# - In case user disabled analytics via environment variable or by
#   answering no when prompted the first time. Just run as usual.
# - In case there is already an analytics user id, it means the user
#   already replied yes to the question wether he wants analytics or
#   not, so we proceed with analytics.
# - If we are not running in a tty, run without analytics.
# - In case there is no analytics id, ask wether is ok to have
#   analytics. If no, remember the answer and disable it. If yes,
#   generate a uuid with uuidgen and remember it.
def decideAnalytics(hasDisableFile, hasUuid, isTty, questionCallback):
  if hasDisableFile:
    debug("Analytics previously disabled.")
    return False
  if hasUuid:
    debug("User has analytics id. Pushing analytics to Google Analytics.")
    return True
  if not isTty:
    debug("This is not an interactive process and "
          "no indication has been given about analytics. Disabling")
    return False
  return questionCallback()

def report(eventType, **metadata):
  if "ALIBUILD_NO_ANALYTICS" in os.environ:
    return
  opts = {
    "v": "1",
    "tid": os.environ["ALIBUILD_ANALYTICS_ID"],
    "cid": os.environ["ALIBUILD_ANALYTICS_USER_UUID"],
    "aip": "1",
    "an": "aliBuild",
    "av": os.environ["ALIBUILD_VERSION"],
    "t": eventType
  }
  opts.update(metadata)
  architecture = os.environ["ALIBUILD_ARCHITECTURE"]
  ostype = "Macintosh" if architecture.startswith("osx") else "Linux"
  osversion, osprocessor = architecture.split("_", 1)
  args = ["curl", "--max-time", "5",
          "--user-agent", "aliBuild/%s (%s; %s %s) Python/%s" % (
                                                    os.environ["ALIBUILD_VERSION"],
                                                    ostype,
                                                    osprocessor,
                                                    osversion,
                                                    ".".join([str(x) for x in sys.version_info[:3]])
                                                   )
         ]
  for k,v in opts.items():
    if not v:
      continue
    args += ["-d", "%s=%s" %(k,v)]

  args += ["--silent", "--output", "/dev/null",
           "https://www.google-analytics.com/collect"]
  try:
    subprocess.Popen(args)
  except:
    pass

def report_event(category, action, label = "", value = None):
  report("event", ec=category, ea=action, el = label, ev = value)

def report_screenview(screen_name):
  report("screenview", cd=screen_name)

def report_timing(category, var, value, label):
  report("timing", utc=category, utv=var, utt=value, utl=label)

def report_exception(e):
  report("exception",
    exd = e.__class__.__name__,
    exf = "1")

def enable_analytics():
  if exists(expanduser("~/.config/alibuild/disable-analytics")):
    unlink(expanduser("~/.config/alibuild/disable-analytics"))
  if not exists(expanduser("~/.config/alibuild/analytics-uuid")):
    generate_analytics_id()

# We do it in getstatusoutput because python makedirs can actually fail
# if one of the intermediate directories is not writeable.
def disable_analytics():
  getstatusoutput("mkdir -p ~/.config/alibuild && touch ~/.config/alibuild/disable-analytics")
  return False

