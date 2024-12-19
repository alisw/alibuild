
bits
========

Bits is a tool to build, install and package large software stacks. It originates from the aliBuild 
tool, originally developed to simplify building and installing ALICE / ALFA software and attempts to
 make it more general and usable for other communities that share similar problems and have overlapp
ing dependencies.

Instant gratification with::

    pip install bits
     or
    git clone git@github.com:bitsorg/bits.git; cd bits; export PATH=$PWD:$PATH; cd ..
    git clone git@github.com:bitsorg/general.bits.git
    bits init -c general 
    bits build ROOT
    bits enter ROOT/latest
    root -b

Full documentation at:

Pre-requisites
==============

If you are using bits directly from git clone, you should make sure
you have `pyyaml` and `argparse` in your python distribution.
