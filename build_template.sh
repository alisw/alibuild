#!/bin/bash

# Build script for %(pkgname)s -- automatically generated

set -e
export WORK_DIR="%(workDir)s"

# From our dependencies
%(dependencies)s

export CONFIG_DIR="%(configDir)s"
export PKGNAME="%(pkgname)s"
export PKGHASH="%(hash)s"
export PKGVERSION="%(version)s"
export PKGREVISION="%(revision)s"
export ARCHITECTURE="%(architecture)s"
export SOURCE0="%(source)s"
export GIT_TAG="%(tag)s"
export JOBS=${JOBS-%(jobs)s}
mkdir -p "$WORK_DIR/BUILD" "$WORK_DIR/SOURCES" "$WORK_DIR/TARS"  "$WORK_DIR/LEGACY" \
  "$WORK_DIR/SPECS" "$WORK_DIR/BUILDROOT" "$WORK_DIR/INSTALLROOT"
export BUILDROOT="$WORK_DIR/BUILD/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION"
export INSTALLROOT="$WORK_DIR/INSTALLROOT/$PKGHASH/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION"
export SOURCEDIR="$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/%(commit_hash)s"
SHORT_TAG=${GIT_TAG:0:10}
if [[ %(commit_hash)s != ${GIT_TAG} && "${SHORT_TAG:-0}" != %(commit_hash)s ]]; then
  mkdir -p "$(dirname $WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/${GIT_TAG:-0})"
  ln -snf %(commit_hash)s "$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/${GIT_TAG:-0}"
fi
rm -fr "$INSTALLROOT" "$BUILDROOT"
mkdir -p "$INSTALLROOT" "$BUILDROOT"
cd "$BUILDROOT"
rm -rf "$BUILDROOT/log"
export BUILDDIR="$BUILDROOT/$PKGNAME"

# Reference statements
%(referenceStatement)s

if [[ ! "$SOURCE0" == '' && ! -d "$SOURCEDIR" ]]; then
  # In case there is a stale link / file, for whatever reason.
  rm -fr $SOURCEDIR
  git clone ${GIT_REFERENCE:+--reference $GIT_REFERENCE} "$SOURCE0" "$SOURCEDIR"
  (cd $SOURCEDIR && git checkout "${GIT_TAG}" && git remote set-url --push origin %(write_repo)s)
fi

mkdir -p "$BUILDDIR" "$SOURCEDIR"
cd "$BUILDDIR"

# Actual build script, as defined in the recipe
set -o pipefail
bash -ex "$WORK_DIR/SPECS/$PKGNAME.sh" 2>&1 | tee "$BUILDROOT/log"

pushd "$WORK_DIR/INSTALLROOT/$PKGHASH"
echo "$PKGHASH" > "$INSTALLROOT/.build-hash"
mkdir -p "$INSTALLROOT/etc/profile.d"
BIGPKGNAME=`echo "$PKGNAME" | tr [:lower:] [:upper:] | tr - _`
rm -f "$INSTALLROOT/etc/profile.d/init.sh"

# Init our dependencies
%(dependenciesInit)s

echo "export ${BIGPKGNAME}_ROOT=$INSTALLROOT" >> $INSTALLROOT/etc/profile.d/init.sh
echo "export ${BIGPKGNAME}_VERSION=$PKGVERSION" >> $INSTALLROOT/etc/profile.d/init.sh
echo "export ${BIGPKGNAME}_REVISION=$PKGREVISION" >> $INSTALLROOT/etc/profile.d/init.sh
echo "export ${BIGPKGNAME}_HASH=$PKGHASH" >> $INSTALLROOT/etc/profile.d/init.sh
echo "export ${BIGPKGNAME}_COMMIT=%(commit_hash)s" >> $INSTALLROOT/etc/profile.d/init.sh

# Environment
%(environment)s

cd "$WORK_DIR/INSTALLROOT/$PKGHASH"
grep -I -H -l -R "INSTALLROOT/$PKGHASH" "$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION" > "$INSTALLROOT/.original-unrelocated"

# Relocate script for <arch>/<pkgname>/<pkgver> structure
cat > "$INSTALLROOT/relocate-me.sh" <<\EoF
#!/bin/bash -e
if [[ "$WORK_DIR" == '' ]]; then
  echo "Please, define \$WORK_DIR"
  exit 1
fi
EoF

cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} echo "sed -e \"s|/[^ ]*INSTALLROOT/$PKGHASH|\$WORK_DIR|g\" {}.unrelocated > {}" >> "$INSTALLROOT/relocate-me.sh"
cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} cp '{}' '{}'.unrelocated

# Relocate script wrt/software root (compatible w/legacy behavior)
(
cat <<\EoF
#!/bin/bash -e
cd "$(dirname "$0")"
NEW_PREFIX=${NEW_PREFIX:-$PWD}
EoF
cat "$INSTALLROOT/.original-unrelocated" | sed -e 's|^\([^/]\+/\+\)\{3\}||g' | \
  xargs -n1 -I{} \
  echo "sed -e \"s|/[^ ]*INSTALLROOT/${PKGHASH}/${ARCHITECTURE}/${PKGNAME}/${PKGVERSION}-${PKGREVISION}|\$NEW_PREFIX|g\" {}.unrelocated > {}"
) > "$INSTALLROOT/relocate-me-root.sh"

HASHPREFIX=`echo $PKGHASH | cut -b1,2`
mkdir -p "${WORK_DIR}/TARS/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH"
mkdir -p "${WORK_DIR}/LEGACY/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH"

# Archive creation
tar czf "$WORK_DIR/TARS/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz" .
(
  cd ${INSTALLROOT}/..
  tar czf "$WORK_DIR/LEGACY/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz" $PKGVERSION-$PKGREVISION
)

ln -nfs \
  "$WORK_DIR/TARS/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz" \
  "$WORK_DIR/TARS/$ARCHITECTURE/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz"

ln -nfs \
  "$WORK_DIR/LEGACY/$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz" \
  "$WORK_DIR/LEGACY/$ARCHITECTURE/${PKGNAME}_$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz"

# Unpack, and relocate
cd "$WORK_DIR"
tar xzf "$WORK_DIR/TARS/$ARCHITECTURE/$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz"
bash -ex "$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/relocate-me.sh"
