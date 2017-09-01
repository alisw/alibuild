#!/usr/bin/env python
import sys
import os
from os.path import dirname, join, abspath
if __name__ == "__main__":
  aliBuild = join(dirname(abspath(sys.argv[0])), "aliBuild")
  os.execv(aliBuild, [ aliBuild ] + sys.argv[1:])
