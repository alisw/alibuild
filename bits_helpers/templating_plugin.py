"""A text templating plugin for aliBuild.

This plugin allows reusing specs like those that would be used during the
build, for instance to get the "real" version numbers for various packages.

We use Jinja2 as the templating language, read the user-provided template from
stdin and print the rendered output to stdout.
"""

import sys
from jinja2.sandbox import SandboxedEnvironment


def build_plugin(specs, args, build_order):
    """Read a user-provided template from stdin and render it."""
    print(SandboxedEnvironment(autoescape=False)
          .from_string(sys.stdin.read())
          .render(specs=specs, args=args, build_order=build_order))
