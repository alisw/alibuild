
bits
========

Bits is a tool to build, install and package large software stacks. It originates from the aliBuild tool, originally developed to simplify building and installing ALICE / ALFA software and attempts to make it more general and usable for other communities that share similar problems and have overlapping dependencies.

Instant gratification with::

 $ git clone git@github.com:bitsorg/bits.git; cd bits; export PATH=$PWD:$PATH; cd ..
 $ git clone git@github.com:bitsorg/alice.bits.git
 $ cd alice.bits

Review and customise bits.rc file (in particular, sw_dir location where all output will be stored)::

 $ cat bits.rc
 [bits]
 organisation=ALICE
 [ALICE]
 pkg_prefix=VO_ALICE
 sw_dir=../sw
 repo_dir=.
 search_path=bits,general,simulation,hepmc,analysis,ml

Then::

 $ bits build ROOT
 $ bits enter ROOT/latest
 $ root -b

Full documentation at:

Pre-requisites
==============

If you are using bits directly from git clone, you should make sure
you have `pyyaml` and `argparse` in your python distribution.
