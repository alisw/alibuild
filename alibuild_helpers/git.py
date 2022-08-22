try:
  from shlex import quote  # Python 3.3+
except ImportError:
  from pipes import quote  # Python 2.7
from alibuild_helpers.cmd import getstatusoutput
from alibuild_helpers.log import debug


def clone_speedup_options():
  """Return a list of options supported by the system git which speed up cloning."""
  _, out = getstatusoutput("LANG=C git clone --filter=blob:none")
  if "unknown option" not in out and "invalid filter-spec" not in out:
    return ["--filter=blob:none"]
  return []


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
  """.format(directory=quote(directory),
             args=" ".join(map(quote, args)),
             # GIT_TERMINAL_PROMPT is only supported in git 2.3+.
             prompt_var="GIT_TERMINAL_PROMPT=0" if not prompt else ""))
  if check and err != 0:
    raise RuntimeError("Error {} from git {}: {}".format(err, " ".join(args), output))
  return output if check else (err, output)
