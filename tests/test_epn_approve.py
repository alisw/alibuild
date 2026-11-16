import io
import json
import os
import subprocess
import tempfile
import unittest
from os.path import join

from alibuild_helpers import epn_approve
from alibuild_helpers.mcp_server import Server


class EpnApproveTestCase(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", join(self.tmp.name, "k")],
                   check=True)
    # Only ever this throwaway key: HOME has no Secretive keys.
    self.environ = {"HOME": self.tmp.name, "PATH": os.environ["PATH"],
                    "EPN_APPROVAL_KEY": join(self.tmp.name, "k")}
    self.server = Server(join(self.tmp.name, "sw"), root=self.tmp.name,
                         approvals_key=join(self.tmp.name, "k.pub"))

  def test_approve(self) -> None:
    asked = self.server.call("run", {"argv": ["true"]})
    log = io.StringIO()
    signature = epn_approve.approve(json.dumps(asked, indent=2), self.environ, log)
    self.assertIn(asked["id"], log.getvalue())
    self.assertIn('"action": "run"', log.getvalue())
    self.assertEqual(self.server.call("approve", {"id": asked["id"], "signature": signature}),
                     {"status": "approved", "id": asked["id"]})
    # The request alone is signed the same way.
    signature = epn_approve.approve(asked["request"] + "\n", self.environ, log)
    self.server.call("approve", {"id": asked["id"], "signature": signature})

  def test_refused(self) -> None:
    asked = self.server.call("run", {"argv": ["true"]})
    request = json.loads(asked["request"])
    with self.assertRaises(ValueError):
      epn_approve.approve(json.dumps(request, indent=2), self.environ, io.StringIO())
    environ = dict(self.environ)
    del environ["EPN_APPROVAL_KEY"]
    with self.assertRaisesRegex(ValueError, "EPN_APPROVAL_KEY"):
      epn_approve.approve(asked["request"], environ, io.StringIO())


if __name__ == '__main__':
  unittest.main()
