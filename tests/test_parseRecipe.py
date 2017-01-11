import unittest
import platform
from alibuild_helpers.utilities import parseRecipe, getRecipeReader, parseDefaults
from alibuild_helpers.utilities import FileReader, GitReader
from alibuild_helpers.utilities import validateDefaults, SpecError

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

ERROR_MSG_3 ="""Unable to parse test_broken_3.sh
while parsing a block mapping
expected <block end>, but found ':'
  in "<string>", line 2, column 6:
       - :
         ^"""

ERROR_MSG_4 = """Malformed header for test_broken_4.sh
Not a YAML key / value."""

ERROR_MSG_5 = """Malformed header for test_broken_5.sh
Missing package field in header."""

ERROR_MSG_6 = """Unable to parse test_broken_6.sh
while scanning a quoted scalar
  in "<string>", line 1, column 6:
    tag: "foo
         ^
found unexpected end of stream
  in "<string>", line 2, column 1:
    
    ^"""

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
    return self.buffer

class TestRecipes(unittest.TestCase):
  def test_recipes(self):
    err, meta, body = parseRecipe(BufferReader("test1.sh", TEST1))
    assert(err == None)
    assert(meta["package"] == "foo")
    assert(meta["version"] == "bar")
    err, meta, body = parseRecipe(BufferReader("test_broken_1.sh", TEST_BROKEN_1))
    assert(err == "Unable to parse test_broken_1.sh. Header missing.")
    err, meta, body = parseRecipe(BufferReader("test_broken_2.sh", TEST_BROKEN_2))
    assert(err == "Malformed header for test_broken_2.sh\nEmpty recipe.")
    assert(not meta and not body)
    err, meta, body = parseRecipe(BufferReader("test_broken_3.sh", TEST_BROKEN_3))
    assert(err == ERROR_MSG_3)
    assert(meta == None)
    assert(body.strip() == "")
    err, meta, body = parseRecipe(BufferReader("test_broken_4.sh", TEST_BROKEN_4))
    assert(err == ERROR_MSG_4)
    err, meta, body = parseRecipe(BufferReader("test_broken_5.sh", TEST_BROKEN_5))
    assert(err == ERROR_MSG_5)
    err, meta, body = parseRecipe(BufferReader("test_broken_6.sh", TEST_BROKEN_6))
    assert(err.strip() == ERROR_MSG_6.strip())

  def test_getRecipeReader(self):
    f = getRecipeReader("foo")
    assert(type(f) == FileReader)
    f = getRecipeReader("dist:foo@master")
    assert(type(f) == FileReader)
    f = getRecipeReader("dist:foo@master", "alidist")
    assert(type(f) == GitReader)

  def test_parseDefaults(self):
    disable = ["bar"]
    err, overrides, taps = parseDefaults(disable,
                                        lambda : ({"disable": "foo",
                                                   "overrides": {"ROOT@master": {"requires": "GCC"}}}, ""),
                                        Recoder())
    assert(disable == ["bar", "foo"])
    assert(overrides == {'root': {'requires': 'GCC'}})
    assert(taps == {'root': 'dist:ROOT@master'})
    print err, overrides, taps
    print disable

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

