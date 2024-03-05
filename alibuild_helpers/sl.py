from shlex import quote  # Python 3.3+
from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.log import debug
from alibuild_helpers.scm import SCM, SCMError

SL_COMMAND_TIMEOUT_SEC = 120
"""How many seconds to let any sl command execute before being terminated."""


# Sapling is a novel SCM by Meta (i.e. Facebook) that is fully compatible with
# git, but has a different command line interface. Among the reasons why it's
# worth suporting it is the ability to handle unnamed branches, the ability to
# absorb changes to the correct commit without having to explicitly rebase and
# the integration with github to allow for pull requests to be created from the
# command line from each commit of a branch.
class Sapling(SCM):
  name = "Sapling"

  def checkedOutCommitName(self, directory):
    return sapling(("whereami", ), directory)

  def branchOrRef(self, directory):
    # Format is <hash>[+] <branch>
    identity = sapling(("identify", ), directory)
    return identity.split(" ")[-1]

  def exec(self, *args, **kwargs):
    return sapling(*args, **kwargs)

  def parseRefs(self, output):
    return {
      sl_ref: sl_hash for sl_ref, sep, sl_hash
      in (line.partition("\t") for line in output.splitlines()) if sep
    }

  def listRefsCmd(self, repository):
    return ["bookmark", "--list", "--remote", "-R", repository]

  def diffCmd(self, directory):
    return "cd %s && sl diff && sl status" % directory

  def checkUntracked(self, line):
    return line.startswith("? ")


def sapling(args, directory=".", check=True, prompt=True):
  debug("Executing sl %s (in directory %s)", " ".join(args), directory)
  # We can't use git --git-dir=%s/.git or git -C %s here as the former requires
  # that the directory we're inspecting to be the root of a git directory, not
  # just contained in one (and that breaks CI tests), and the latter isn't
  # supported by the git version we have on slc6.
  # Silence cd as shell configuration can cause the new directory to be echoed.
  err, output = getstatusoutput("""\
  set -e +x
  sl -R {directory} {args}
  """.format(
    directory=quote(directory),
    args=" ".join(map(quote, args)),
  ), timeout=SL_COMMAND_TIMEOUT_SEC)
  if check and err != 0:
    raise SCMError("Error {} from sl {}: {}".format(err, " ".join(args), output))
  return output if check else (err, output)
