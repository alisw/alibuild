This is a list of a few design choices of aliBuild with the rationale for it.

# git is the only "native" backend for sources

The `source:` key in the recipes takes a git repository URL as only kind of source. This is because it was considered
that the overhead for maintaining multiple backends was not worth the candle. In the Github age, if you need something which is
not on git you can simply create your own repository and import a tarball.
