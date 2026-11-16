import json
import os
import tempfile
import unittest
from os.path import join

from alibuild_helpers import buildstatus


class BuildStatusTestCase(unittest.TestCase):
  def test_update(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
      path = join(tmp, "status.json")
      buildstatus.update(environ={}, state="building")  # without the variable, nothing
      self.assertFalse(os.path.exists(path))
      env = {"ALIBUILD_STATUS_FILE": path}
      buildstatus.update(environ=env, state="waiting for a build slot", package="ROOT")
      buildstatus.update(environ=env, state="building", log="/sw/BUILD/ROOT-latest/log")
      with open(path) as f:
        status = json.load(f)
      self.assertEqual((status["state"], status["package"], status["log"]),
                       ("building", "ROOT", "/sw/BUILD/ROOT-latest/log"))
      self.assertIn("updated", status)
      # A status that cannot be written must not stop the build.
      buildstatus.update(environ={"ALIBUILD_STATUS_FILE": join(tmp, "no", "such", "dir")}, state="x")


if __name__ == '__main__':
  unittest.main()
