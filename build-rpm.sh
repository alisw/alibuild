#!/bin/bash
set -e

VERSION=${1:?Usage: $0 <version>}
SPEC=alibuild.spec

BUILDDIR=$(mktemp -d)
trap 'rm -rf "$BUILDDIR"' EXIT

echo "Downloading alibuild ${VERSION} wheel from PyPI..."

# Download wheel to SOURCES
mkdir -p "$BUILDDIR/SOURCES"
pip download --no-deps --only-binary=:all: --dest "$BUILDDIR/SOURCES" "alibuild==${VERSION}"

# Build RPM
rpmbuild -ba "${SPEC}" \
    --define "version ${VERSION}" \
    --define "_topdir ${BUILDDIR}"

# Copy RPMs to current directory
cp "$BUILDDIR/RPMS"/*/*.rpm "$BUILDDIR/SRPMS"/*.rpm .
echo "Done. RPMs copied to current directory."
