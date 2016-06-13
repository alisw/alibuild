# Dummy file to package build_template.sh
import sys

# absolute import compatibility check
if sys.version_info < (3, 0):
    import utilities
    import analytics
    import log
else:
    from . import utilities
    from . import analytics
    from . import log

# remove non-project imports from this module
del sys
