import unittest
import platform
from alibuild_helpers.utilities import parseRecipe, getRecipeReader, parseDefaults
from alibuild_helpers.utilities import FileReader, GitReader
from alibuild_helpers.utilities import validateDefaults, SpecError, readDefaults
try:
    from unittest.mock import patch, call, MagicMock  # In Python 3, mock is built-in
    from io import StringIO
except ImportError:
    from mock import patch, call, MagicMock  # Python 2
    from StringIO import StringIO
try:
  from collections import OrderedDict
except ImportError:
  from ordereddict import OrderedDict

TEST1="""package: foo
version: bar
---
"""

TEST_BROKEN_1 = "broken"
TEST_BROKEN_2 = "---"
TEST_BROKEN_3 = """gfooo:
   - :
---
"""
TEST_BROKEN_4 = """broken
---
"""

TEST_BROKEN_5 = """tag: foo
---
"""

TEST_BROKEN_6 = """tag: "foo
---
"""

ERROR_MSG_3 = """Unable to parse test_broken_3.sh
while parsing a block mapping
expected <block end>, but found ':'
  in "<unicode string>", line 2, column 6:
       - :
         ^"""

ERROR_MSG_4 = """Malformed header for test_broken_4.sh
Not a YAML key / value."""

ERROR_MSG_5 = """Malformed header for test_broken_5.sh
Missing package field in header."""

ERROR_MSG_6 = """Unable to parse test_broken_6.sh
while scanning a quoted scalar
  in "<unicode string>", line 1, column 6:
    tag: "foo
         ^
found unexpected end of stream
  in "<unicode string>", line 2, column 1:
    
    ^"""

TEST_OVERRIDE_1 = """package: defaults-release
version: v1
---
"""
TEST_OVERRIDE_2 = """package: defaults-override2
version: v1
disable:
  - dis2
overrides:
  dummy:
    version: vOverride2
---
"""
TEST_OVERRIDE_3 = """package: defaults-override3
version: v1
disable:
  - dis3
overrides:
  dummy:
    version: vOverride3
---
"""

class Recoder(object):
  def __init__(self):
    self.buffer = ""
  def __call__(self, s):
    self.buffer += s

class BufferReader(object):
  def __init__(self, filename, recipe):
    self.url = filename
    self.buffer = recipe
  def __call__(self):
    if type(self.buffer) == bytes:
      return self.buffer.decode()
    else:
      return self.buffer

class TestRecipes(unittest.TestCase):
  def test_recipes(self):
    err, meta, body = parseRecipe(BufferReader("test1.sh", TEST1))
    self.assertEqual(err, None)
    self.assertEqual(meta["package"], "foo")
    self.assertEqual(meta["version"],  "bar")
    err, meta, body = parseRecipe(BufferReader("test_broken_1.sh", TEST_BROKEN_1))
    self.assertEqual(err,  "Unable to parse test_broken_1.sh. Header missing.")
    err, meta, body = parseRecipe(BufferReader("test_broken_2.sh", TEST_BROKEN_2))
    self.assertEqual(err, "Malformed header for test_broken_2.sh\nEmpty recipe.")
    self.assertTrue(not meta and not body)
    err, meta, body = parseRecipe(BufferReader("test_broken_3.sh", TEST_BROKEN_3))
    self.assertEqual(err.encode("ascii"), ERROR_MSG_3.encode("ascii"))
    self.assertEqual(meta, None)
    self.assertEqual(body.strip(), "")
    err, meta, body = parseRecipe(BufferReader("test_broken_4.sh", TEST_BROKEN_4))
    self.assertEqual(err, ERROR_MSG_4)
    err, meta, body = parseRecipe(BufferReader("test_broken_5.sh", TEST_BROKEN_5))
    self.assertEqual(err, ERROR_MSG_5)
    err, meta, body = parseRecipe(BufferReader("test_broken_6.sh", TEST_BROKEN_6))
    self.assertEqual(err.strip(), ERROR_MSG_6.strip())

  def test_getRecipeReader(self):
    f = getRecipeReader("foo")
    self.assertEqual(type(f), FileReader)
    f = getRecipeReader("dist:foo@master")
    self.assertEqual(type(f), FileReader)
    f = getRecipeReader("dist:foo@master", "alidist")
    self.assertEqual(type(f), GitReader)

  @patch("alibuild_helpers.utilities.exists")
  @patch("alibuild_helpers.utilities.open")
  def test_readDefaults(self, mock_open, mock_exists):
    mock_exists.side_effect = lambda x: True
    mock_open.side_effect = lambda x: { "/dist/defaults-release.sh"  : StringIO(TEST_OVERRIDE_1),
                                        "/dist/defaults-override2.sh": StringIO(TEST_OVERRIDE_2),
                                        "/dist/defaults-override3.sh": StringIO(TEST_OVERRIDE_3) }[x]
    meta,body = readDefaults("/dist", ["release", "override2", "override3"], lambda x: None)
    self.assertEqual(meta["overrides"]["dummy"]["version"], "vOverride3")
    self.assertEqual(meta["disable"], ["dis3"])
    meta,body = readDefaults("/dist", ["release", "override3", "override2"], lambda x: None)
    self.assertEqual(meta["overrides"]["dummy"]["version"], "vOverride2")
    self.assertEqual(meta["disable"], ["dis2"])

  def test_parseDefaults(self):
    disable = ["bar"]
    err, overrides, taps = parseDefaults(disable,
                                        lambda: ({ "disable": "foo",
                                                   "overrides": OrderedDict({"ROOT@master": {"requires": "GCC"}})},
                                                 ""),
                                        Recoder())
    self.assertEqual(disable, ["bar", "foo"])
    self.assertEqual(overrides, {'defaults-release': {}, 'root': {'requires': 'GCC'}})
    self.assertEqual(taps, {'root': 'dist:ROOT@master'})

  def test_validateDefault(self):
    ok, valid = validateDefaults({"something": True}, "release")
    self.assertEqual(ok, True)
    ok, valid = validateDefaults({"package": "foo","valid_defaults": ["o2", "o2-daq"]}, "release")
    self.assertEqual(ok, False)
    self.assertEqual(valid, 'Cannot compile foo with `release\' default. Valid defaults are\n - o2\n - o2-daq')
    ok, valid = validateDefaults({"package": "foo","valid_defaults": ["o2", "o2-daq"]}, "o2")
    self.assertEqual(ok, True)
    ok, valid = validateDefaults({"package": "foo","valid_defaults": "o2-daq"}, "o2")
    self.assertEqual(ok, False)
    ok, valid = validateDefaults({"package": "foo","valid_defaults": "o2"}, "o2")
    self.assertEqual(ok, True)
    ok, valid = validateDefaults({"package": "foo","valid_defaults": 1}, "o2")
    self.assertEqual(ok, False)
    self.assertEqual(valid, 'valid_defaults needs to be a string or a list of strings. Found [1].')
    ok, valid = validateDefaults({"package": "foo", "valid_defaults": {}}, "o2")
    self.assertEqual(ok, False)
    self.assertEqual(valid, 'valid_defaults needs to be a string or a list of strings. Found [{}].')

if __name__ == '__main__':
    unittest.main()

