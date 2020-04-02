.. image:: https://github.com/alisw/alibuild/workflows/Python%20package/badge.svg

aliBuild
========

A simple build tool for ALICE experiment software and its externals. Recipes
for the externals and ALICE software are stored in
`alidist <https://github.com/alisw/alidist>`_.

Instant gratification with::

    pip install alibuild
    git clone https://github.com/alisw/alidist.git
    aliBuild build AliRoot
    alienv enter AliRoot/latest
    aliroot -b

Full documentation at:

https://alisw.github.io/alibuild

Pre-requisites
==============

If you are using aliBuild directly from git clone, you should make sure
you have `pyyaml` and `argparse` in your python distribution.
