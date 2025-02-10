import unittest
from alibuild_helpers.utilities import parseRecipe, getRecipeReader, parseDefaults
from alibuild_helpers.utilities import FileReader, GitReader
from alibuild_helpers.utilities import validateDefaults
from collections import OrderedDict

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

class Recoder(object):
  def __init__(self) -> None:
    self.buffer = ""
  def __call__(self, s, *a) -> None:
    self.buffer += s % a

class BufferReader(object):
  def __init__(self, filename, recipe) -> None:
    self.url = filename
    self.buffer = recipe
  def __call__(self):
    if type(self.buffer) == bytes:
      return self.buffer.decode()
    else:
      return self.buffer

class TestRecipes(unittest.TestCase):
  def test_recipes(self) -> None:
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

  def test_getRecipeReader(self) -> None:
    f = getRecipeReader("foo")
    self.assertEqual(type(f), FileReader)
    f = getRecipeReader("dist:foo@master")
    self.assertEqual(type(f), FileReader)
    f = getRecipeReader("dist:foo@master", "alidist")
    self.assertEqual(type(f), GitReader)

  def test_parseDefaults(self) -> None:
    disable = ["bar"]
    err, overrides, taps = parseDefaults(disable,
                                        lambda: ({ "disable": "foo",
                                                   "overrides": OrderedDict({"ROOT@master": {"requires": "GCC"}})},
                                                 ""),
                                        Recoder())
    self.assertEqual(disable, ["bar", "foo"])
    self.assertEqual(overrides, {'defaults-release': {}, 'root': {'requires': 'GCC'}})
    self.assertEqual(taps, {'root': 'dist:ROOT@master'})

  def test_validateDefault(self) -> None:
    ok, out, validDefaults = validateDefaults({"something": True}, "release")
    self.assertEqual(ok, True)
    ok, out, validDefaults = validateDefaults({"package": "foo","valid_defaults": ["o2", "o2-dataflow"]}, "release")
    self.assertEqual(ok, False)
    self.assertEqual(out, 'Cannot compile foo with `release\' default. Valid defaults are\n - o2\n - o2-dataflow')
    ok, out, validDefaults = validateDefaults({"package": "foo","valid_defaults": ["o2", "o2-dataflow"]}, "o2")
    self.assertEqual(ok, True)
    ok, out, validDefaults = validateDefaults({"package": "foo","valid_defaults": "o2-dataflow"}, "o2")
    self.assertEqual(ok, False)
    self.assertEqual(validDefaults, ["o2-dataflow"])
    ok, out, validDefaults = validateDefaults({"package": "foo","valid_defaults": "o2"}, "o2")
    self.assertEqual(ok, True)
    ok, out, validDefaults = validateDefaults({"package": "foo","valid_defaults": 1}, "o2")
    self.assertEqual(ok, False)
    self.assertEqual(out, 'valid_defaults needs to be a string or a list of strings. Found [1].')
    ok, out, validDefaults = validateDefaults({"package": "foo", "valid_defaults": {}}, "o2")
    self.assertEqual(ok, False)
    self.assertEqual(out, 'valid_defaults needs to be a string or a list of strings. Found [{}].')

if __name__ == '__main__':
    unittest.main()

