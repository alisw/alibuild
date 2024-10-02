# vim: set fileencoding=utf-8 :

import unittest

# Assuming you are using the mock library to ... mock things
from unittest.mock import patch

from alibuild_helpers.utilities import doDetectArch, filterByArchitecture
from alibuild_helpers.utilities import Hasher
from alibuild_helpers.utilities import asList
from alibuild_helpers.utilities import prunePaths
from alibuild_helpers.utilities import resolve_version
from alibuild_helpers.utilities import topological_sort
import os
import string

UBUNTU_1510_OS_RELEASE = """
NAME="Ubuntu"
VERSION="15.10 (Wily Werewolf)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 15.10"
VERSION_ID="15.10"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
"""

LINUX_MINT_OS_RELEASE = """
NAME="Ubuntu"
VERSION="14.04.4 LTS, Trusty Tahr"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 14.04.4 LTS"
VERSION_ID="14.04"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
"""

UBUNTU_1404_OS_RELEASE = """
NAME="Ubuntu"
VERSION="14.04.3 LTS, Trusty Tahr"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 14.04.3 LTS"
VERSION_ID="14.04"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
"""

UBUNTU_1604_OS_RELEASE = """
NAME="Ubuntu"
VERSION="16.04 LTS (Xenial Xerus)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 16.04 LTS"
VERSION_ID="16.04"
HOME_URL="http://www.ubuntu.com/"
SUPPORT_URL="http://help.ubuntu.com/"
BUG_REPORT_URL="http://bugs.launchpad.net/ubuntu/"
UBUNTU_CODENAME=xenial
"""

UBUNTU_1804_OS_RELEASE = """
NAME="Ubuntu"
VERSION="18.04.4 LTS (Bionic Beaver)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 18.04.4 LTS"
VERSION_ID="18.04"
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
VERSION_CODENAME=bionic
UBUNTU_CODENAME=bionic
"""

DEBIAN_7_OS_RELEASE = """
PRETTY_NAME="Debian GNU/Linux 7 (wheezy)"
NAME="Debian GNU/Linux"
VERSION_ID="7"
VERSION="7 (wheezy)"
ID=debian
ANSI_COLOR="1;31"
HOME_URL="http://www.debian.org/"
SUPPORT_URL="http://www.debian.org/support/"
BUG_REPORT_URL="http://bugs.debian.org/"
"""

DEBIAN_8_OS_RELEASE = """
PRETTY_NAME="Debian GNU/Linux 8 (jessie)"
NAME="Debian GNU/Linux"
VERSION_ID="8"
VERSION="8 (jessie)"
ID=debian
HOME_URL="http://www.debian.org/"
SUPPORT_URL="http://www.debian.org/support"
BUG_REPORT_URL="https://bugs.debian.org/"
"""

SABAYON2_OS_RELEASE = """
NAME=Sabayon
ID=sabayon
PRETTY_NAME="Sabayon/Linux"
ANSI_COLOR="1;32"
HOME_URL="http://www.sabayon.org/"
SUPPORT_URL="http://forum.sabayon.org/"
BUG_REPORT_URL="https://bugs.sabayon.org/"
"""

architecturePayloads = [
  ['osx_x86-64', False, [], ('','',''), 'Darwin', 'x86-64'],
  ['osx_arm64', False, [], ('','',''), 'Darwin', 'arm64'],
  ['slc5_x86-64', False, [], ('redhat', '5.XX', 'Boron'), 'Linux', 'x86-64'],
  ['slc6_x86-64', False, [], ('centos', '6.X', 'Carbon'), 'Linux', 'x86-64'],
  ['slc7_x86-64', False, [], ('centos', '7.X', 'Ptor'), 'Linux', 'x86-64'],
  ['ubuntu1804_x86-64', True, UBUNTU_1804_OS_RELEASE.split("\n"), ('Ubuntu', '18.04', 'bionic'), 'Linux', 'x86-64'],
  ['ubuntu1604_x86-64', True, UBUNTU_1604_OS_RELEASE.split("\n"), ('Ubuntu', '16.04', 'xenial'), 'Linux', 'x86-64'],
  ['ubuntu1510_x86-64', False, [], ('Ubuntu', '15.10', 'wily'), 'Linux', 'x86-64'],
  ['ubuntu1510_x86-64', True, UBUNTU_1510_OS_RELEASE.split("\n"), ('Ubuntu', '15.10', 'wily'), 'Linux', 'x86-64'],
  ['ubuntu1510_x86-64', True, UBUNTU_1510_OS_RELEASE.split("\n"), ('', '', ''), 'Linux', 'x86-64'], # ANACONDA case
  ['ubuntu1404_x86-64', True, UBUNTU_1404_OS_RELEASE.split("\n"), ('Ubuntu', '14.04', 'trusty'), 'Linux', 'x86-64'],
  ['ubuntu1404_x86-64', True, UBUNTU_1404_OS_RELEASE.split("\n"), ('', '', ''), 'Linux', 'x86-64'],
  ['ubuntu1404_x86-64', True, LINUX_MINT_OS_RELEASE.split("\n"), ('LinuxMint', '17.3', 'rosa'), 'Linux', 'x86-64'], # LinuxMint
  ['ubuntu1204_x86-64', True, DEBIAN_7_OS_RELEASE.split("\n"), ('Debian', '7', 'wheezy'), 'Linux', 'x86-64'],
  ['ubuntu1404_x86-64', True, DEBIAN_8_OS_RELEASE.split("\n"), ('Debian', '8', 'jessie'), 'Linux', 'x86-64'],
  ['sabayon2_x86-64', True, SABAYON2_OS_RELEASE.split("\n"), ('gentoo', '2.2', ''), 'Linux', 'x86_64']
]

macOSArchitecturePayloads = [
  ['osx_x86-64', False, [], ('','',''), 'Darwin', 'x86_64'],
  ['osx_arm64', False, [], ('','',''), 'Darwin', 'arm64'],
]

class TestUtilities(unittest.TestCase):
  def test_osx(self):
    for payload in architecturePayloads:
      result, hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor = payload
      self.assertEqual(result, doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor))
  # Test by mocking platform.processor
  def test_osx_mock(self):
    for payload in macOSArchitecturePayloads:
      result, hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor = payload
      with patch('platform.machine', return_value=platformProcessor):
        platformProcessor = None
        self.assertEqual(result, doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, None))
  def test_Hasher(self):
    h = Hasher()
    h("foo")
    self.assertEqual("0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33", h.hexdigest())
    h("")
    self.assertEqual("0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33", h.hexdigest())
    self.assertRaises(AttributeError, h, 1)
    h("bar")
    self.assertEqual("8843d7f92416211de9ebb963ff4ce28125932878", h.hexdigest())

  def test_UTF8_Hasher(self):
    h1 = Hasher()
    h2 = Hasher()
    h3 = Hasher()
    h1(u'\ua000')
    h2(u'\ua001')
    h3(b'foo')
    self.assertEqual(h1.hexdigest(), "2af8e41129115eb231a0af76ec5465d3a9184fc4")
    self.assertEqual(h2.hexdigest(), "1619bcdbeff6828138ad9b6e43cc17e856457603")
    self.assertEqual(h3.hexdigest(), "0beec7b5ea3f0fdbc95d0dd47f3c5bc275da8a33")
    self.assertNotEqual(h1.hexdigest(), h2.hexdigest())

  def test_asList(self):
    self.assertEqual(asList("a"), ["a"])
    self.assertEqual(asList(["a"]), ["a"])
    self.assertEqual(asList(None), [None])

  def test_filterByArchitecture(self):
    self.assertEqual(["AliRoot"], list(filterByArchitecture("osx_x86-64", ["AliRoot"])))
    self.assertEqual([], list(filterByArchitecture("osx_x86-64", ["AliRoot:(?!osx)"])))
    self.assertEqual(["GCC"], list(filterByArchitecture("osx_x86-64", ["AliRoot:(?!osx)", "GCC"])))
    self.assertEqual(["AliRoot", "GCC"], list(filterByArchitecture("osx_x86-64", ["AliRoot:(?!slc6)", "GCC"])))
    self.assertEqual(["GCC"], list(filterByArchitecture("osx_x86-64", ["AliRoot:slc6", "GCC:osx"])))
    self.assertEqual([], list(filterByArchitecture("osx_x86-64", [])))

  def test_prunePaths(self):
    fake_env = {
      "PATH": "/sw/bin:/usr/local/bin",
      "LD_LIBRARY_PATH": "/sw/lib",
      "DYLD_LIBRARY_PATH": "/sw/lib",
      "ALIBUILD_VERSION": "v1.0.0",
      "ROOT_VERSION": "v1.0.0"
    }
    fake_env_copy = {
      "PATH": "/sw/bin:/usr/local/bin",
      "LD_LIBRARY_PATH": "/sw/lib",
      "DYLD_LIBRARY_PATH": "/sw/lib",
      "ALIBUILD_VERSION": "v1.0.0",
      "ROOT_VERSION": "v1.0.0"
    }
    with patch.object(os, "environ", fake_env):
      prunePaths("/sw")
      self.assertTrue(not "ROOT_VERSION" in fake_env)
      self.assertTrue(fake_env["PATH"] == "/usr/local/bin")
      self.assertTrue(fake_env["LD_LIBRARY_PATH"] == "")
      self.assertTrue(fake_env["DYLD_LIBRARY_PATH"] == "")
      self.assertTrue(fake_env["ALIBUILD_VERSION"] == "v1.0.0")

    with patch.object(os, "environ", fake_env_copy):
      prunePaths("/foo")
      self.assertTrue(not "ROOT_VERSION" in fake_env_copy)
      self.assertTrue(fake_env_copy["PATH"] == "/sw/bin:/usr/local/bin")
      self.assertTrue(fake_env_copy["LD_LIBRARY_PATH"] == "/sw/lib")
      self.assertTrue(fake_env_copy["DYLD_LIBRARY_PATH"] == "/sw/lib")
      self.assertTrue(fake_env_copy["ALIBUILD_VERSION"] == "v1.0.0")

  def test_resolver(self):
    spec = {"package": "test-pkg",
      "version": "%(tag_basename)s",
      "tag": "foo/bar",
      "commit_hash": "000000000000000000000000000"
    }
    self.assertTrue(resolve_version(spec, "release", "stream/v1", "v1"), "bar")
    spec["version"] = "%(branch_stream)s"
    self.assertTrue(resolve_version(spec, "release", "stream/v1", "v1"), "v1")
    spec["version"] = "%(defaults_upper)s"
    self.assertTrue(resolve_version(spec, "o2", "stream/v1", "v1"), "O2")
    spec["version"] = "NO%(defaults_upper)s"
    self.assertTrue(resolve_version(spec, "release", "stream/v1", "v1"), "NO")


class TestTopologicalSort(unittest.TestCase):
    """Check that various properties of topological sorting hold."""

    def test_resolve_dependency_chain(self):
        """Test that topological sorting correctly sorts packages in a dependency chain."""
        # Topological sorting only takes "requires" into account, since the
        # build/runtime distinction does not matter for resolving build order.
        self.assertEqual(["c", "b", "a"], list(topological_sort({
            "a": {"package": "a", "requires": ["b"]},
            "b": {"package": "b", "requires": ["c"]},
            "c": {"package": "c", "requires": []},
        })))

    def test_diamond_dependency(self):
        """Test that a diamond dependency relationship is handled correctly."""
        self.assertEqual(["base", "mid2", "mid1", "top"], list(topological_sort({
            "top": {"package": "top", "requires": ["mid1", "mid2"]},
            # Add a mid1 -> mid2 cross-dependency to make the order deterministic.
            "mid1": {"package": "mid1", "requires": ["base", "mid2"]},
            "mid2": {"package": "mid2", "requires": ["base"]},
            "base": {"package": "base", "requires": []},
        })))

    def test_dont_drop_packages(self):
        """Check that topological sorting doesn't drop any packages."""
        # For half the packages, depend on the first package, to make this a
        # little more than trivial.
        specs = {pkg: {"package": pkg, "requires": [] if pkg < "m" else ["a"]}
                 for pkg in string.ascii_lowercase}
        self.assertEqual(frozenset(specs.keys()),
                         frozenset(topological_sort(specs)))


if __name__ == '__main__':
    unittest.main()
