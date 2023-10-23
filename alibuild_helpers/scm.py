class SCM(object):
  def checkedOutCommitName(self, directory):
    raise NotImplementedError
  def branchOrRef(self, directory):
    raise NotImplementedError
  def lsRemote(self, remote):
    raise NotImplementedError
  def listRefsCmd(self):
    raise NotImplementedError
  def parseRefs(self, output):
    raise NotImplementedError
  def exec(self, *args, **kwargs):
    raise NotImplementedError
  def cloneCmd(self, spec, referenceRepo, usePartialClone):
    raise NotImplementedError
  def diffCmd(self, directory):
    raise NotImplementedError
  def checkUntracked(self, line):
    raise NotImplementedError
