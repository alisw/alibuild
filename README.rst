.. image:: https://badge.fury.io/py/alibuild.svg
.. image:: https://github.com/alisw/alibuild/actions/workflows/pr-check.yml/badge.svg?branch=master&event=push

aliBuild
========

A simple build tool for ALICE experiment software and its externals. Recipes
for the externals and ALICE software are stored in
`alidist <https://github.com/alisw/alidist>`_.

Instant gratification with::

    pip install alibuild
    aliBuild init
    aliBuild build AliRoot
    alienv enter AliRoot/latest
    aliroot -b

Full documentation at:

https://alisw.github.io/alibuild

Pre-requisites
==============

If you are using aliBuild directly from git clone, you should make sure
you have the dependencies installed. The easiest way to do this is to run::

    pip install -e .


For developers
==============

If you want to contribute to aliBuild, you can run the tests with::

    pip install -e .[test] # Only needed once
    tox

The test suite only runs fully on a Linux system, but there is a reduced suite for macOS, runnable with::

    tox -e darwin

You can also run only the unit tests (it's a lot faster than the full suite) with::

    pytest

To run the documentation locally, you can use::

    pip install -e .[docs]
    cd docs
    mkdocs serve
