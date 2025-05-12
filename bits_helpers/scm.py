class SCMError(Exception):
  """Signal that an SCM-related error occurred."""


class SCM(object):
  def checkedOutCommitName(self, directory):
    raise NotImplementedError
  def branchOrRef(self, directory):
    raise NotImplementedError
  def lsRemote(self, remote):
    raise NotImplementedError
  def listRefsCmd(self, repository):
    raise NotImplementedError
  def parseRefs(self, output):
    raise NotImplementedError
  def exec(self, *args, **kwargs):
    raise NotImplementedError
  def checkoutCmd(self, tag):
    raise NotImplementedError
  def fetchCmd(self, remote, *refs):
    raise NotImplementedError
  def cloneReferenceCmd(self, spec, referenceRepo, usePartialClone):
    raise NotImplementedError
  def cloneSourceCmd(self, source, destination, referenceRepo, usePartialClone):
    raise NotImplementedError
  def setWriteUrlCmd(self, url):
    raise NotImplementedError
  def diffCmd(self, directory):
    raise NotImplementedError
  def checkUntracked(self, line):
    raise NotImplementedError
