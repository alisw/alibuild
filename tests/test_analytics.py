import unittest
from alibuild_helpers.analytics import decideAnalytics

def noAnalytics():
    return False

def yesAnalytics():
    return True

def notInvoked() -> None:
    assert(False)

class TestAnalytics(unittest.TestCase):
    def test_analytics(self) -> None:
        self.assertEqual(False,  decideAnalytics(hasDisableFile=False,
                                                 hasUuid=False,
                                                 isTty=False,
                                                 questionCallback=notInvoked))
        self.assertEqual(False, decideAnalytics(hasDisableFile=False,
                                                hasUuid=False,
                                                isTty=True,
                                                questionCallback=noAnalytics))
        self.assertEqual(True, decideAnalytics(hasDisableFile=False,
                                               hasUuid=False,
                                               isTty=True,
                                               questionCallback=yesAnalytics))
        self.assertEqual(True, decideAnalytics(hasDisableFile=False,
                                               hasUuid=True,
                                               isTty=False,
                                               questionCallback=notInvoked))
        self.assertEqual(True, decideAnalytics(hasDisableFile=False,
                                               hasUuid=True,
                                               isTty=True,
                                               questionCallback=yesAnalytics))
        self.assertEqual(False, decideAnalytics(hasDisableFile=True,
                                                hasUuid=False,
                                                isTty=True,
                                                questionCallback=yesAnalytics))


if __name__ == '__main__':
    unittest.main()
