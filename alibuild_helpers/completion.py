"""Output shell completion scripts for aliBuild."""

import sys
from os.path import dirname, realpath, join


def doCompletion(args):
    """Print the completion script for the requested shell to stdout."""
    script = join(dirname(realpath(__file__)), "completions", args.shell + ".sh")
    with open(script) as f:
        print(f.read())
