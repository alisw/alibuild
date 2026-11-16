"""epn approve: sign a request of `aliBuild mcp --gated`, for its approve tool.

This is the owner's tool, on the owner's machine, not the agent's: the
signature it prints is what lets a gated server build or run what the request
says. So it shows the request, then signs it:

    python3 -m alibuild_helpers.epn_approve approve REQUEST.json
    python3 -m alibuild_helpers.epn_approve approve - < REQUEST.json

REQUEST.json is what the gated tool returned, whose "request" is signed as it
is, or that request alone. The key is $EPN_APPROVAL_KEY, by default the one
public key in Secretive's directory: Secretive's agent then signs, asking for
Touch ID.

TODO: the rest of the epn command (up, alloc, deny, down, status), and getting
requests and handing signatures over through the broker instead of by hand,
are described in smurfs-village's docs/epn-gpu-mcp-design.md, sections 3, 5
and 8.
"""

import argparse
import json
import os
import subprocess
import sys
from glob import glob
from os.path import expanduser, join

from alibuild_helpers.mcp_server import APPROVAL_NAMESPACE

SECRETIVE = "Library/Containers/com.maxgoedjen.Secretive.SecretAgent/Data"


def canonical_request(text):
  """Return the request to sign from text, as the server sent it, and its id or None."""
  data = json.loads(text)
  request_id = None
  if isinstance(data, dict) and isinstance(data.get("request"), str):
    request_id, text = data.get("id"), data["request"]
    data = json.loads(text)
  text = text.strip()
  if text != json.dumps(data, sort_keys=True, separators=(",", ":")):
    raise ValueError("not a request as the server sends it, with sorted keys and no whitespace")
  return text, request_id


def approval_key(environ):
  if environ.get("EPN_APPROVAL_KEY"):
    return expanduser(environ["EPN_APPROVAL_KEY"])
  directory = join(environ.get("HOME", ""), SECRETIVE, "PublicKeys")
  keys = glob(join(directory, "*.pub"))
  if len(keys) != 1:
    raise ValueError("found %d keys in %s: set EPN_APPROVAL_KEY to the owner's key, the public "
                     "key of a Secretive key there, or another key ssh-keygen -Y sign -f takes"
                     % (len(keys), directory))
  return keys[0]


def approve(text, environ=os.environ, log=sys.stderr):
  """Show the request in text, and return its signature."""
  text, request_id = canonical_request(text)
  key = approval_key(environ)
  env = dict(environ)
  secretive = join(environ.get("HOME", ""), SECRETIVE)
  if key.startswith(secretive + os.sep):
    env["SSH_AUTH_SOCK"] = join(secretive, "socket.ssh")
  print(json.dumps(json.loads(text), indent=2, sort_keys=True), file=log)
  print("Signing request %s with %s, for namespace %s" % (request_id or "above", key,
                                                          APPROVAL_NAMESPACE), file=log)
  proc = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", key, "-n", APPROVAL_NAMESPACE],
                        input=text, env=env, text=True, stdout=subprocess.PIPE)
  if proc.returncode:
    raise ValueError("ssh-keygen -Y sign failed with %d" % proc.returncode)
  return proc.stdout


def main(argv=None):
  parser = argparse.ArgumentParser(prog="epn", description="Approve what agents ask to run.")
  actions = parser.add_subparsers(dest="action", required=True)
  p = actions.add_parser("approve", help="show a request and sign it, for the approve tool")
  p.add_argument("request", metavar="REQUEST.json", help="The request, or - for stdin.")
  args = parser.parse_args(argv)
  try:
    if args.request == "-":
      text = sys.stdin.read()
    else:
      with open(args.request) as f:
        text = f.read()
    sys.stdout.write(approve(text))
  except (OSError, ValueError) as exc:
    print("epn: %s" % exc, file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  sys.exit(main())
