import codecs
import os.path
import re
import unittest

from collections import OrderedDict

from alibuild_helpers.build import storeHashes

LOGFILE = "build.log"
SPEC_RE = re.compile(r"spec = (OrderedDict\(\[\('package', '([^']+)'.*\)\]\))")
HASH_RE = re.compile(r"Hashes for recipe (.*) are "
                     r"(([0-9a-f]{40})(?:, [0-9a-f]{40})*) \(remote\)[,;] "
                     r"(([0-9a-f]{40})(?:, [0-9a-f]{40})*) \(local\)")


class KnownGoodHashesTestCase(unittest.TestCase):
    """Make sure storeHashes produces the same hashes as in a build log.

    It is assumed that the hashes in the build log are correct, i.e. the ones
    we want to get for the matching spec in the log.

    It is possible to provide old-style logs (mentioning one local and remote
    hash only) or new-style logs (mentioning all alternative remote and local
    hashes). If providing old-style logs, only the hashing for the primary
    hashes is checked.
    """

    @unittest.skipIf(not os.path.exists(LOGFILE),
                     "Need a reference build log at path " + LOGFILE)
    def test_hashes_match_build_log(self):
        checked = set()
        specs = {}
        with codecs.open(LOGFILE, encoding="utf-8") as logf:
            for line in logf:
                match = re.search(SPEC_RE, line)
                if match:
                    spec_expr, package = match.groups()
                    specs[package] = eval(spec_expr, {"OrderedDict": OrderedDict})
                    specs[package]["is_devel_pkg"] = False
                    continue
                match = re.search(HASH_RE, line)
                if not match:
                    continue
                package, alt_remote, remote, alt_local, local = match.groups()
                if package in checked:
                    # Once a package is built, it will have a second "spec ="
                    # and "Hashes for recipe" line in the log. In that case, we
                    # don't want to check the hashes are correct, as
                    # storeHashes doesn't do anything in that case (the spec
                    # from the log will already have hashes stored).
                    continue
                storeHashes(package, specs, considerRelocation=False)
                spec = specs[package]
                self.assertEqual(spec["remote_revision_hash"], remote)
                self.assertEqual(spec["local_revision_hash"], local)
                # For logs produced by old hash implementations (which didn't
                # consider spec["scm_refs"]), alt_{remote,local} will only
                # contain the primary hash anyway, so this works nicely.
                self.assertEqual(spec["remote_hashes"], alt_remote.split(", "))
                self.assertEqual(spec["local_hashes"], alt_local.split(", "))
                checked.add(package)
                continue


if __name__ == '__main__':
    unittest.main()
