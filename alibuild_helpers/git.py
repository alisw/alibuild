from shlex import quote
from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.log import debug
from alibuild_helpers.scm import SCM, SCMError

GIT_COMMAND_TIMEOUT_SEC = 120
"""How many seconds to let any git command execute before being terminated."""


def clone_speedup_options():
  """Return a list of options supported by the system git which speed up cloning."""
  for filter_option in ("--filter=tree:0", "--filter=blob:none"):
    _, out = getstatusoutput("LANG=C git clone " + filter_option)
    if "unknown option" not in out and "invalid filter-spec" not in out:
      return [filter_option]
  return []


class Git(SCM):
  name = "Git"

  def checkedOutCommitName(self, directory):
    return git(("rev-parse", "HEAD"), directory)

  def branchOrRef(self, directory):
    out = git(("rev-parse", "--abbrev-ref", "HEAD"), directory=directory)
    if out == "HEAD":
      out = git(("rev-parse", "HEAD"), directory)[:10]
    return out

  def exec(self, *args, **kwargs):
    return git(*args, **kwargs)

  def parseRefs(self, output):
    return {
      git_ref: git_hash for git_hash, sep, git_ref
      in (line.partition("\t") for line in output.splitlines()) if sep
    }

  def listRefsCmd(self, repository):
    return ["ls-remote", "--heads", "--tags", repository]

  def cloneReferenceCmd(self, source, referenceRepo, usePartialClone):
    cmd = ["clone", "--bare", source, referenceRepo]
    if usePartialClone:
      cmd.extend(clone_speedup_options())
    return cmd

  def cloneSourceCmd(self, source, destination, referenceRepo, usePartialClone):
    cmd = ["clone", "-n", source, destination]
    if referenceRepo:
      # If we're building inside a Docker container, we can't refer to the
      # mirror repo directly, since Git uses an absolute path. With
      # "--dissociate", we still copy the objects locally, but we don't refer
      # to them by path.
      cmd.extend(["--dissociate", "--reference", referenceRepo])
    if usePartialClone:
      cmd.extend(clone_speedup_options())
    return cmd

  def checkoutCmd(self, ref):
    return ["checkout", "-f", ref]

  def fetchCmd(self, source, *refs):
    return ["fetch", "-f", source, *refs]

  def setWriteUrlCmd(self, url):
    return ["remote", "set-url", "--push", "origin", url]

  def diffCmd(self, directory):
    return "cd %s && git diff -r HEAD && git status --porcelain" % directory

  def checkUntracked(self, line):
    return line.startswith("?? ")


def git(args, directory=".", check=True, prompt=True):
  debug("Executing git %s (in directory %s)", " ".join(args), directory)
  # We can't use git --git-dir=%s/.git or git -C %s here as the former requires
  # that the directory we're inspecting to be the root of a git directory, not
  # just contained in one (and that breaks CI tests), and the latter isn't
  # supported by the git version we have on slc6.
  # Silence cd as shell configuration can cause the new directory to be echoed.
  err, output = getstatusoutput("""\
  set -e +x
  cd {directory} >/dev/null 2>&1
  {prompt_var} git {args}
  """.format(
    directory=quote(directory),
    args=" ".join(map(quote, args)),
    # GIT_TERMINAL_PROMPT is only supported in git 2.3+.
    prompt_var="GIT_TERMINAL_PROMPT=0" if not prompt else "",
  ), timeout=GIT_COMMAND_TIMEOUT_SEC)
  if check and err != 0:
    raise SCMError("Error {} from git {}: {}".format(err, " ".join(args), output))
  return output if check else (err, output)
