# This file is needed to package build_template.sh.

# Single-source a PEP440-compliant version using setuptools_scm.
try:
    # This is an sdist or wheel, and it's properly installed.
    from alibuild_helpers._version import version as __version__
except ImportError:
    # We're probably running directly from a source checkout.
    try:
        from setuptools_scm import get_version
    except ImportError:
        __version__ = None
    else:
        import os.path
        source_root = os.path.join(os.path.dirname(__file__), os.path.pardir)
        try:
            __version__ = get_version(root=source_root)
        except LookupError:
            __version__ = None
        finally:
            del get_version, source_root
