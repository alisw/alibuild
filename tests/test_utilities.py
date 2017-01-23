import unittest
import platform
from alibuild_helpers.utilities import doDetectArch
from alibuild_helpers.utilities import Hasher
from alibuild_helpers.utilities import format
from alibuild_helpers.utilities import asList

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
  ['slc5_x86-64', False, [], ('redhat', '5.XX', 'Boron'), 'Linux', 'x86-64'],
  ['slc6_x86-64', False, [], ('centos', '6.X', 'Carbon'), 'Linux', 'x86-64'],
  ['slc7_x86-64', False, [], ('centos', '7.X', 'Ptor'), 'Linux', 'x86-64'],
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

class TestUtilities(unittest.TestCase):
  def test_osx(self):
    for payload in architecturePayloads:
      result, hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor = payload
      self.assertEqual(result, doDetectArch(hasOsRelease, osReleaseLines, platformTuple, platformSystem, platformProcessor))
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

  def test_format(self):
    self.assertEqual(format("%(foo)s", foo="foo"), "foo")
    self.assertEqual(format(b"%(foo)s", foo="foo"), "foo")
    self.assertRaises(KeyError, format, "%(foo)s", bar="foo")

  def test_asList(self):
    self.assertEqual(asList("a"), ["a"])
    self.assertEqual(asList(["a"]), ["a"])
    self.assertEqual(asList(None), [None])

if __name__ == '__main__':
    unittest.main()

