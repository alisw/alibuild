"""What a running build is doing, for programs watching it, e.g. `aliBuild mcp`.

When ALIBUILD_STATUS_FILE is set, the build keeps a small JSON object there up
to date: which package it is on, and whether it is waiting for a package lock
or a build slot, or building. Without it, nothing is written.
"""

import json
import os
import time


def update(environ=os.environ, **fields):
  path = environ.get("ALIBUILD_STATUS_FILE")
  if not path:
    return
  try:
    with open(path) as f:
      status = json.load(f)
  except (OSError, ValueError):
    status = {}
  status.update(fields, updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
  try:
    with open(path + ".tmp", "w") as f:
      json.dump(status, f, indent=2)
    os.replace(path + ".tmp", path)
  except OSError:
    pass  # Watching a build must never break it.
