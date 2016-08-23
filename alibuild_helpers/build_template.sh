#!/bin/bash

# Automatically generated build script

set -e
set +h
export WORK_DIR="${WORK_DIR_OVERRIDE:-%(workDir)s}"

# From our dependencies
%(dependencies)s

# The following environment variables are setup by
# the aliBuild script itself
#
# - ARCHITECTURE
# - BUILD_REQUIRES
# - CACHED_TARBALL
# - CAN_DELETE
# - COMMIT_HASH
# - DEPS_HASH
# - DEVEL_HASH
# - DEVEL_PREFIX
# - GIT_TAG
# - INCREMENTAL_BUILD_HASH
# - JOBS
# - PKGHASH
# - PKGNAME
# - PKGREVISION
# - PKGVERSION
# - REQUIRES
# - RUNTIME_REQUIRES
# - WRITE_REPO

export PKG_NAME="$PKGNAME"
export PKG_VERSION="$PKGVERSION"
export PKG_BUILDNUM="$PKGREVISION"

export SOURCE0="${SOURCE0_DIR_OVERRIDE:-%(sourceDir)s}%(sourceName)s"
export PKGPATH=${ARCHITECTURE}/${PKGNAME}/${PKGVERSION}-${PKGREVISION}
mkdir -p "$WORK_DIR/BUILD" "$WORK_DIR/SOURCES" "$WORK_DIR/TARS" \
         "$WORK_DIR/SPECS" "$WORK_DIR/INSTALLROOT"
export BUILDROOT="$WORK_DIR/BUILD/$PKGHASH"

# In case the repository is local, it means we are in development mode, so we
# install directly in $WORK_DIR/$PKGPATH so that we can do make install
# directly into BUILD/$PKGPATH and have changes being propagated.
if [ "${SOURCE0:0:1}" == "/" ]; then
  export INSTALLROOT="$WORK_DIR/$PKGPATH"
else
  export INSTALLROOT="$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
fi
export SOURCEDIR="$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/$COMMIT_HASH"
export BUILDDIR="$BUILDROOT/$PKGNAME"

SHORT_TAG=${GIT_TAG:0:10}
mkdir -p $(dirname $SOURCEDIR)
if [[ ${COMMIT_HASH} != ${GIT_TAG} && "${SHORT_TAG:-0}" != ${COMMIT_HASH} ]]; then
  GIT_TAG_DIR=${GIT_TAG:-0}
  GIT_TAG_DIR=${GIT_TAG_DIR//\//_}
  ln -snf ${COMMIT_HASH} "$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/${GIT_TAG_DIR}"
fi
rm -fr "$WORK_DIR/INSTALLROOT/$PKGHASH"
# We remove the build directory only if we are not in incremental mode.
if [[ "$INCREMENTAL_BUILD_HASH" == 0 ]]; then
  rm -rf "$BUILDROOT"
fi
mkdir -p "$INSTALLROOT" "$BUILDROOT" "$BUILDDIR" "$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
cd "$BUILDROOT"
ln -snf $PKGHASH $WORK_DIR/BUILD/$PKGNAME-latest
if [[ $DEVEL_PREFIX ]]; then
  ln -snf $PKGHASH $WORK_DIR/BUILD/$PKGNAME-latest-$DEVEL_PREFIX
fi

# Reference statements
%(referenceStatement)s

if [[ ! "$SOURCE0" == '' && "${SOURCE0:0:1}" != "/" && ! -d "$SOURCEDIR" ]]; then
  # In case there is a stale link / file, for whatever reason.
  rm -rf $SOURCEDIR
  git clone ${GIT_REFERENCE:+--reference $GIT_REFERENCE} "$SOURCE0" "$SOURCEDIR"
  cd $SOURCEDIR
  git checkout "${GIT_TAG}"
  git remote set-url --push origin $WRITE_REPO
elif [[ ! "$SOURCE0" == '' && "${SOURCE0:0:1}" == "/" ]]; then
  ln -snf $SOURCE0 $SOURCEDIR
fi

mkdir -p "$SOURCEDIR"
cd "$BUILDDIR"

# Actual build script, as defined in the recipe

# This actually does the build, taking in to account shortcuts like
# having a pre build tarball or having an incremental recipe (in the
# case of development mode).
#
# - If the build was never done and we do not have a cached tarball,
#   build everything as usual.
# - If the build was started, we do not have a tarball, and we
#   have a non trivial incremental recipe, use it to continue the build.
# - If the build was started, but we do not have a incremental build recipe,
#   simply rebuild as usual.
# - In case we have a cached tarball, we skip the build and expand it, change
#   the relocation script so that it takes into account the new location.
if [[ "$CACHED_TARBALL" == "" && ! -f $BUILDROOT/log ]]; then
  set -o pipefail
  bash -ex "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.sh" 2>&1 | tee "$BUILDROOT/log"
elif [[ "$CACHED_TARBALL" == "" && $INCREMENTAL_BUILD_HASH != "0" && -f "$BUILDDIR/.build_succeeded" ]]; then
  set -o pipefail
  (%(incremental_recipe)s) 2>&1 | tee -a "$BUILDROOT/log"
elif [[ "$CACHED_TARBALL" == "" ]]; then
  set -o pipefail
  bash -ex "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.sh" 2>&1 | tee "$BUILDROOT/log"
else
  # Unpack the cached tarball in the $INSTALLROOT and remove the unrelocated
  # files.
  rm -rf "$BUILDROOT/log"
  mkdir -p $WORK_DIR/TMP/$PKGHASH
  $MY_GZIP -dc $CACHED_TARBALL | tar -C $WORK_DIR/TMP/$PKGHASH -x
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
export ${BIGPKGNAME}_COMMIT=${COMMIT_HASH}
EOF

# Environment
%(environment)s

cd "$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
# Find which files need relocation.
{ grep -I -H -l -R "\(INSTALLROOT/$PKGHASH\|[@][@]PKGREVISION[@]$PKGHASH[@][@]\)" . || true; } | sed -e 's|^\./||' > "$INSTALLROOT/.original-unrelocated"

# Relocate script for <arch>/<pkgname>/<pkgver> structure
cat > "$INSTALLROOT/relocate-me.sh" <<EoF
#!/bin/bash -e
if [[ "\$WORK_DIR" == '' ]]; then
  echo 'Please, define \$WORK_DIR'
  exit 1
fi
OP=${PKGPATH}
PP=\${PKGPATH:-${PKGPATH}}
PH=${PKGHASH}
EoF

cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} echo "sed -e \"s|/[^ ]*INSTALLROOT/\$PH/\$OP|\$WORK_DIR/\$PP|g;s|[@][@]PKGREVISION[@]\$PH[@][@]|$PKGREVISION|g\" \$PP/{}.unrelocated > \$PP/{}" >> "$INSTALLROOT/relocate-me.sh"
# Always relocate the modulefile (if present) so that it works also in devel mode.
if [[ ! -s "$INSTALLROOT/.original-unrelocated" && -f "$INSTALLROOT/etc/modulefiles/$PKGNAME" ]]; then
  echo "mv -f \$PP/etc/modulefiles/$PKGNAME \$PP/etc/modulefiles/${PKGNAME}.forced-relocation && sed -e \"s|[@][@]PKGREVISION[@]\$PH[@][@]|$PKGREVISION|g\" \$PP/etc/modulefiles/${PKGNAME}.forced-relocation > \$PP/etc/modulefiles/$PKGNAME" >> "$INSTALLROOT/relocate-me.sh"
fi
cat "$INSTALLROOT/relocate-me.sh"
cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} cp '{}' '{}'.unrelocated
cd "$WORK_DIR/INSTALLROOT/$PKGHASH"

# Archive creation
HASHPREFIX=`echo $PKGHASH | cut -b1,2`
HASH_PATH=$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH
mkdir -p "${WORK_DIR}/TARS/$HASH_PATH" \
         "${WORK_DIR}/TARS/$ARCHITECTURE/$PKGNAME"

PACKAGE_WITH_REV=$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz
# Avoid having broken left overs if the tar fails
tar -C $WORK_DIR/INSTALLROOT/$PKGHASH -c -z -f "$WORK_DIR/TARS/$HASH_PATH/${PACKAGE_WITH_REV}.processing" .
mv $WORK_DIR/TARS/$HASH_PATH/${PACKAGE_WITH_REV}.processing $WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV

ln -nfs \
  "../../$HASH_PATH/$PACKAGE_WITH_REV" \
  "$WORK_DIR/TARS/$ARCHITECTURE/$PKGNAME/$PACKAGE_WITH_REV"

# Unpack, and relocate
cd "$WORK_DIR"
tar xzf "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV"
[ "X$CAN_DELETE" = X1 ] && rm "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV"
bash -ex "$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/relocate-me.sh"
# Last package built gets a "latest" mark.
ln -snf $PKGVERSION-$PKGREVISION $ARCHITECTURE/$PKGNAME/latest

# Latest package built for a given devel prefix gets latest-$BUILD_FAMILY
if [[ $BUILD_FAMILY ]]; then
  ln -snf $PKGVERSION-$PKGREVISION $ARCHITECTURE/$PKGNAME/latest-$BUILD_FAMILY
fi

# Mark the build as successful with a placeholder. Allows running incremental
# recipe in case the package is in development mode.
echo "${DEVEL_HASH}${DEPS_HASH}" > "$BUILDDIR/.build_succeeded"
