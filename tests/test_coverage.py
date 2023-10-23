import unittest
from alibuild_helpers.utilities import check_coverage

class FooTest(unittest.TestCase):
    def test_foo(self):
        self.assertTrue(check_coverage())

