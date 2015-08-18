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
export PKGPATH=${ARCHITECTURE}/${PKGNAME}/${PKGVERSION}-${PKGREVISION}
mkdir -p "$WORK_DIR/BUILD" "$WORK_DIR/SOURCES" "$WORK_DIR/TARS" \
         "$WORK_DIR/LEGACY" "$WORK_DIR/SPECS" "$WORK_DIR/BUILDROOT" \
         "$WORK_DIR/INSTALLROOT"
export BUILDROOT="$WORK_DIR/BUILD/$PKGHASH"
export INSTALLROOT="$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
export SOURCEDIR="$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/%(commit_hash)s"
export BUILDDIR="$BUILDROOT/$PKGNAME"

SHORT_TAG=${GIT_TAG:0:10}
if [[ %(commit_hash)s != ${GIT_TAG} && "${SHORT_TAG:-0}" != %(commit_hash)s ]]; then
  GIT_TAG_DIR=${GIT_TAG:-0}
  GIT_TAG_DIR=${GIT_TAG_DIR//\//_}
  mkdir -p "$(dirname $WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/${GIT_TAG_DIR})"
  ln -snf %(commit_hash)s "$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/${GIT_TAG_DIR}"
fi
rm -fr "$WORK_DIR/INSTALLROOT/$PKGHASH" "$BUILDROOT"
mkdir -p "$INSTALLROOT" "$BUILDROOT" "$BUILDDIR"
cd "$BUILDROOT"
rm -rf "$BUILDROOT/log"

# Reference statements
%(referenceStatement)s

if [[ ! "$SOURCE0" == '' && ! -d "$SOURCEDIR" ]]; then
  # In case there is a stale link / file, for whatever reason.
  rm -rf $SOURCEDIR
  git clone ${GIT_REFERENCE:+--reference $GIT_REFERENCE} "$SOURCE0" "$SOURCEDIR"
  cd $SOURCEDIR
  git checkout "${GIT_TAG}"
  git remote set-url --push origin %(write_repo)s
fi

mkdir -p "$SOURCEDIR"
cd "$BUILDDIR"

# Actual build script, as defined in the recipe
CACHED_TARBALL=%(cachedTarball)s

# In case we have a cached tarball, we skip the build and expand it, change the
# relocation script so that it takes into account the new location.
if [ X$CACHED_TARBALL = X ]; then
  set -o pipefail
  bash -ex "$WORK_DIR/SPECS/$PKGNAME.sh" 2>&1 | tee "$BUILDROOT/log"
else
  # Unpack the cached tarball in the $INSTALLROOT and remove the unrelocated
  # files.
  mkdir -p $WORK_DIR/TMP/$PKGHASH
  %(gzip)s -dc $CACHED_TARBALL | tar -C $WORK_DIR/TMP/$PKGHASH -x
  mkdir -p $(dirname $INSTALLROOT)
  rm -rf $INSTALLROOT
  mv $WORK_DIR/TMP/$PKGHASH/$ARCHITECTURE/$PKGNAME/$PKGVERSION-* $INSTALLROOT
  pushd $WORK_DIR/INSTALLROOT/$PKGHASH
    WORK_DIR=$WORK_DIR/INSTALLROOT/$PKGHASH bash -ex $INSTALLROOT/relocate-me.sh
  popd
  find $INSTALLROOT -name "*.unrelocated" -delete 
  rm -rf $WORK_DIR/TMP/$PKGHASH
fi

cd "$WORK_DIR/INSTALLROOT/$PKGHASH"
echo "$PKGHASH" > "$INSTALLROOT/.build-hash"
mkdir -p "$INSTALLROOT/etc/profile.d"
BIGPKGNAME=`echo "$PKGNAME" | tr [:lower:] [:upper:] | tr - _`
rm -f "$INSTALLROOT/etc/profile.d/init.sh"

# Init our dependencies
%(dependenciesInit)s

cat << EOF >> $INSTALLROOT/etc/profile.d/init.sh
export ${BIGPKGNAME}_ROOT=$INSTALLROOT
export ${BIGPKGNAME}_VERSION=$PKGVERSION
export ${BIGPKGNAME}_REVISION=$PKGREVISION
export ${BIGPKGNAME}_HASH=$PKGHASH
export ${BIGPKGNAME}_COMMIT=%(commit_hash)s
EOF

# Environment
%(environment)s

cd "$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
grep -I -H -l -R "INSTALLROOT/$PKGHASH" . | sed -e 's|^\./||' > "$INSTALLROOT/.original-unrelocated"

# Relocate script for <arch>/<pkgname>/<pkgver> structure
cat > "$INSTALLROOT/relocate-me.sh" <<EoF
#!/bin/bash -e
if [[ "\$WORK_DIR" == '' ]]; then
  echo 'Please, define \$WORK_DIR'
  exit 1
fi
ORIGINAL_PKGPATH=${PKGPATH}
PKGPATH=\${PKGPATH:-${PKGPATH}}
EoF

cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} echo "sed -e \"s|/[^ ]*INSTALLROOT/$PKGHASH/\$ORIGINAL_PKGPATH|\$WORK_DIR/\$PKGPATH|g\" \$PKGPATH/{}.unrelocated > \$PKGPATH/{}" >> "$INSTALLROOT/relocate-me.sh"
cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} cp '{}' '{}'.unrelocated
cd "$WORK_DIR/INSTALLROOT/$PKGHASH"

# Relocate script wrt/software root (compatible w/legacy behavior)
(
cat <<\EoF
#!/bin/bash -e
cd "$(dirname "$0")"
NEW_PREFIX=${NEW_PREFIX:-$PWD}
EoF
cat "$INSTALLROOT/.original-unrelocated" | sed -e 's|^\([^/]\+/\+\)\{3\}||g' | \
  xargs -n1 -I{} \
  echo "sed -e \"s|/[^ ]*INSTALLROOT/${PKGHASH}/${PKGPATH}|\$NEW_PREFIX|g\" {}.unrelocated > {}"
) > "$INSTALLROOT/relocate-me-root.sh"

# Archive creation
HASHPREFIX=`echo $PKGHASH | cut -b1,2`
HASH_PATH=$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH
mkdir -p "${WORK_DIR}/TARS/$HASH_PATH" \
         "${WORK_DIR}/LEGACY/$HASH_PATH" \
         "${WORK_DIR}/TARS/$ARCHITECTURE/$PKGNAME" \
         "${WORK_DIR}/LEGACY/$ARCHITECTURE/$PKGNAME"

PACKAGE_WITH_REV=$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz
LEGACY_WITH_REV=$PKGNAME_$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz
tar -C $WORK_DIR/INSTALLROOT/$PKGHASH -c -z -f "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV" .
tar -C $INSTALLROOT/.. -c -z -f "$WORK_DIR/LEGACY/$HASH_PATH/$PACKAGE_WITH_REV" $PKGVERSION-$PKGREVISION

ln -nfs \
  "../../$HASH_PATH/$PACKAGE_WITH_REV" \
  "$WORK_DIR/TARS/$ARCHITECTURE/$PKGNAME/$PACKAGE_WITH_REV"

ln -nfs \
  "../../$HASH_PATH/$PACKAGE_WITH_REV" \
  "$WORK_DIR/LEGACY/$ARCHITECTURE/$PKGNAME/$LEGACY_WITH_REV"

# Unpack, and relocate
cd "$WORK_DIR"
tar xzf "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV"
bash -ex "$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/relocate-me.sh"
