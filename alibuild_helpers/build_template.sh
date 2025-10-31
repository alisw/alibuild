#!/bin/bash
ALIBUILD_START_TIMESTAMP=$(date +%%s)
# Automatically generated build script
unset DYLD_LIBRARY_PATH
echo "aliBuild: start building $PKGNAME-$PKGVERSION-$PKGREVISION at $ALIBUILD_START_TIMESTAMP"

cleanup() {
  local exit_code=$?
  ALIBUILD_END_TIMESTAMP=$(date +%%s)
  ALIBUILD_DELTA_TIME=$(($ALIBUILD_END_TIMESTAMP - $ALIBUILD_START_TIMESTAMP))
  echo "aliBuild: done building $PKGNAME-$PKGVERSION-$PKGREVISION at $ALIBUILD_START_TIMESTAMP (${ALIBUILD_DELTA_TIME} s)"
  exit $exit_code
}

trap cleanup EXIT

# Cleanup variables which should not be exposed to user code
unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY

set -e
set +h
function hash() { true; }
export WORK_DIR="${WORK_DIR_OVERRIDE:-%(workDir)s}"
export ALIBUILD_CONFIG_DIR="${ALIBUILD_CONFIG_DIR_OVERRIDE:-%(configDir)s}"

# Insert our own wrapper scripts into $PATH, patched to use the system OpenSSL,
# instead of the one we build ourselves.
export PATH=$WORK_DIR/wrapper-scripts:$PATH

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
# - INCREMENTAL_BUILD_HASH
# - JOBS
# - PKGHASH
# - PKGNAME
# - PKGREVISION
# - PKGVERSION
# - REQUIRES
# - RUNTIME_REQUIRES

export PKG_NAME="$PKGNAME"
export PKG_VERSION="$PKGVERSION"
export PKG_BUILDNUM="$PKGREVISION"

export PKGPATH=${ARCHITECTURE}/${PKGNAME}/${PKGVERSION}-${PKGREVISION}
mkdir -p "$WORK_DIR/BUILD" "$WORK_DIR/SOURCES" "$WORK_DIR/TARS" \
         "$WORK_DIR/SPECS" "$WORK_DIR/INSTALLROOT"
# If we are in development mode, then install directly in $WORK_DIR/$PKGPATH,
# so that we can do "make install" directly into BUILD/$PKGPATH and have
# changes being propagated.
# Moreover, devel packages should always go in the official WORK_DIR
if [ -n "$DEVEL_HASH" ]; then
  export ALIBUILD_BUILD_WORK_DIR="${WORK_DIR}"
  export INSTALLROOT="$WORK_DIR/$PKGPATH"
else
  export INSTALLROOT="$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"
  export ALIBUILD_BUILD_WORK_DIR="${ALIBUILD_BUILD_WORK_DIR:-$WORK_DIR}"
fi

export BUILDROOT="$ALIBUILD_BUILD_WORK_DIR/BUILD/$PKGHASH"
export SOURCEDIR="$WORK_DIR/SOURCES/$PKGNAME/$PKGVERSION/$COMMIT_HASH"
export BUILDDIR="$BUILDROOT/$PKGNAME"

rm -fr "$WORK_DIR/INSTALLROOT/$PKGHASH"
# We remove the build directory only if we are not in incremental mode.
if [[ "$INCREMENTAL_BUILD_HASH" == 0 ]] && ! rm -rf "$BUILDROOT"; then
  # Golang installs stuff without write permissions for ourselves sometimes.
  # This makes the `rm -rf` above fail, so give ourselves write permission.
  chmod -R o+w "$BUILDROOT" || :
  rm -rf "$BUILDROOT"
fi
mkdir -p "$INSTALLROOT" "$BUILDROOT" "$BUILDDIR" "$WORK_DIR/INSTALLROOT/$PKGHASH/$PKGPATH"

cd "$WORK_DIR/INSTALLROOT/$PKGHASH"
cat > "$INSTALLROOT/.meta.json" <<\EOF
%(provenance)s
EOF

# Add "source" command for dependencies to init.sh.
# Install init.sh now, so that it is available for debugging in case the build fails.
mkdir -p "$INSTALLROOT/etc/profile.d"
rm -f "$INSTALLROOT/etc/profile.d/init.sh"
cat <<\EOF > "$INSTALLROOT/etc/profile.d/init.sh"
%(initdotsh_deps)s
EOF

# Apply dependency initialisation now, but skip setting the variables below until after the build.
. "$INSTALLROOT/etc/profile.d/init.sh"

# Add support for direnv https://github.com/direnv/direnv/
#
# This is beneficial for all the cases where the build step requires some
# environment to be properly setup in order to work. e.g. to support ninja or
# protoc.
cat << EOF > "$BUILDDIR/.envrc"
# Source the build environment which was used for this package
WORK_DIR=\${WORK_DIR:-$WORK_DIR} source "\${WORK_DIR:-$WORK_DIR}/${INSTALLROOT#$WORK_DIR/}/etc/profile.d/init.sh"
source_up
# On mac we build with the proper installation relative RPATH,
# so this is not actually used and it's actually harmful since
# startup time is reduced a lot by the extra overhead from the
# dynamic loader
unset DYLD_LIBRARY_PATH
EOF

cd "$BUILDROOT"
ln -snf "$PKGHASH" "$ALIBUILD_BUILD_WORK_DIR/BUILD/$PKGNAME-latest"
if [[ $DEVEL_PREFIX ]]; then
  ln -snf "$PKGHASH" "$ALIBUILD_BUILD_WORK_DIR/BUILD/$PKGNAME-latest-$DEVEL_PREFIX"
fi

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
  (set -x; unset DYLD_LIBRARY_PATH; source "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.sh" 2>&1) | tee "$BUILDROOT/log"
elif [[ "$CACHED_TARBALL" == "" && $INCREMENTAL_BUILD_HASH != "0" && -f "$BUILDDIR/.build_succeeded" ]]; then
  set -o pipefail
  (%(incremental_recipe)s) 2>&1 | tee "$BUILDROOT/log"
elif [[ "$CACHED_TARBALL" == "" ]]; then
  set -o pipefail
  (set -x; unset DYLD_LIBRARY_PATH; source "$WORK_DIR/SPECS/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/$PKGNAME.sh" 2>&1) | tee "$BUILDROOT/log"
else
  # Unpack the cached tarball in the $INSTALLROOT and remove the unrelocated
  # files.
  rm -rf "$BUILDROOT/log"
  mkdir -p $WORK_DIR/TMP/$PKGHASH
  tar -xzf "$CACHED_TARBALL" -C "$WORK_DIR/TMP/$PKGHASH"
  mkdir -p $(dirname $INSTALLROOT)
  rm -rf $INSTALLROOT
  mv $WORK_DIR/TMP/$PKGHASH/$ARCHITECTURE/$PKGNAME/$PKGVERSION-* $INSTALLROOT
  pushd $WORK_DIR/INSTALLROOT/$PKGHASH
    if [ -w "$INSTALLROOT" ]; then
      WORK_DIR=$WORK_DIR/INSTALLROOT/$PKGHASH bash -ex $INSTALLROOT/relocate-me.sh
    fi
  popd
  find $INSTALLROOT -name "*.unrelocated" -delete
  rm -rf $WORK_DIR/TMP/$PKGHASH
fi

# Regenerate init.sh, in case the package build clobbered it. This
# particularly happens in the AliEn-Runtime package, since it copies other
# packages into its installroot wholesale.
# Notice how we only do it if $INSTALLROOT is writeable. If it is
# not, we assume it points to a CVMFS store which should be left untouched.
if [ -w $INSTALLROOT ]; then
mkdir -p "$INSTALLROOT/etc/profile.d"
rm -f "$INSTALLROOT/etc/profile.d/init.sh"
cat <<\EOF > "$INSTALLROOT/etc/profile.d/init.sh"
%(initdotsh_full)s
EOF

cd "$WORK_DIR/INSTALLROOT/$PKGHASH"
# Replace the .envrc to point to the final installation directory.
cat << EOF > "$BUILDDIR/.envrc"
# Source the build environment which was used for this package
WORK_DIR=\${WORK_DIR:-$WORK_DIR} source ../../../$PKGPATH/etc/profile.d/init.sh
source_up
# On mac we build with the proper installation relative RPATH,
# so this is not actually used and it's actually harmful since
# startup time is reduced a lot by the extra overhead from the
# dynamic loader
unset DYLD_LIBRARY_PATH
EOF

cat > "$INSTALLROOT/.meta.json" <<\EOF
%(provenance)s
EOF

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

while read -r unrelocated; do
  echo "sed -e \"s|/[^ ;:]*INSTALLROOT/\$PH/\$OP|\$WORK_DIR/\$PP|g; s|[@][@]PKGREVISION[@]\$PH[@][@]|$PKGREVISION|g\"" \
       "\$PP/$unrelocated.unrelocated > \$PP/$unrelocated"
done < "$INSTALLROOT/.original-unrelocated" >> "$INSTALLROOT/relocate-me.sh"

# Always relocate the modulefile (if present) so that it works also in devel mode.
if [[ ! -s "$INSTALLROOT/.original-unrelocated" && -f "$INSTALLROOT/etc/modulefiles/$PKGNAME" ]]; then
  echo "mv -f \$PP/etc/modulefiles/$PKGNAME \$PP/etc/modulefiles/${PKGNAME}.forced-relocation && sed -e \"s|[@][@]PKGREVISION[@]\$PH[@][@]|$PKGREVISION|g\" \$PP/etc/modulefiles/${PKGNAME}.forced-relocation > \$PP/etc/modulefiles/$PKGNAME" >> "$INSTALLROOT/relocate-me.sh"
fi

# Find libraries and executables needing relocation on macOS
if [[ ${ARCHITECTURE:0:3} == "osx" ]]; then
  otool_arch=$(echo "${ARCHITECTURE#osx_}" | tr - _)  # otool knows x86_64, not x86-64

  /usr/bin/find ${RELOCATE_PATHS:-bin lib lib64} -type d \( -name '*.dist-info' -o -path '*/pytz/zoneinfo' \) -prune -false -o -type f \
                -not -name '*.py' -not -name '*.pyc' -not -name '*.pyi' -not -name '*.pxd' -not -name '*.inc' -not -name '*.js' -not -name '*.json' \
                -not -name '*.xml' -not -name '*.xsl' -not -name '*.txt' -not -name '*.dat' -not -name '*.mat' -not -name '*.sav' -not -name '*.csv' \
                -not -name '*.wav' -not -name '*.png' -not -name '*.svg' -not -name '*.css' -not -name '*.html' -not -name '*.woff' -not -name '*.woff2' -not -name '*.ttf' \
                -not -name LICENSE -not -name COPYING -not -name '*.c' -not -name '*.cc' -not -name '*.cxx' -not -name '*.cpp' -not -name '*.h' -not -name '*.hpp' |
    while read -r BIN; do
      MACHOTYPE=$(set +o pipefail; otool -arch "$otool_arch" -h "$PWD/$BIN" 2> /dev/null | grep filetype -A1 | awk 'END{print $5}')

      # See mach-o/loader.h from XNU sources: 2 == executable, 6 == dylib, 8 == bundle
      if [[ $MACHOTYPE == 6 || $MACHOTYPE == 8 ]]; then
        # Only dylibs: relocate LC_ID_DYLIB
        if otool -arch "$otool_arch" -D "$PWD/$BIN" 2> /dev/null | tail -n1 | grep -q "$PKGHASH"; then
          cat <<EOF >> "$INSTALLROOT/relocate-me.sh"
install_name_tool -id "\$(otool -arch $otool_arch -D "\$PP/$BIN" | tail -n1 | sed -e "s|/[^ ]*INSTALLROOT/\$PH/\$OP|\$WORK_DIR/\$PP|g")" "\$PP/$BIN"
EOF
        elif otool -arch "$otool_arch" -D "$PWD/$BIN" 2> /dev/null | tail -n1 | grep -vq /; then
          cat <<EOF >> "$INSTALLROOT/relocate-me.sh"
install_name_tool -id "\$WORK_DIR/\$PP/$BIN" "\$PP/$BIN"
EOF
        fi
      fi

      if [[ $MACHOTYPE == 2 || $MACHOTYPE == 6 || $MACHOTYPE == 8 ]]; then
        # Both libs and binaries: relocate LC_RPATH
        if otool -arch "$otool_arch" -l "$PWD/$BIN" 2> /dev/null | grep -A2 LC_RPATH | grep path | grep -q "$PKGHASH"; then
          cat <<EOF >> "$INSTALLROOT/relocate-me.sh"
OLD_RPATHS=\$(otool -arch $otool_arch -l "\$PP/$BIN" | grep -A2 LC_RPATH | grep path | grep "\$PH" | sed -e 's|^.*path ||' -e 's| .*$||' | sort -u)
for OLD_RPATH in \$OLD_RPATHS; do
  NEW_RPATH=\${OLD_RPATH/#*INSTALLROOT\/\$PH\/\$OP/\$WORK_DIR/\$PP}
  install_name_tool -rpath "\$OLD_RPATH" "\$NEW_RPATH" "\$PP/$BIN"
done
EOF
        fi

        # Both libs and binaries: relocate LC_LOAD_DYLIB
        if otool -arch "$otool_arch" -l "$PWD/$BIN" 2> /dev/null | grep -A2 LC_LOAD_DYLIB | grep name | grep -q $PKGHASH; then
          cat <<EOF >> "$INSTALLROOT/relocate-me.sh"
OLD_LOAD_DYLIBS=\$(otool -arch $otool_arch -l "\$PP/$BIN" | grep -A2 LC_LOAD_DYLIB | grep name | grep "\$PH" | sed -e 's|^.*name ||' -e 's| .*$||' | sort -u)
for OLD_LOAD_DYLIB in \$OLD_LOAD_DYLIBS; do
  NEW_LOAD_DYLIB=\${OLD_LOAD_DYLIB/#*INSTALLROOT\/\$PH\/\$OP/\$WORK_DIR/\$PP}
  install_name_tool -change "\$OLD_LOAD_DYLIB" "\$NEW_LOAD_DYLIB" "\$PP/$BIN"
done
EOF
        fi
      fi
    done || true
fi

cat "$INSTALLROOT/relocate-me.sh"
cat "$INSTALLROOT/.original-unrelocated" | xargs -n1 -I{} cp '{}' '{}'.unrelocated
fi
cd "$WORK_DIR/INSTALLROOT/$PKGHASH"

# Archive creation
HASHPREFIX=`echo $PKGHASH | cut -b1,2`
HASH_PATH=$ARCHITECTURE/store/$HASHPREFIX/$PKGHASH
mkdir -p "${WORK_DIR}/TARS/$HASH_PATH" \
         "${WORK_DIR}/TARS/$ARCHITECTURE/$PKGNAME"

PACKAGE_WITH_REV=$PKGNAME-$PKGVERSION-$PKGREVISION.$ARCHITECTURE.tar.gz
# Copy and tar/compress (if applicable) in parallel.
# Use -H to match tar's behaviour of preserving hardlinks.
rsync -aH "$WORK_DIR/INSTALLROOT/$PKGHASH/" "$WORK_DIR" & rsync_pid=$!
if [ "$CAN_DELETE" = 1 ]; then
  # We're deleting the tarball anyway, so no point in creating a new one.
  # There might be an old existing tarball, and we should delete it.
  rm -f "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV"
elif [ -z "$CACHED_TARBALL" ]; then
  # Use pigz to compress, if we can, because it's multicore.
  gzip=$(command -v pigz) || gzip=$(command -v gzip)
  # We don't have an existing tarball, and we want to keep the one we create now.
  tar -cC "$WORK_DIR/INSTALLROOT/$PKGHASH" . |
    # Avoid having broken left overs if the tar fails.
    $gzip -c > "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV.processing"
  mv "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV.processing" \
     "$WORK_DIR/TARS/$HASH_PATH/$PACKAGE_WITH_REV"
  ln -nfs "../../$HASH_PATH/$PACKAGE_WITH_REV" \
     "$WORK_DIR/TARS/$ARCHITECTURE/$PKGNAME/$PACKAGE_WITH_REV"
fi
wait "$rsync_pid"

# We've copied files into their final place; now relocate.
cd "$WORK_DIR"
if [ -w "$WORK_DIR/$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION" ]; then
  bash -ex "$ARCHITECTURE/$PKGNAME/$PKGVERSION-$PKGREVISION/relocate-me.sh"
fi
# Last package built gets a "latest" mark.
ln -snf $PKGVERSION-$PKGREVISION $ARCHITECTURE/$PKGNAME/latest

# Latest package built for a given devel prefix gets latest-$BUILD_FAMILY
if [[ $BUILD_FAMILY ]]; then
  ln -snf $PKGVERSION-$PKGREVISION $ARCHITECTURE/$PKGNAME/latest-$BUILD_FAMILY
fi

# When the package is definitely fully installed, install the file that marks
# the package as successful.
if [ -w "$WORK_DIR/$PKGPATH" ]; then
  echo "$PKGHASH" > "$WORK_DIR/$PKGPATH/.build-hash"
fi
# Mark the build as successful with a placeholder. Allows running incremental
# recipe in case the package is in development mode.
echo "${DEVEL_HASH}${DEPS_HASH}" > "$BUILDDIR/.build_succeeded"
