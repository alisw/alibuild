#!/bin/bash
set -e

VERSION=${1:?Usage: $0 <version>}
SPEC=alibuild.spec

BUILDDIR=$(mktemp -d)
trap 'rm -rf "$BUILDDIR"' EXIT

echo "Building alibuild ${VERSION} wheel from current directory..."

# Build wheel to SOURCES
mkdir -p "$BUILDDIR/SOURCES"
SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" pip wheel --no-deps --wheel-dir "$BUILDDIR/SOURCES" .

# Build RPM
rpmbuild -ba "${SPEC}" \
    --define "version ${VERSION}" \
    --define "_topdir ${BUILDDIR}"

# Copy RPMs to current directory
cp "$BUILDDIR/RPMS"/*/*.rpm "$BUILDDIR/SRPMS"/*.rpm .
echo "Done. RPMs copied to current directory."
