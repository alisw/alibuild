{stdenv, pkgs, systemDeps}:
let
   properUnpack = ''
      runHook preUnpack;
      echo "foo"
      env
      runHook postUnpack;
   '';
   filterGit = what: pkgs.lib.cleanSourceWith { src=what; filter=path: type: !( (builtins.match ".git" path) != null || (builtins.match ".cache" path) != null); };

  Rivet = stdenv.mkDerivation {
    name = "Rivet";
    version = "rivet-4.1.0";
    
    
    src=(builtins.fetchGit {
    rev="b87b5437518cb3d5dd4a3426a77e9ac98fb02ce5";
    url="https://gitlab.com/hepcedar/rivet.git";});

    
    
    
    buildInputs = [
      Python
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      HepMC3
      YODA
      fastjet
      cgal
      GMP
      Python
      Python-modules
      Python
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Rivet
      PKGVERSION=rivet-4.1.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export HEPMC3_ROOT=${ HepMC3.out }
      HEPMC3_VERSION=${ HepMC3.version }
      HEPMC3_REVISION=1
      
      export YODA_ROOT=${ YODA.out }
      YODA_VERSION=${ YODA.version }
      YODA_REVISION=1
      
      export FASTJET_ROOT=${ fastjet.out }
      FASTJET_VERSION=${ fastjet.version }
      FASTJET_REVISION=1
      
      export CGAL_ROOT=${ cgal.out }
      CGAL_VERSION=${ cgal.version }
      CGAL_REVISION=1
      
      export GMP_ROOT=${ GMP.out }
      GMP_VERSION=${ GMP.version }
      GMP_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export PYTHON_MODULES_ROOT=${ Python-modules.out }
      PYTHON_MODULES_VERSION=${ Python-modules.version }
      PYTHON_MODULES_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      #
      # For testing 
      #
      #   aliBuild  -a slc7_x86-64 --docker-image registry.cern.ch/alisw/slc7-builder:latest. Rivet
      #
      rsync -a --chmod=ugo=rwX --delete --exclude '**/.git' --delete-excluded "$SOURCEDIR"/ ./
       
      autoreconf -ivf

      case $ARCHITECTURE in
          osx*)
              export HDF5_ROOT=''${HDF5_ROOT:-$(brew --prefix hdf5)}
              ;;
          *)
            EXTRA_LDFLAGS="-Wl,--no-as-needed"
          ;;
      esac

      ./configure --prefix="$INSTALLROOT"                             \
                  --disable-silent-rules                              \
                  --disable-doxygen                                   \
                  --with-yoda="$YODA_ROOT"                            \
                  --with-hepmc3="$HEPMC3_ROOT"                        \
                  --with-fastjet="$FASTJET_ROOT"                      \
                  LDFLAGS="''${CGAL_ROOT:+-L''${CGAL_ROOT}/lib} ''${GMP_ROOT:+-L''${GMP_ROOT}/lib} ''${HDF5_ROOT:+-L''${HDF5_ROOT}/lib} ''${EXTRA_LDFLAGS}" \
                  CPPFLAGS="''${CGAL_ROOT:+-I''${CGAL_ROOT}/include} ''${GMP_ROOT:+-I''${GMP_ROOT}/include} ''${HDF5_ROOT:+-I''${HDF5_ROOT}/include}" \
                  CYTHON="$PYTHON_MODULES_ROOT/bin/cython"

      # Remove -L/usr/lib from pyext/build.py 
      sed -i.bak -e 's,-L/usr/lib[^ /"]*,,g' pyext/build.py
      # Now build 
      make ''${JOBS+-j $JOBS}
      make install

      # Remove libRivet.la
      rm -f "$INSTALLROOT"/lib/libRivet.la

      # Create line to source 3rdparty.sh to be inserted into 
      # rivet-config and rivet-build 
      cat << EOF > source3rd
      source $INSTALLROOT/etc/profile.d/init.sh
      EOF

      # Make back-up of original for debugging - disable execute bit
      cp "$INSTALLROOT"/bin/rivet-config "$INSTALLROOT"/bin/rivet-config.orig
      chmod 644 "$INSTALLROOT"/bin/rivet-config.orig
      # Modify rivet-config script to use environment from rivet_3rdparty.sh
      sed -e "$SED_EXPR" "$INSTALLROOT"/bin/rivet-config > "$INSTALLROOT"/bin/rivet-config.0
      csplit "$INSTALLROOT"/bin/rivet-config.0 '/^datarootdir=/+1'
      cat xx00 source3rd xx01 >  "$INSTALLROOT"/bin/rivet-config
      chmod 0755 "$INSTALLROOT"/bin/rivet-config

      # Make back-up of original for debugging - disable execute bit
      cp "$INSTALLROOT"/bin/rivet-build "$INSTALLROOT"/bin/rivet-build.orig
      chmod 644 "$INSTALLROOT"/bin/rivet-build.orig
      # Modify rivet-build script to use environment from rivet_3rdparty.sh.  
      sed -e  "$SED_EXPR" "$INSTALLROOT"/bin/rivet-build > "$INSTALLROOT"/bin/rivet-build.0
      csplit "$INSTALLROOT"/bin/rivet-build.0 '/^datarootdir=/+1'
      cat xx00 source3rd xx01 >  "$INSTALLROOT"/bin/rivet-build
      chmod 0755 "$INSTALLROOT"/bin/rivet-build

      # Make symlink in library dir for Python
      PYVER="$(basename "$(find "$INSTALLROOT"/lib -type d -name 'python*')")"

      pushd "$INSTALLROOT"/lib || exit 1
      ln -s "''${PYVER}" python
      popd || exit 1

      
      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > $MODULEFILE
      cat >> "$MODULEFILE" <<EoF
      setenv RIVET_ROOT \$RIVET_ROOT
      setenv RIVET_ANALYSIS_PATH \$RIVET_ROOT/lib/Rivet
      setenv RIVET_DATA_PATH \$RIVET_ROOT/share/Rivet
      prepend-path PYTHONPATH \$RIVET_ROOT/lib/$PYVER/site-packages
      prepend-path PYTHONPATH \$RIVET_ROOT/lib64/$PYVER/site-packages

      # Producing plots with (/rivet/bin/make-plots, in python) requires dedicated LaTeX packages
      # which are not always there on the system (alidock, lxplus ...)
      # -> need to point to such packages, actually shipped together with Rivet sources
      # Consider the official source info in /rivet/rivetenv.sh to see what is needed
      # (TEXMFHOME, HOMETEXMF, TEXMFCNF, TEXINPUTS, LATEXINPUTS)
      # Here trying to keep the env variable changes to their minimum, i.e touch only TEXINPUTS, LATEXINPUTS
      # Manual prepend-path for TEX variables
      # catch option to fix compatibility issues with multiple systems
      if { [catch {exec kpsewhich -var-value TEXINPUTS} brokenTEX] } {
          set Old_TEXINPUTS \$brokenTEX
      } else {
          set Old_TEXINPUTS [ exec sh -c "kpsewhich -var-value TEXINPUTS" ]
      }

      set Extra_RivetTEXINPUTS \$RIVET_ROOT/share/Rivet/texmf/tex//
      setenv TEXINPUTS  \$Old_TEXINPUTS:\$Extra_RivetTEXINPUTS
      setenv LATEXINPUTS \$Old_TEXINPUTS:\$Extra_RivetTEXINPUTS
      EoF
      runHook postInstall
    '';
  };

  HepMC3 = stdenv.mkDerivation {
    name = "HepMC3";
    version = "3.3.0";
    
    
    src=(builtins.fetchGit {
    rev="78ddbe15146b7521daaef679208a7eeece85a36a";
    url="https://gitlab.cern.ch/hepmc/HepMC3.git";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=HepMC3
      PKGVERSION=3.3.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      cmake  $SOURCEDIR                          \
             -DROOT_DIR=$ROOT_ROOT               \
             -DCMAKE_INSTALL_PREFIX=$INSTALLROOT \
             -DCMAKE_INSTALL_LIBDIR=lib          \
             -DHEPMC3_ENABLE_PYTHON=OFF

      make ''${JOBS+-j $JOBS}
      make install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${GCC_TOOLCHAIN_ROOT:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION} ''${ROOT_REVISION:+ROOT/$ROOT_VERSION-$ROOT_REVISION}
      # Our environment
      set HEPMC3_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv HEPMC3_ROOT \$HEPMC3_ROOT
      prepend-path PATH \$HEPMC3_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$HEPMC3_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$HEPMC3_ROOT/include
      EoF
      runHook postInstall
    '';
  };

  YODA = stdenv.mkDerivation {
    name = "YODA";
    version = "yoda-2.1.0";
    
    
    src=(builtins.fetchGit {
    rev="a8a0db3adbb725ce70f6e21f0d2c2c2dcc2e044c";
    url="https://gitlab.com/hepcedar/yoda.git";});

    
    
    
    buildInputs = [
      HepMC3
      Python
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python
      Python-modules
      ROOT
      hdf5
      HepMC3
      Python
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=YODA
      PKGVERSION=yoda-2.1.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export HEPMC3_ROOT=${ HepMC3.out }
      HEPMC3_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export PYTHON_MODULES_ROOT=${ Python-modules.out }
      PYTHON_MODULES_VERSION=${ Python-modules.version }
      PYTHON_MODULES_REVISION=1
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export HDF5_ROOT=${ hdf5.out }
      HDF5_VERSION=${ hdf5.version }
      HDF5_REVISION=1
      
      export HEPMC3_ROOT=${ HepMC3.out }
      HEPMC3_VERSION=${ HepMC3.version }
      HEPMC3_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      rsync -a --exclude='**/.git' --delete --delete-excluded "$SOURCEDIR"/ ./

      [[ -e .missing_timestamps ]] && ./missing-timestamps.sh --apply || autoreconf -ivf

      export PYTHON=$(type -p python3)

      ./configure --disable-silent-rules --enable-root --prefix="$INSTALLROOT" --with-hdf5="$HDF5_ROOT"
      make ''${JOBS+-j $JOBS}
      make install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"

      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0					\\
                  ''${PYTHON_FULL_VERSION:+Python/$PYTHON_FULL_VERSION}	\\
                  ''${ROOT_REVISION:+ROOT/$ROOT_VERSION-$ROOT_REVISION}

      # Our environment
      set YODA_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
       
      prepend-path PATH \$YODA_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$YODA_ROOT/lib
      prepend-path LD_LIBRARY_PATH \$YODA_ROOT/lib64
      set pythonpath [exec \$YODA_ROOT/bin/yoda-config --pythonpath]
      prepend-path PYTHONPATH \$pythonpath
      prepend-path PYTHONPATH \$YODA_ROOT/lib/python/site-packages
      EoF
      runHook postInstall
    '';
  };

  fastjet = stdenv.mkDerivation {
    name = "fastjet";
    version = "v3.4.1_1.052-alice3";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/v3.4.1_1.052-alice3";
    url="https://github.com/alisw/fastjet";});

    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      cgal
      GMP
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=fastjet
      PKGVERSION=v3.4.1_1.052-alice3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CGAL_ROOT=${ cgal.out }
      CGAL_VERSION=${ cgal.version }
      CGAL_REVISION=1
      
      export GMP_ROOT=${ GMP.out }
      GMP_VERSION=${ GMP.version }
      GMP_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      case $ARCHITECTURE in
        osx*)
          # If we preferred system tools, we need to make sure we can pick them up.
          [[ ! $BOOST_ROOT ]] && BOOST_ROOT=`brew --prefix boost`
        ;;
      esac

      if [[ $GGAL_ROOT ]]; then
        export LIBRARY_PATH="''${BOOST_ROOT:+$BOOST_ROOT/lib:}$LIBRARY_PATH"
        BOOST_INC=''${BOOST_ROOT:+$BOOST_ROOT/include:}
        printf "void main() {}" | c++ -xc ''${BOOST_ROOT:+-L$BOOST_ROOT/lib} -lboost_thread - -o /dev/null 2>/dev/null  \
          && BOOST_LIBS="''${BOOST_ROOT+-L$BOOST_ROOT/lib} -lboost_thread"                                              \
          || BOOST_LIBS="''${BOOST_ROOT+-L$BOOST_ROOT/lib} -lboost_thread-mt"
        BOOST_LIBS="$BOOST_LIBS -lboost_system"
      fi

      rsync -a --delete --cvs-exclude --exclude .git $SOURCEDIR/ ./

      # FastJet
      pushd fastjet
        autoreconf -i -v -f
        [[ "''${ARCHITECTURE:0:3}" != osx ]] && ARCH_FLAGS='-Wl,--no-as-needed'
        FJTAG=''${GIT_TAG#alice-}
        if [[ $FJTAG < "v3.3.3" ]]
        then
          ADDITIONAL_FLAGS="''${GMP_ROOT:+-L$GMP_ROOT/lib -lgmp} ''${MPFR_ROOT:+-L$MPFR_ROOT/lib -lmpfr} $BOOST_LIBS ''${CGAL_ROOT:+-L$CGAL_ROOT/lib -lCGAL -I$CGAL_ROOT/include} ''${BOOST_ROOT:+-I$BOOST_ROOT/include} ''${GMP_ROOT:+-I$GMP_ROOT/include} ''${MPFR_ROOT:+-I$MPFR_ROOT/include} ''${CGAL_ROOT:+-DCGAL_DO_NOT_USE_MPZF} -O2 -g"
          export CXXFLAGS="$CXXFLAGS $ARCH_FLAGS $ADDITIONAL_FLAGS"
          export CFLAGS="$CFLAGS $ARCH_FLAGS $ADDITIONAL_FLAGS"
          export CPATH="''${BOOST_INC}''${CGAL_ROOT:+$CGAL_ROOT/include:}''${GMP_ROOT:+$GMP_ROOT/include:}''${MPFR_ROOT:+$MPFR_ROOT/include}"
          export C_INCLUDE_PATH="''${BOOST_INC}''${GMP_ROOT:+$GMP_ROOT/include:}''${MPFR_ROOT:+$MPFR_ROOT/include}"
          ./configure --enable-shared \
                      ''${CGAL_ROOT:+--enable-cgal --with-cgal=$CGAL_ROOT} \
                      --prefix=$INSTALLROOT \
                      --enable-allcxxplugins
        else
          export CXXFLAGS="$CXXFLAGS $ARCH_FLAGS"
          ./configure --enable-shared         \
                      ''${CGAL_ROOT:+--enable-cgal \
                      --with-cgaldir=$CGAL_ROOT  \
                      --with-cgal-boostdir=$BOOST_ROOT  \
                      ''${GMP_ROOT:+--with-cgal-gmpdir=$GMP_ROOT}  \
                      ''${MPFR_ROOT:+--with-cgal-mpfrdir=$MPFR_ROOT}}  \
                      --prefix=$INSTALLROOT   \
                      --enable-allcxxplugins  \
      		--disable-auto-ptr
        fi
        make ''${JOBS:+-j$JOBS}
        make install
      popd

      # FastJet Contrib
      pushd fjcontrib
        ./configure --fastjet-config=$INSTALLROOT/bin/fastjet-config \
                    CXXFLAGS="$CXXFLAGS" \
                    CFLAGS="$CFLAGS" \
                    CPATH="$CPATH" \
                    C_INCLUDE_PATH="$C_INCLUDE_PATH"
        make ''${JOBS:+-j$JOBS}
        make install
        make fragile-shared ''${JOBS:+-j$JOBS}
        make fragile-shared-install
      popd

      rm -f $INSTALLROOT/lib/*.la

      # Dependencies relocation: rely on runtime environment.  That is,
      # specific paths in the generated script are replaced by expansions of
      # the relevant environment variables.
      SED_EXPR="s!x!x!"  # noop
      for P in $REQUIRES $BUILD_REQUIRES; do
        UPPER=$(echo $P | tr '[:lower:]' '[:upper:]' | tr '-' '_')
        EXPAND=$(eval echo \$''${UPPER}_ROOT)
        [[ $EXPAND ]] || continue
        SED_EXPR="$SED_EXPR; s!$EXPAND!\$''${UPPER}_ROOT!g"
      done

      # Modify fastjet-config to use environment
      cat $INSTALLROOT/bin/fastjet-config | sed -e "$SED_EXPR" > $INSTALLROOT/bin/fastjet-config.0
      mv $INSTALLROOT/bin/fastjet-config.0 $INSTALLROOT/bin/fastjet-config
      chmod 0755 $INSTALLROOT/bin/fastjet-config

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${CGAL_REVISION:+cgal/$CGAL_VERSION-$CGAL_REVISION} ''${GMP_REVISION:+GMP/$GMP_VERSION-$GMP_REVISION}
      # Our environment
      set FASTJET_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv FASTJET \$FASTJET_ROOT
      prepend-path PATH \$FASTJET_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$FASTJET_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$FASTJET_ROOT/include
      EoF
      runHook postInstall
    '';
  };

  cgal = stdenv.mkDerivation {
    name = "cgal";
    version = "4.12.2";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      GMP
      MPFR
      curl
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      boost
      GMP
      MPFR
      curl
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=cgal
      PKGVERSION=4.12.2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export GMP_ROOT=${ GMP.out }
      GMP_REVISION=1
      
      export MPFR_ROOT=${ MPFR.out }
      MPFR_REVISION=1
      
      export CURL_ROOT=${ curl.out }
      CURL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export BOOST_ROOT=${ boost.out }
      BOOST_VERSION=${ boost.version }
      BOOST_REVISION=1
      
      export GMP_ROOT=${ GMP.out }
      GMP_VERSION=${ GMP.version }
      GMP_REVISION=1
      
      export MPFR_ROOT=${ MPFR.out }
      MPFR_VERSION=${ MPFR.version }
      MPFR_REVISION=1
      
      export CURL_ROOT=${ curl.out }
      CURL_VERSION=${ curl.version }
      CURL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      case $ARCHITECTURE in
        osx*)
          # If we preferred system tools, we need to make sure we can pick them up.
          [[ ! $BOOST_ROOT ]] && BOOST_ROOT=`brew --prefix boost`
        ;;
      esac
      URL="https://github.com/CGAL/cgal/releases/download/releases%2FCGAL-$PKGVERSION/CGAL-$PKGVERSION.tar.xz"

      curl -kLo cgal.tar.xz "$URL"
      tar xJf cgal.tar.xz
      cd CGAL-*

      if [[ "$BOOST_ROOT" != ''' ]]; then
        export LDFLAGS="-L$BOOST_ROOT/lib"
        export LD_LIBRARY_PATH="$BOOST_ROOT/lib:$LD_LIBRARY_PATH"
        export DYLD_LIBRARY_PATH="$BOOST_ROOT/lib:$LD_LIBRARY_PATH"
      fi

      export MPFR_LIB_DIR="''${MPFR_ROOT}/lib"
      export MPFR_INC_DIR="''${MPFR_ROOT}/include"
      export GMP_LIB_DIR="''${GMP_ROOT}/lib"
      export GMP_INC_DIR="''${GMP_ROOT}/include"

      cmake . \
            -DCMAKE_INSTALL_PREFIX:PATH="''${INSTALLROOT}" \
            -DCMAKE_INSTALL_LIBDIR:PATH="lib" \
            -DCMAKE_BUILD_TYPE=Release \
            -DWITH_BLAS:BOOL=OFF \
            -DWITH_CGAL_Core:BOOL=ON \
            -DWITH_CGAL_ImageIO:BOOL=ON \
            -DWITH_CGAL_Qt3:BOOL=OFF \
            -DWITH_CGAL_Qt4:BOOL=OFF \
            -DWITH_CGAL_Qt5:BOOL=OFF \
            -DWITH_Coin3D:BOOL=OFF \
            -DWITH_ESBTL:BOOL=OFF \
            -DWITH_Eigen3:BOOL=OFF \
            -DWITH_GMP:BOOL=ON \
            -DWITH_GMPXX:BOOL=OFF \
            -DWITH_IPE:BOOL=OFF \
            -DWITH_LAPACK:BOOL=OFF \
            -DWITH_LEDA:BOOL=OFF \
            -DWITH_MPFI:BOOL=OFF \
            -DWITH_MPFR:BOOL=ON \
            -DWITH_NTL:BOOL=OFF \
            -DWITH_OpenGL:BOOL=OFF \
            -DWITH_OpenNL:BOOL=OFF \
            -DWITH_QGLViewer:BOOL=OFF \
            -DWITH_RS:BOOL=OFF \
            -DWITH_RS3:BOOL=OFF \
            -DWITH_TAUCS:BOOL=OFF \
            -DWITH_ZLIB:BOOL=ON \
            -DWITH_demos:BOOL=OFF \
            -DWITH_examples:BOOL=OFF \
            -DCGAL_ENABLE_PRECONFIG:BOOL=NO \
            -DCGAL_IGNORE_PRECONFIGURED_GMP:BOOL=YES \
            -DCGAL_IGNORE_PRECONFIGURED_MPFR:BOOL=YES \
            ''${BOOST_ROOT:+-DBoost_NO_SYSTEM_PATHS:BOOL=TRUE -DBOOST_ROOT:PATH="$BOOST_ROOT"}

      make VERBOSE=1 ''${JOBS:+-j$JOBS}
      make install VERBOSE=1

      find $INSTALLROOT/lib/ -name "*.dylib" -exec install_name_tool -add_rpath @loader_path/../lib {} \;
      find $INSTALLROOT/lib/ -name "*.dylib" -exec install_name_tool -add_rpath ''${INSTALLROOT}/lib {} \;
      find $INSTALLROOT/lib/ -name "*.dylib" -exec install_name_tool -id {} {} \;

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${BOOST_REVISION:+boost/$BOOST_VERSION-$BOOST_REVISION}
      # Our environment
      set CGAL_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv CGAL_ROOT \$CGAL_ROOT
      prepend-path PATH \$CGAL_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$CGAL_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  GMP = stdenv.mkDerivation {
    name = "GMP";
    version = "v6.2.1";
    
    
    src=(builtins.fetchGit {
    rev="2bbd52703e5af82509773264bfbd20ff8464804f";
    url="https://github.com/alisw/GMP.git";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=GMP
      PKGVERSION=v6.2.1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/sh
      case $ARCHITECTURE in
        osx*) MARCH="" ;;
        *x86-64) MARCH="core2" ;;
        *) MARCH= ;;
      esac

      # temporary fix C23 (since gcc 15) compatibility
      sed -i.orig 's/void g(){}/void g(int p1,t1 const* p2,t1 p3,t2 p4,t1 const* p5,int p6){}/' "$SOURCEDIR/acinclude.m4"
      sed -i.orig 's/void g(){}/void g(int p1,t1 const* p2,t1 p3,t2 p4,t1 const* p5,int p6){}/' "$SOURCEDIR/configure"

      case $ARCHITECTURE in
        osx*)
            $SOURCEDIR/configure --prefix=$INSTALLROOT \
      			   --enable-cxx \
      			   --disable-static \
      			   --enable-shared \
      			   ''${MARCH:+--build=$MARCH --host=$MARCH} \
      			   --with-pic
        ;;
        *)
            $SOURCEDIR/configure --prefix=$INSTALLROOT \
      			   --enable-cxx \
      			   --enable-static \
      			   --disable-shared \
      			   ''${MARCH:+--build=$MARCH --host=$MARCH} \
      			   --with-pic
        ;;
      esac

      make ''${JOBS+-j $JOBS} MAKEINFO=:
      make install MAKEINFO=:

      rm -f $INSTALLROOT/lib/*.la

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${GCC_TOOLCHAIN_ROOT:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION}
      # Our environment
      set GMP_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv GMP_ROOT \$GMP_ROOT
      prepend-path LD_LIBRARY_PATH \$GMP_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  Python = stdenv.mkDerivation {
    name = "Python";
    version = "python-brew3.12.10";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Python
      PKGVERSION=python-brew3.12.10
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      
      runHook postInstall
    '';
  };

  Python-modules = stdenv.mkDerivation {
    name = "Python-modules";
    version = "virtualenv";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      Python-modules-list
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      hdf5
      Python-modules-list
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Python-modules
      PKGVERSION=virtualenv
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export PYTHON_MODULES_LIST_ROOT=${ Python-modules-list.out }
      PYTHON_MODULES_LIST_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export HDF5_ROOT=${ hdf5.out }
      HDF5_VERSION=${ hdf5.version }
      HDF5_REVISION=1
      
      export PYTHON_MODULES_LIST_ROOT=${ Python-modules-list.out }
      PYTHON_MODULES_LIST_VERSION=${ Python-modules-list.version }
      PYTHON_MODULES_LIST_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      # Install pinned basic requirements for python infrastructure
      echo "$PIP_BASE_REQUIREMENTS" > base-requirements.txt
      python3 -m pip install -IU -r base-requirements.txt
      # The above updates pip and setuptools, so install the rest of the packages separately.
      echo "$PIP_REQUIREMENTS" > requirements.txt
      python3 -m pip install -IU -r requirements.txt
      # We do not need anything else, because python is going to be in path
      # if we are inside a virtualenv so no need to pretend we know where
      # the correct python is.

      # We generate the modulefile to avoid complains by dependencies
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  alibuild-recipe-tools = stdenv.mkDerivation {
    name = "alibuild-recipe-tools";
    version = "0.2.5";
    
    
    src=(builtins.fetchGit {
    rev="4f9f0284fa8d83bffd485cb04162e6b8994fb6ee";
    url="https://github.com/alisw/alibuild-recipe-tools";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=alibuild-recipe-tools
      PKGVERSION=0.2.5
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      mkdir -p $INSTALLROOT/bin
      install $SOURCEDIR/alibuild-generate-module $INSTALLROOT/bin

      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0
      # Our environment
      set ALIBUILD_RECIPE_TOOLS_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path LD_LIBRARY_PATH \$ALIBUILD_RECIPE_TOOLS_ROOT/lib
      prepend-path PATH \$ALIBUILD_RECIPE_TOOLS_ROOT/bin
      EoF
      runHook postInstall
    '';
  };

  defaults-release = stdenv.mkDerivation {
    name = "defaults-release";
    version = "v1";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=defaults-release
      PKGVERSION=v1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      
      mkdir -p $BUILDDIR
      
      runHook postInstall
    '';
  };

  ROOT = stdenv.mkDerivation {
    name = "ROOT";
    version = "v6-32-06-alice9";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/v6-32-06-alice9";
    url="https://github.com/alisw/root.git";});

    
    buildInputs = [
      Xcode
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      arrow
      AliEn-Runtime
      GSL
      Python-modules
      XRootD
      TBB
      protobuf
      FFTW3
      Vc
      pythia
      Xcode
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=ROOT
      PKGVERSION=v6-32-06-alice9
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export XCODE_ROOT=${ Xcode.out }
      XCODE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ARROW_ROOT=${ arrow.out }
      ARROW_VERSION=${ arrow.version }
      ARROW_REVISION=1
      
      export ALIEN_RUNTIME_ROOT=${ AliEn-Runtime.out }
      ALIEN_RUNTIME_VERSION=${ AliEn-Runtime.version }
      ALIEN_RUNTIME_REVISION=1
      
      export GSL_ROOT=${ GSL.out }
      GSL_VERSION=${ GSL.version }
      GSL_REVISION=1
      
      export PYTHON_MODULES_ROOT=${ Python-modules.out }
      PYTHON_MODULES_VERSION=${ Python-modules.version }
      PYTHON_MODULES_REVISION=1
      
      export XROOTD_ROOT=${ XRootD.out }
      XROOTD_VERSION=${ XRootD.version }
      XROOTD_REVISION=1
      
      export TBB_ROOT=${ TBB.out }
      TBB_VERSION=${ TBB.version }
      TBB_REVISION=1
      
      export PROTOBUF_ROOT=${ protobuf.out }
      PROTOBUF_VERSION=${ protobuf.version }
      PROTOBUF_REVISION=1
      
      export FFTW3_ROOT=${ FFTW3.out }
      FFTW3_VERSION=${ FFTW3.version }
      FFTW3_REVISION=1
      
      export VC_ROOT=${ Vc.out }
      VC_VERSION=${ Vc.version }
      VC_REVISION=1
      
      export PYTHIA_ROOT=${ pythia.out }
      PYTHIA_VERSION=${ pythia.version }
      PYTHIA_REVISION=1
      
      export XCODE_ROOT=${ Xcode.out }
      XCODE_VERSION=${ Xcode.version }
      XCODE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      # Fix the syntax highlighing when your editor is not smart enough to 
      # understand yaml.
      cat >/dev/null <<EOF
      EOF

      unset ROOTSYS
      COMPILER_CC=cc
      COMPILER_CXX=c++
      COMPILER_LD=c++
      [[ "$CXXFLAGS" == *'-std=c++11'* ]] && CMAKE_CXX_STANDARD=11 || true
      [[ "$CXXFLAGS" == *'-std=c++14'* ]] && CMAKE_CXX_STANDARD=14 || true
      [[ "$CXXFLAGS" == *'-std=c++17'* ]] && CMAKE_CXX_STANDARD=17 || true
      [[ "$CXXFLAGS" == *'-std=c++20'* ]] && CMAKE_CXX_STANDARD=20 || true

      # We do not use global options for ROOT, otherwise the -g will
      # kill compilation on < 8GB machines
      unset CXXFLAGS
      unset CFLAGS
      unset LDFLAGS

      SONAME=so
      case $ARCHITECTURE in
        osx*)
          ENABLE_COCOA=1
          DISABLE_MYSQL=1
          USE_BUILTIN_GLEW=1
          COMPILER_CC=clang
          COMPILER_CXX=clang++
          COMPILER_LD=clang
          SONAME=dylib
          [[ ! $GSL_ROOT ]] && GSL_ROOT=$(brew --prefix gsl)
          [[ ! $OPENSSL_ROOT ]] && SYS_OPENSSL_ROOT=$(brew --prefix openssl@3)
          [[ ! $LIBPNG_ROOT ]] && LIBPNG_ROOT=$(brew --prefix libpng)
        ;;
      esac

      if [[ $ALIEN_RUNTIME_VERSION ]]; then
        # AliEn-Runtime: we take OpenSSL and libxml2 from there, in case they
        # were not taken from the system
        OPENSSL_ROOT=''${OPENSSL_ROOT:+$ALIEN_RUNTIME_ROOT}
        LIBXML2_ROOT=''${LIBXML2_REVISION:+$ALIEN_RUNTIME_ROOT}
      fi
      [[ $SYS_OPENSSL_ROOT ]] && OPENSSL_ROOT=$SYS_OPENSSL_ROOT

      # ROOT 6+: enable Python
      ROOT_PYTHON_FLAGS="-Dpyroot=ON"
      ROOT_HAS_PYTHON=1
      python_exec=$(python -c 'import distutils.sysconfig; print(distutils.sysconfig.get_config_var("exec_prefix"))')/bin/python3
      if [ "$python_exec" = "$(which python)" ]; then
        # By default, if there's nothing funny going on, let ROOT pick the Python in
        # the PATH, which is the one built by us (unless disabled, in which case it
        # is the system one). This is substituted into ROOT's Python scripts'
        # shebang lines, so we cannot use an absolute path because the path to our
        # Python will differ between build time and runtime, e.g. on the Grid.
        PYTHON_EXECUTABLE=
      else
        # If Python's exec_prefix doesn't point to the same place as $PATH, then we
        # have a shim script in between. This is used by things like pyenv and asdf.
        # This doesn't happen when building things to be published, only in local
        # usage, so hardcoding an absolute path into the shebangs is fine.
        PYTHON_EXECUTABLE=$python_exec
      fi

      if [ -n "$XROOTD_ROOT" ]; then
        ROOT_XROOTD_FLAGS="-Dxrootd=ON -DXROOTD_ROOT_DIR=$XROOTD_ROOT"
      else
        # If we didn't build XRootD (e.g. if it was disabled by a default), explicitly
        # disable support for it -- otherwise, ROOT will download and compile against
        # its own XRootD version.
        ROOT_XROOTD_FLAGS='-Dxrootd=OFF'
      fi

      case $PKG_VERSION in
        v6[-.]30*) EXTRA_CMAKE_OPTIONS="-Dminuit2=ON -Dpythia6=ON -Dpythia6_nolink=ON" ;;
        v6[-.]32[-.]0[6789]*) EXTRA_CMAKE_OPTIONS="-Dminuit=ON -Dpythia6=ON -Dpythia6_nolink=ON -Dproof=ON" ;;
        *) EXTRA_CMAKE_OPTIONS="-Dminuit=ON" ;;
      esac

      unset DYLD_LIBRARY_PATH
      CMAKE_GENERATOR=''${CMAKE_GENERATOR:-Ninja}
      # Standard ROOT build
      cmake $SOURCEDIR                                                                       \
            ''${CMAKE_GENERATOR:+-G "$CMAKE_GENERATOR"}                                        \
            -DCMAKE_BUILD_TYPE=$CMAKE_BUILD_TYPE                                             \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT                                              \
            -Dalien=OFF                                                                      \
            ''${CMAKE_CXX_STANDARD:+-DCMAKE_CXX_STANDARD=''${CMAKE_CXX_STANDARD}}                \
            -Dfreetype=ON                                                                    \
            -Dbuiltin_freetype=OFF                                                           \
            -Dpcre=OFF                                                                       \
            -Dbuiltin_pcre=ON                                                                \
            -Dsqlite=OFF                                                                     \
            $ROOT_XROOTD_FLAGS                                                               \
            $ROOT_PYTHON_FLAGS                                                               \
            ''${ARROW_ROOT:+-Darrow=ON}                                                        \
            ''${ARROW_ROOT:+-DARROW_HOME=$ARROW_ROOT}                                          \
            ''${ENABLE_COCOA:+-Dcocoa=ON}                                                      \
            ''${EXTRA_CMAKE_OPTIONS}                                                           \
            -DCMAKE_CXX_COMPILER=$COMPILER_CXX                                               \
            -DCMAKE_C_COMPILER=$COMPILER_CC                                                  \
            -Dfortran=OFF                                                                    \
            -DCMAKE_LINKER=$COMPILER_LD                                                      \
            ''${GCC_TOOLCHAIN_REVISION:+-DCMAKE_EXE_LINKER_FLAGS="-L$GCC_TOOLCHAIN_ROOT/lib64"} \
            ''${OPENSSL_ROOT:+-DOPENSSL_ROOT=$OPENSSL_ROOT}                                    \
            ''${OPENSSL_ROOT:+-DOPENSSL_INCLUDE_DIR=$OPENSSL_ROOT/include}                     \
            ''${OPENSSL_ROOT:+-DOPENSSL_LIBRARIES=$OPENSSL_ROOT/lib/libssl.$SONAME;$OPENSSL_ROOT/lib/libcrypto.$SONAME}  \
            ''${LIBXML2_ROOT:+-DLIBXML2_ROOT=$LIBXML2_ROOT}                                    \
            ''${GSL_ROOT:+-DGSL_DIR=$GSL_ROOT}                                                 \
            ''${LIBPNG_ROOT:+-DPNG_INCLUDE_DIRS="''${LIBPNG_ROOT}/include"}                      \
            ''${LIBPNG_ROOT:+-DPNG_LIBRARY="''${LIBPNG_ROOT}/lib/libpng.''${SONAME}"}              \
            ''${PROTOBUF_REVISION:+-DProtobuf_DIR=''${PROTOBUF_ROOT}}                            \
            ''${ZLIB_ROOT:+-DZLIB_ROOT=''${ZLIB_ROOT}}                                           \
            ''${FFTW3_ROOT:+-DFFTW_DIR=''${FFTW3_ROOT}}                                          \
            ''${NLOHMANN_JSON_ROOT:+nlohmann_json_DIR=''${NLOHMANN_JSON_ROOT}}                   \
            -Dfftw3=ON                                                                       \
            -Dpgsql=OFF                                                                      \
            -Dminuit=ON                                                                      \
            -Dmathmore=ON                                                                    \
            -Droofit=ON                                                                      \
            -Dhttp=ON                                                                        \
            -Droot7=ON                                                                       \
            -Dsoversion=ON                                                                   \
            -Dshadowpw=OFF                                                                   \
            -Dvdt=OFF                                                                        \
            -Dvc=ON                                                                          \
            -Dbuiltin_vc=OFF                                                                 \
            -Dbuiltin_vdt=OFF                                                                \
            -Dgviz=OFF                                                                       \
            -Dbuiltin_davix=OFF                                                              \
            -Dbuiltin_fftw3=OFF                                                              \
            -Dtmva-sofie=ON                                                                  \
            -Dtmva-gpu=OFF                                                                   \
            -Ddavix=OFF                                                                      \
            -Dunfold=ON                                                                      \
            -Dpythia8=ON                                                                     \
            ''${USE_BUILTIN_GLEW:+-Dbuiltin_glew=ON}                                           \
            ''${DISABLE_MYSQL:+-Dmysql=OFF}                                                    \
            ''${ROOT_HAS_PYTHON:+-DPYTHON_PREFER_VERSION=3}                                    \
            ''${PYTHON_EXECUTABLE:+-DPYTHON_EXECUTABLE="''${PYTHON_EXECUTABLE}"}                 \
      -DCMAKE_PREFIX_PATH="$FREETYPE_ROOT;$SYS_OPENSSL_ROOT;$GSL_ROOT;$ALIEN_RUNTIME_ROOT;$PYTHON_ROOT;$PYTHON_MODULES_ROOT;$LIBPNG_ROOT;$LZMA_ROOT;$PROTOBUF_ROOT;$FFTW3_ROOT"

      # Workaround issue with cmake 3.29.0
      sed -i.removeme '/deps = gcc/d' build.ninja
      rm *.removeme
      cmake --build . --target install ''${JOBS+-j $JOBS}

      # Make sure ROOT actually found its build dependencies and didn't disable
      # features we requested. "-Dfail-on-missing=ON" would probably be better.
      [ "$("$INSTALLROOT/bin/root-config" --has-fftw3)" = yes ]

      # Add support for ROOT_PLUGIN_PATH envvar for specifying additional plugin search paths
      grep -v '^Unix.*.Root.PluginPath' $INSTALLROOT/etc/system.rootrc > system.rootrc.0
      cat >> system.rootrc.0 <<\EOF
      # Specify additional plugin search paths via the environment variable ROOT_PLUGIN_PATH.
      # Plugins in $ROOT_PLUGIN_PATH have priority.
      Unix.*.Root.PluginPath: $(ROOT_PLUGIN_PATH):$(ROOTSYS)/etc/plugins:
      Unix.*.Root.DynamicPath: .:$(ROOT_DYN_PATH):
      EOF
      mv system.rootrc.0 $INSTALLROOT/etc/system.rootrc

      if [[ $ALIEN_RUNTIME_VERSION ]]; then
        # Get them from AliEn-Runtime in the Modulefile
        unset OPENSSL_VERSION LIBXML2_VERSION OPENSSL_REVISION LIBXML2_REVISION
      fi

      # Make some CMake files used by other projects relocatable
      sed -i.deleteme -e "s!$BUILDDIR!$INSTALLROOT!g" $(find "$INSTALLROOT" -name '*.cmake') || true

      rm -vf "$INSTALLROOT/etc/plugins/TGrid/P010_TAlien.C"         \
             "$INSTALLROOT/etc/plugins/TSystem/P030_TAlienSystem.C" \
             "$INSTALLROOT/etc/plugins/TFile/P070_TAlienFile.C"     \
             "$INSTALLROOT/LICENSE"

      # Make sure all the tools use the correct python
      for binfile in "$INSTALLROOT"/bin/*; do
        [ -f "$binfile" ] || continue
        if grep -q "^''''exec' .*python.*" "$binfile"; then
          # This file uses a hack to get around shebang size limits. As we're
          # replacing the shebang with the system python, the limit doesn't apply and
          # we can just use a normal shebang.
          sed -i.bak '1d; 2d; 3d; 4s,^,#!/usr/bin/env python3\n,' "$binfile"
        else
          sed -i.bak '1s,^#!.*python.*,#!/usr/bin/env python3,' "$binfile"
        fi
      done
      rm -fv "$INSTALLROOT"/bin/*.bak

      # Modulefile
      mkdir -p etc/modulefiles
      alibuild-generate-module --bin --lib > etc/modulefiles/$PKGNAME
      cat >> etc/modulefiles/$PKGNAME <<EoF
      # Our environment
      setenv ROOT_RELEASE \$version
      setenv ROOT_BASEDIR \$::env(BASEDIR)/$PKGNAME
      setenv ROOTSYS \$::env(ROOT_BASEDIR)/\$::env(ROOT_RELEASE)
      prepend-path PYTHONPATH \$PKG_ROOT/lib
      prepend-path ROOT_DYN_PATH \$PKG_ROOT/lib
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles

      # External RPM dependencies
      cat > $INSTALLROOT/.rpm-extra-deps <<EoF
      glibc-headers
      EoF
      runHook postInstall
    '';
  };

  hdf5 = stdenv.mkDerivation {
    name = "hdf5";
    version = "1.14.6";
    
    
    src=(builtins.fetchGit {
    rev="7bf340440909d468dbb3cf41f0ea0d87f5050cea";
    url="https://github.com/HDFGroup/hdf5.git";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=hdf5
      PKGVERSION=1.14.6
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
        cmake "$SOURCEDIR"                             \
          -DCMAKE_CMAKE_BUILD_TYPE="''${CMAKE_BUILD_TYPE:-Release}" \
          -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
          -DBUILD_TESTING=OFF                          \
          ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}      \
          -DHDF5_BUILD_CPP_LIB=ON

      cmake --build . -- ''${IGNORE_ERRORS:+-k} ''${JOBS+-j $JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > "$MODULEFILE"
      runHook postInstall
    '';
  };

  boost = stdenv.mkDerivation {
    name = "boost";
    version = "v1.83.0-alice2";
    
    
    src=(builtins.fetchGit {
    rev="52e0d24c2177aa5242ae187cdb4ff4283b431ed1";
    url="https://github.com/alisw/boost.git";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python-modules
      zlib
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=boost
      PKGVERSION=v1.83.0-alice2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_MODULES_ROOT=${ Python-modules.out }
      PYTHON_MODULES_VERSION=${ Python-modules.version }
      PYTHON_MODULES_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      BOOST_PYTHON=
      BOOST_CXXFLAGS=
      if [[ $ARCHITECTURE != osx* && $PYTHON_MODULES_VERSION ]]; then
        # Enable boost_python on platforms other than macOS
        BOOST_PYTHON=1
        if [[ $PYTHON_VERSION ]]; then
          # Our Python. We need to pass the appropriate flags to boost for the includes
          BOOST_CXXFLAGS="$(python3-config --includes)"
        else
          # Using system's Python. We want to make sure `python-config` is available in $PATH and points
          # to the Python 3 version. Note that a symlink will not work due to the automatic prefix
          # calculation of the python-config script. Our own Python does not require tricks
          if ! type python3-config &> /dev/null; then
            echo "FATAL: cannot find python3-config in your \$PATH. Cannot enable boost_python"
            exit 1
          fi
          mkdir fake_bin
          cat > fake_bin/python-config <<\EOF
      #!/bin/bash
      exec python3-config "$@"
      EOF
          chmod +x fake_bin/python-config
          ln -nfs "$(which python3)" fake_bin/python
          ln -nfs "$(which pip3)" fake_bin/pip
          export PATH="$PWD/fake_bin:$PATH"
        fi
      fi

      BOOST_NO_PYTHON=
      if [[ ! $BOOST_PYTHON ]]; then
        BOOST_NO_PYTHON=1
      fi

      if [[ $CXXSTD && $CXXSTD -ge 17 ]]; then
        # Use C++17: https://github.com/boostorg/system/issues/26#issuecomment-413631998
        CXXSTD=17
      fi

      TMPB2=$BUILDDIR/tmp-boost-build
      case $ARCHITECTURE in
        osx*) TOOLSET=clang ;;
        *) TOOLSET=gcc ;;
      esac

      rsync -a --no-specials --no-devices  --chmod=ug=rwX --exclude '**/.git' --delete --delete-excluded "$SOURCEDIR"/ "$BUILDDIR"/
      cd "$BUILDDIR"/tools/build
      # This is to work around an issue in boost < 1.70 where the include path misses
      # the ABI suffix. E.g. ../include/python3 rather than ../include/python3m.
      # This is causing havok on different combinations of Ubuntu / Anaconda
      # installations.
      bash bootstrap.sh $TOOLSET
      case $ARCHITECTURE in
        osx*)  ;;
        *) export CPLUS_INCLUDE_PATH="$CPLUS_INCLUDE_PATH:$(python3 -c 'import sysconfig; print(sysconfig.get_path("include"))')" ;;
      esac
      mkdir -p $TMPB2
      ./b2 install --prefix=$TMPB2
      export PATH=$TMPB2/bin:$PATH
      cd $BUILDDIR
      b2 -q                                                 \
         -d2                                                \
         ''${JOBS+-j $JOBS}                                   \
         --prefix="$INSTALLROOT"                            \
         --build-dir=build-boost                            \
         --disable-icu                                      \
         --without-context                                  \
         --without-coroutine                                \
         --without-graph                                    \
         --without-graph_parallel                           \
         --without-locale                                   \
         --without-mpi                                      \
         ''${BOOST_NO_PYTHON:+--without-python}               \
         --debug-configuration                              \
         -sNO_ZSTD=1                                        \
         ''${BZ2_ROOT:+-sBZIP2_INCLUDE="$BZ2_ROOT/include"}   \
         ''${BZ2_ROOT:+-sBZIP2_LIBPATH="$BZ2_ROOT/lib"}       \
         ''${ZLIB_ROOT:+-sZLIB_INCLUDE="$ZLIB_ROOT/include"}  \
         ''${ZLIB_ROOT:+-sZLIB_LIBPATH="$ZLIB_ROOT/lib"}      \
         ''${LZMA_ROOT:+-sLZMA_INCLUDE="$LZMA_ROOT/include"}  \
         ''${LZMA_ROOT:+-sLZMA_LIBPATH="$LZMA_ROOT/lib"}      \
         toolset=$TOOLSET                                   \
         link=shared                                        \
         threading=multi                                    \
         variant=release                                    \
         ''${BOOST_CXXFLAGS:+cxxflags="$BOOST_CXXFLAGS"}      \
         ''${CXXSTD:+cxxstd=$CXXSTD}                          \
         install

      # If boost_python is enabled, check if it was really compiled
      [[ $BOOST_PYTHON ]] && ls -1 "$INSTALLROOT"/lib/*boost_python* > /dev/null

      # We need to tell boost libraries linking other boost libraries to look for them
      # inside the same directory as the main ones, on macOS (@loader_path).
      if [[ $ARCHITECTURE == osx* ]]; then
        for LIB in "$INSTALLROOT"/lib/libboost*.dylib; do
          otool -L "$LIB" | grep -v "$(basename "$LIB")" | { grep -oE 'libboost_[^ ]+' || true; } | \
            xargs -I{} install_name_tool -change {} @loader_path/{} "$LIB"
        done
      fi

      # Modulefile
      mkdir -p etc/modulefiles
      alibuild-generate-module --lib --cmake > etc/modulefiles/"$PKGNAME"
      cat << EOF >> etc/modulefiles/"$PKGNAME"
      prepend-path ROOT_INCLUDE_PATH \$PKG_ROOT/include
      EOF
      mkdir -p "$INSTALLROOT"/etc/modulefiles && rsync -a --no-specials --no-devices  --delete etc/modulefiles/ "$INSTALLROOT"/etc/modulefiles
      runHook postInstall
    '';
  };

  MPFR = stdenv.mkDerivation {
    name = "MPFR";
    version = "v3.1.3";
    
    
    src=(builtins.fetchGit {
    rev="d0edb09adbf3386749aa73af887364ba9d34510b";
    url="https://github.com/alisw/MPFR.git";});

    
    
    
    buildInputs = [
      GMP
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      GMP
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=MPFR
      PKGVERSION=v3.1.3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export GMP_ROOT=${ GMP.out }
      GMP_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export GMP_ROOT=${ GMP.out }
      GMP_VERSION=${ GMP.version }
      GMP_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/sh
      rsync -a --chmod=ug=rwX --delete --exclude .git --delete-excluded $SOURCEDIR/ .
      sed -i.bak -e 's/ doc / /' Makefile.am
      rm *.bak
      autoreconf -ivf

      ./configure --prefix=$INSTALLROOT    \
                  --disable-shared         \
                  --enable-static          \
                  --with-gmp=$GMP_ROOT     \
                  --with-pic

      make ''${JOBS+-j $JOBS}
      make install

      rm -f $INSTALLROOT/lib/*.la

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module > "$MODULEFILE"
      cat >> "$MODULEFILE" <<EoF

      # Our environment
      set MPFR_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv MPFR_ROOT \$MPFR_ROOT
      prepend-path LD_LIBRARY_PATH \$MPFR_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  curl = stdenv.mkDerivation {
    name = "curl";
    version = "7.70.0";
    
    
    src=(builtins.fetchGit {
    rev="4eef6710d4feacf7caf575c3fe60deed5c95d2f0";
    url="https://github.com/curl/curl.git";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=curl
      PKGVERSION=7.70.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      if [[ $ARCHITECTURE = osx* ]]; then
        OPENSSL_ROOT=$(brew --prefix openssl@3)
      else
        ''${OPENSSL_ROOT:+env LDFLAGS=-Wl,-R$OPENSSL_ROOT/lib}
      fi
      rsync -a --chmod=ug=rwX  --delete --exclude="**/.git" --delete-excluded $SOURCEDIR/ .

      sed -i.deleteme 's/CPPFLAGS="$CPPFLAGS $SSL_CPPFLAGS"/CPPFLAGS="$SSL_CPPFLAGS $CPPFLAGS"/' configure.ac
      sed -i.deleteme 's/LDFLAGS="$LDFLAGS $SSL_LDFLAGS"/LDFLAGS="$SSL_LDFLAGS $LDFLAGS"/' configure.ac

      ./buildconf
      ./configure --prefix=$INSTALLROOT --disable-ldap ''${OPENSSL_ROOT:+--with-ssl=$OPENSSL_ROOT} --disable-static
      make ''${JOBS:+-j$JOBS}
      make install

      # Modulefile
      mkdir -p etc/modulefiles
      alibuild-generate-module --bin --lib > etc/modulefiles/$PKGNAME
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  Python-modules-list = stdenv.mkDerivation {
    name = "Python-modules-list";
    version = "1.0";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Python-modules-list
      PKGVERSION=1.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  arrow = stdenv.mkDerivation {
    name = "arrow";
    version = "v20.0.0-alice1";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/apache-arrow-20.0.0-alice1";
    url="https://github.com/alisw/arrow.git";});

    
    buildInputs = [
      zlib
      flatbuffers
      RapidJSON
      double-conversion
      re2
      alibuild-recipe-tools
      Python
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      boost
      Clang
      protobuf
      utf8proc
      xsimd
      zlib
      flatbuffers
      RapidJSON
      double-conversion
      re2
      alibuild-recipe-tools
      Python
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=arrow
      PKGVERSION=v20.0.0-alice1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_REVISION=1
      
      export FLATBUFFERS_ROOT=${ flatbuffers.out }
      FLATBUFFERS_REVISION=1
      
      export RAPIDJSON_ROOT=${ RapidJSON.out }
      RAPIDJSON_REVISION=1
      
      export DOUBLE_CONVERSION_ROOT=${ double-conversion.out }
      DOUBLE_CONVERSION_REVISION=1
      
      export RE2_ROOT=${ re2.out }
      RE2_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export BOOST_ROOT=${ boost.out }
      BOOST_VERSION=${ boost.version }
      BOOST_REVISION=1
      
      export CLANG_ROOT=${ Clang.out }
      CLANG_VERSION=${ Clang.version }
      CLANG_REVISION=1
      
      export PROTOBUF_ROOT=${ protobuf.out }
      PROTOBUF_VERSION=${ protobuf.version }
      PROTOBUF_REVISION=1
      
      export UTF8PROC_ROOT=${ utf8proc.out }
      UTF8PROC_VERSION=${ utf8proc.version }
      UTF8PROC_REVISION=1
      
      export XSIMD_ROOT=${ xsimd.out }
      XSIMD_VERSION=${ xsimd.version }
      XSIMD_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export FLATBUFFERS_ROOT=${ flatbuffers.out }
      FLATBUFFERS_VERSION=${ flatbuffers.version }
      FLATBUFFERS_REVISION=1
      
      export RAPIDJSON_ROOT=${ RapidJSON.out }
      RAPIDJSON_VERSION=${ RapidJSON.version }
      RAPIDJSON_REVISION=1
      
      export DOUBLE_CONVERSION_ROOT=${ double-conversion.out }
      DOUBLE_CONVERSION_VERSION=${ double-conversion.version }
      DOUBLE_CONVERSION_REVISION=1
      
      export RE2_ROOT=${ re2.out }
      RE2_VERSION=${ re2.version }
      RE2_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      mkdir -p "$INSTALLROOT"
      case $ARCHITECTURE in
        osx*)
          # If we preferred system tools, we need to make sure we can pick them up.
          [[ -z $FLATBUFFERS_ROOT ]] && FLATBUFFERS_ROOT=$(dirname "$(dirname "$(which flatc)")")
          [[ -z $BOOST_ROOT ]] && BOOST_ROOT=$(brew --prefix boost)
          [[ -z $LZ4_ROOT ]] && LZ4_ROOT=$(dirname "$(dirname "$(which lz4)")")
          [[ -z $PROTOBUF_ROOT ]] && PROTOBUF_ROOT=$(dirname "$(dirname "$(which protoc)")")
          [[ -z $UTF8PROC_ROOT ]] && UTF8PROC_ROOT=$(brew --prefix utf8proc)
          [[ ! -d $FLATBUFFERS_ROOT ]] && unset FLATBUFFERS_ROOT
          [[ ! -d $BOOST_ROOT ]] && unset BOOST_ROOT
          [[ ! -d $LZ4_ROOT ]] && unset LZ4_ROOT
          [[ ! -d $PROTOBUF_ROOT ]] && unset PROTOBUF_ROOT
          SONAME=dylib
          cat >no-llvm-symbols.txt << EOF
      _LLVM*
      __ZN4llvm*
      __ZNK4llvm*
      EOF
          CMAKE_SHARED_LINKER_FLAGS="-Wl,-unexported_symbols_list,$PWD/no-llvm-symbols.txt"
        ;;
        *) SONAME=so ;;
      esac

      # Downloaded by CMake, built, and linked statically (not needed at runtime):
      #   zlib, lz4, brotli
      #
      # Taken from our stack, linked statically (not needed at runtime):
      #   flatbuffers
      #
      # Taken from our stack, linked dynamically (needed at runtime):
      #   boost

      mkdir -p ./src_tmp
      rsync -a --chmod=ug=rwX --exclude='**/.git' --delete --delete-excluded "$SOURCEDIR/" ./src_tmp/
      case $ARCHITECTURE in
        osx*)
         # use compatible llvm@18 from brew, if available. This
         # must match the prefer_system_check in clang.sh
         CLANG_EXECUTABLE="''${CLANG_REVISION:+$CLANG_ROOT/bin-safe/clang}"
         if [ -z "''${CLANG_EXECUTABLE}" -a -d "$(brew --prefix llvm)@18" ]; then
           CLANG_EXECUTABLE="$(brew --prefix llvm)@18/bin/clang"
         fi
         ;;
        *)
         CLANG_EXECUTABLE="''${CLANG_ROOT}/bin-safe/clang"
         # this patches version script to hide llvm symbols in gandiva library
         sed -i.deleteme '/^[[:space:]]*extern/ a \ \ \ \ \ \ llvm*; LLVM*;' "./src_tmp/cpp/src/gandiva/symbols.map"
         ;;
      esac

      cmake ./src_tmp/cpp                                                                                 \
            ''${CMAKE_SHARED_LINKER_FLAGS:+-DCMAKE_SHARED_LINKER_FLAGS="$CMAKE_SHARED_LINKER_FLAGS"}        \
            -DARROW_DEPENDENCY_SOURCE=SYSTEM                                                              \
            -G Ninja                                                                                      \
            -DCMAKE_BUILD_TYPE=Release                                                                    \
            ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}                                                       \
            -DBUILD_SHARED_LIBS=TRUE                                                                      \
            -DARROW_BUILD_BENCHMARKS=OFF                                                                  \
            -DARROW_BUILD_TESTS=OFF                                                                       \
            -DARROW_ENABLE_TIMING_TESTS=OFF                                                               \
            -DARROW_USE_GLOG=OFF                                                                          \
            -DARROW_JEMALLOC=OFF                                                                          \
            -DARROW_HDFS=OFF                                                                              \
            -DARROW_IPC=ON                                                                                \
            ''${THRIFT_ROOT:+-DARROW_PARQUET=ON}                                                            \
            ''${THRIFT_ROOT:+-DThrift_ROOT="$THRIFT_ROOT"}                                                  \
            ''${FLATBUFFERS_ROOT:+-DFlatbuffers_ROOT="$FLATBUFFERS_ROOT"}                                   \
            -DCMAKE_INSTALL_LIBDIR="lib"                                                                  \
            -DARROW_WITH_LZ4=ON                                                                           \
            ''${RAPIDJSON_ROOT:+-DRapidJSON_ROOT="$RAPIDJSON_ROOT"}                                         \
            ''${RE2_ROOT:+-DRE2_ROOT="$RE2_ROOT"}                                                           \
            ''${PROTOBUF_ROOT:+-DProtobuf_LIBRARY="$PROTOBUF_ROOT/lib/libprotobuf.$SONAME"}                 \
            ''${PROTOBUF_ROOT:+-DProtobuf_LITE_LIBRARY="$PROTOBUF_ROOT/lib/libprotobuf-lite.$SONAME"}       \
            ''${PROTOBUF_ROOT:+-DProtobuf_PROTOC_LIBRARY="$PROTOBUF_ROOT/lib/libprotoc.$SONAME"}            \
            ''${PROTOBUF_ROOT:+-DProtobuf_INCLUDE_DIR="$PROTOBUF_ROOT/include"}                             \
            ''${PROTOBUF_ROOT:+-DProtobuf_PROTOC_EXECUTABLE="$PROTOBUF_ROOT/bin/protoc"}                    \
            ''${BOOST_ROOT:+-DBoost_ROOT="$BOOST_ROOT"}                                                     \
            ''${LZ4_ROOT:+-DLZ4_ROOT="$LZ4_ROOT"}                                                           \
            ''${UTF8PROC_ROOT:+-Dutf8proc_ROOT="$UTF8PROC_ROOT"}                                            \
            ''${OPENSSL_ROOT:+-DOpenSSL_ROOT="$OPENSSL_ROOT"}                                               \
            ''${CLANG_ROOT:+-DLLVM_DIR="$CLANG_ROOT"}                                                       \
            ''${PYTHON_ROOT:+-DPython3_EXECUTABLE="$(which python3)"}                                       \
            ''${XSIMD_REVISION:+-Dxsimd_DIR=''${XSIMD_ROOT}}                                                  \
            -DARROW_WITH_SNAPPY=OFF                                                                       \
            -DARROW_WITH_ZSTD=OFF                                                                         \
            -DARROW_WITH_BROTLI=OFF                                                                       \
            -DARROW_WITH_ZLIB=ON                                                                          \
            -DARROW_NO_DEPRECATED_API=ON                                                                  \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                                                         \
            -DARROW_TENSORFLOW=ON                                                                         \
            -DARROW_GANDIVA=ON                                                                            \
            -DARROW_COMPUTE=ON                                                                            \
            -DARROW_DATASET=ON                                                                            \
            -DARROW_FILESYSTEM=ON                                                                         \
            -DARROW_BUILD_STATIC=OFF                                                                      \
            -DCMAKE_INSTALL_RPATH_USE_LINK_PATH=ON                                                        \
            ''${GCC_TOOLCHAIN_REVISION:+-DGCC_TOOLCHAIN_ROOT="$(find "$GCC_TOOLCHAIN_ROOT/lib" -name crtbegin.o -exec dirname {} \;)"} \
            -DCLANG_EXECUTABLE="$CLANG_EXECUTABLE"

      cmake --build . -- ''${JOBS:+-j $JOBS} install
      find "$INSTALLROOT/share" -name '*-gdb.py' -exec mv {} "$INSTALLROOT/lib" \;

      # Modulefile
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --lib --cmake > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  AliEn-Runtime = stdenv.mkDerivation {
    name = "AliEn-Runtime";
    version = "v2-19-le";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      zlib
      AliEn-CAs
      UUID
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Xcode
      zlib
      AliEn-CAs
      UUID
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=AliEn-Runtime
      PKGVERSION=v2-19-le
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_REVISION=1
      
      export ALIEN_CAS_ROOT=${ AliEn-CAs.out }
      ALIEN_CAS_REVISION=1
      
      export UUID_ROOT=${ UUID.out }
      UUID_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export XCODE_ROOT=${ Xcode.out }
      XCODE_VERSION=${ Xcode.version }
      XCODE_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export ALIEN_CAS_ROOT=${ AliEn-CAs.out }
      ALIEN_CAS_VERSION=${ AliEn-CAs.version }
      ALIEN_CAS_REVISION=1
      
      export UUID_ROOT=${ UUID.out }
      UUID_VERSION=${ UUID.version }
      UUID_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      for RPKG in $BUILD_REQUIRES; do
        RPKG_UP=$(echo $RPKG|tr '[:lower:]' '[:upper:]'|tr '-' '_')
        RPKG_ROOT=$(eval echo "\$''${RPKG_UP}_ROOT")
        rsync -a $RPKG_ROOT/ $INSTALLROOT/
        pushd $INSTALLROOT/../../..
          env WORK_DIR=$PWD sh -e $INSTALLROOT/relocate-me.sh
        popd
        rm -f $INSTALLROOT/etc/modulefiles/{$RPKG,$RPKG.unrelocated} || true
      done

      rm -f $INSTALLROOT/lib/pkgconfig/zlib.pc

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > "$MODULEDIR/$PKGNAME"
      cat >> "$MODULEDIR/$PKGNAME" <<\EoF
      setenv X509_CERT_DIR $PKG_ROOT/globus/share/certificates
      EoF
      runHook postInstall
    '';
  };

  GSL = stdenv.mkDerivation {
    name = "GSL";
    version = "v2.8";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/v2.8";
    url="https://github.com/alisw/gsl";});

    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=GSL
      PKGVERSION=v2.8
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      rsync -a --chmod=ug=rwX --exclude .git --delete-excluded $SOURCEDIR/ $BUILDDIR/
      # Do not build documentation
      sed -i.bak -e "s/doc//" Makefile.am
      sed -i.bak -e "s|doc/Makefile||" configure.ac
      autoreconf -f -v -i
      ./configure --prefix="$INSTALLROOT" \
                  --enable-maintainer-mode
      make ''${JOBS:+-j$JOBS}
      make ''${JOBS:+-j$JOBS} install
      rm -fv $INSTALLROOT/lib/*.la
      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > $MODULEFILE
      runHook postInstall
    '';
  };

  XRootD = stdenv.mkDerivation {
    name = "XRootD";
    version = "v5.8.3";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/v5.8.3";
    url="https://github.com/xrootd/xrootd";});

    
    buildInputs = [
      UUID
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python-modules
      AliEn-Runtime
      zlib
      UUID
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=XRootD
      PKGVERSION=v5.8.3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export UUID_ROOT=${ UUID.out }
      UUID_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_MODULES_ROOT=${ Python-modules.out }
      PYTHON_MODULES_VERSION=${ Python-modules.version }
      PYTHON_MODULES_REVISION=1
      
      export ALIEN_RUNTIME_ROOT=${ AliEn-Runtime.out }
      ALIEN_RUNTIME_VERSION=${ AliEn-Runtime.version }
      ALIEN_RUNTIME_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export UUID_ROOT=${ UUID.out }
      UUID_VERSION=${ UUID.version }
      UUID_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      XROOTD_PYTHON=""
      [[ -e ''${SOURCEDIR}/bindings ]] && XROOTD_PYTHON=True;
      PYTHON_EXECUTABLE=$(/usr/bin/env python3 -c 'import sys; print(sys.executable)')
      PYTHON_VER=$( ''${PYTHON_EXECUTABLE} -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' )

      # Report versions of pip and setuptools
      echo "###################
      pip version:
      $(python3 -m pip -V)
      setuptools version:
      $(python3 -m pip show setuptools | grep 'Version\|Location')
      ###################"

      COMPILER_CC=cc
      COMPILER_CXX=c++
      COMPILER_LD=c++
      SONAME=so
      libuuid_soname=$SONAME

      case $ARCHITECTURE in
        osx_*)
          [[ $OPENSSL_ROOT ]] || OPENSSL_ROOT=$(brew --prefix openssl@3)
          # Find where ZLIB is defined
          [[ $ZLIB_ROOT ]] || ZLIB_ROOT="$(brew --prefix zlib)"
          [[ -d "$ZLIB_ROOT" ]] || unset ZLIB_ROOT
          # Python from Homebrew will have a hardcoded sysroot pointing to the
          # Xcode.app directory, which might not exist. This seems to be a robust
          # way to discover a working SDK path and present it to Python setuptools.
          # This fix is needed only on MacOS when building XRootD Python bindings.
          export CFLAGS="''${CFLAGS} -isysroot $(xcrun --show-sdk-path)"
          COMPILER_CC=clang
          COMPILER_CXX=clang++
          COMPILER_LD=clang
          SONAME=dylib
          libuuid_soname=a   # on Mac, no .dylib is produced
          ;;
      esac

      case $ARCHITECTURE in
        osx_x86-64) export ARCHFLAGS="-arch x86_64" ;;
        osx_arm64) CMAKE_FRAMEWORK_PATH=$(brew --prefix python)/Frameworks ;;
      esac

      cd $BUILDDIR
      cmake "''${SOURCEDIR}"                                                  \
            --log-level DEBUG                                               \
            ''${CMAKE_GENERATOR:+-G "$CMAKE_GENERATOR"}                       \
            -DCMAKE_CXX_COMPILER=$COMPILER_CXX                              \
            -DCMAKE_C_COMPILER=$COMPILER_CC                                 \
            -DCMAKE_LINKER=$COMPILER_LD                                     \
            -DCMAKE_INSTALL_PREFIX=''${INSTALLROOT}                           \
            ''${CMAKE_FRAMEWORK_PATH+-DCMAKE_FRAMEWORK_PATH=$CMAKE_FRAMEWORK_PATH} \
            -DCMAKE_INSTALL_LIBDIR=lib                                      \
            -DXRDCL_ONLY=ON                                                 \
            ''${UUID_ROOT:+-DUUID_LIBRARY="$UUID_ROOT/lib/libuuid.$libuuid_soname"} \
            ''${UUID_ROOT:+-DUUID_INCLUDE_DIR="$UUID_ROOT/include"}           \
            -DENABLE_KRB5=OFF                                               \
            -DENABLE_FUSE=OFF                                               \
            -DENABLE_VOMS=OFF                                               \
            -DENABLE_XRDCLHTTP=OFF                                          \
            -DENABLE_READLINE=OFF                                           \
            -DCMAKE_BUILD_TYPE=RelWithDebInfo                               \
            ''${OPENSSL_ROOT:+-DOPENSSL_ROOT_DIR=$OPENSSL_ROOT}               \
            ''${OPENSSL_ROOT:+-DOPENSSL_INCLUDE_DIRS=$OPENSSL_ROOT/include}   \
            ''${OPENSSL_ROOT:+-DOPENSSL_LIBRARIES=$OPENSSL_ROOT/lib/libssl.$SONAME;$OPENSSL_ROOT/lib/libcrypto.$SONAME} \
            ''${ZLIB_ROOT:+-DZLIB_ROOT=$ZLIB_ROOT}                            \
            ''${XROOTD_PYTHON:+-DENABLE_PYTHON=ON}                            \
            ''${XROOTD_PYTHON:+-DPython_EXECUTABLE=$PYTHON_EXECUTABLE}        \
            ''${XROOTD_PYTHON:+-DPIP_OPTIONS='--force-reinstall --ignore-installed --verbose'}   \
            -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-Wno-error"

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      if [[ x"$XROOTD_PYTHON" == x"True" ]]; then
          pushd ''${INSTALLROOT}

          # there are cases where python bindings are installed as relative to INSTALLROOT
          if [[ -d local/lib64 ]]; then
              [[ -d local/lib64/python''${PYTHON_VER} ]] && mv -f local/lib64/python''${PYTHON_VER} lib/
          fi
          if [[ -d local/lib ]]; then
              [[ -d local/lib/python''${PYTHON_VER} ]] && mv -f local/lib/python''${PYTHON_VER} lib/
          fi

          pushd lib
          if [ -d ../lib64/python''${PYTHON_VER} ]; then
            ln -s ../lib64/python''${PYTHON_VER} python
          elif [[ -d python''${PYTHON_VER} ]]; then
            ln -s python''${PYTHON_VER} python
          fi
          [[ ! -e python ]] && echo "NO PYTHON SYMLINK CREATED in: $(pwd -P)"
          popd  # get back from lib

          popd  # get back from INSTALLROOT

        case $ARCHITECTURE in
            osx*)
              find $INSTALLROOT/lib/python/ -name "*.so" -exec install_name_tool -add_rpath ''${INSTALLROOT}/lib {} \;
              find $INSTALLROOT/lib/ -name "*.dylib" -exec install_name_tool -add_rpath ''${INSTALLROOT}/lib {} \;
            ;;
        esac

          # Print found XRootD python bindings
          # just run the the command as this is under "bash -e"
          echo -ne ">>>>>>   Found XRootD python bindings: "
          LD_LIBRARY_PATH="$INSTALLROOT/lib''${LD_LIBRARY_PATH:+:}$LD_LIBRARY_PATH" PYTHONPATH="$INSTALLROOT/lib/python/site-packages''${PYTHONPATH:+:}$PYTHONPATH" ''${PYTHON_EXECUTABLE} -c 'from XRootD import client as xrd_client;print(f"{xrd_client.__version__}\n{xrd_client.__file__}");'
          echo

      fi  # end of PYTHON part

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"

      alibuild-generate-module --bin --lib --cmake > "$MODULEFILE"

      case $ARCHITECTURE in
        slc[78]*) OPTIONAL_ENV= ;;
        *) OPTIONAL_ENV="" ;;
      esac

      cat >> "$MODULEFILE" <<EoF
      setenv ''${OPTIONAL_ENV}XRD_CONNECTIONWINDOW 3
      setenv ''${OPTIONAL_ENV}XRD_CONNECTIONRETRY 1
      setenv ''${OPTIONAL_ENV}XRD_TIMEOUTRESOLUTION 1
      setenv ''${OPTIONAL_ENV}XRD_REQUESTTIMEOUT 150

      if { $XROOTD_PYTHON } {
        prepend-path PYTHONPATH \$PKG_ROOT/lib/python/site-packages
        # This is probably redundant, but should not harm.
        module load ''${PYTHON_REVISION:+Python/$PYTHON_VERSION-$PYTHON_REVISION}                                 \\
                    ''${PYTHON_MODULES_REVISION:+Python-modules/$PYTHON_MODULES_VERSION-$PYTHON_MODULES_REVISION}
      }
      EoF
      runHook postInstall
    '';
  };

  TBB = stdenv.mkDerivation {
    name = "TBB";
    version = "v2021.5.0";
    
    
    src=(builtins.fetchGit {
    rev="3df08fe234f23e732a122809b40eb129ae22733f";
    url="https://github.com/uxlfoundation/oneTBB";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=TBB
      PKGVERSION=v2021.5.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      cmake $SOURCEDIR -DCMAKE_INSTALL_PREFIX=$INSTALLROOT   \
                ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}      \
                -DCMAKE_INSTALL_LIBDIR=lib -DTBB_TEST=OFF

      # Build and install
      cmake --build . -- ''${JOBS:+-j$JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > $MODULEFILE
      cat >> "$MODULEFILE" <<EOF
      # extra environment
      set TBB_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path ROOT_INCLUDE_PATH \$TBB_ROOT/include
      EOF
      runHook postInstall
    '';
  };

  protobuf = stdenv.mkDerivation {
    name = "protobuf";
    version = "v29.3";
    
    
    src=(builtins.fetchGit {
    rev="85425fce61be6ce0d7ac6f2a154fef7de2e684f3";
    url="https://github.com/protocolbuffers/protobuf";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      abseil
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      abseil
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=protobuf
      PKGVERSION=v29.3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_VERSION=${ abseil.version }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      if [ -f $SOURCEDIR/cmake/CMakeLists.txt ]; then
        ALIBUILD_CMAKE_SOURCE_DIR=$SOURCEDIR/cmake
      else
        ALIBUILD_CMAKE_SOURCE_DIR=$SOURCEDIR
      fi
      cmake -S "$ALIBUILD_CMAKE_SOURCE_DIR"                  \
          -DCMAKE_INSTALL_PREFIX="$INSTALLROOT" \
          -Dprotobuf_BUILD_TESTS=NO             \
          -Dprotobuf_MODULE_COMPATIBLE=YES      \
          -Dprotobuf_BUILD_SHARED_LIBS=OFF      \
          -Dprotobuf_ABSL_PROVIDER=package      \
          -DABSL_ROOT_DIR=$ABSEIL_ROOT          \
          -DCMAKE_INSTALL_LIBDIR=lib

      cmake --build . -- ''${JOBS:+-j$JOBS} install
      sed -i.bak 's|absl/log/absl_log.h|absl/log/vlog_is_on.h|' $INSTALLROOT/include/google/protobuf/io/coded_stream.h
      rm $INSTALLROOT/include/google/protobuf/io/coded_stream.h.bak

      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin --lib > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  FFTW3 = stdenv.mkDerivation {
    name = "FFTW3";
    version = "v3.3.9";
    
    
    src=(builtins.fetchGit {
    rev="2609f490804a8b606bbcb21e4ce3ac33c8074ea1";
    url="https://github.com/alisw/fftw3";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=FFTW3
      PKGVERSION=v3.3.9
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      # ROOT and O2 need different variants of fftw3, but we cannot configure fftw3
      # to build both at the same time. As a workaround, configure and build one,
      # then wipe out the build directory and configure and build the second one.

      # First, build fftw3 (double precision), required by ROOT.
      cmake -S "$SOURCEDIR" -B "$BUILDDIR/fftw3"              \
            -DCMAKE_INSTALL_PREFIX:PATH="$INSTALLROOT"        \
            -DCMAKE_INSTALL_LIBDIR:PATH=lib
      make -C "$BUILDDIR/fftw3" ''${JOBS+-j "$JOBS"}
      make -C "$BUILDDIR/fftw3" install

      # Now reconfigure for fftw3f (single precision float), required by O2.
      cmake -S "$SOURCEDIR" -B "$BUILDDIR/fftw3f"             \
            -DCMAKE_INSTALL_PREFIX:PATH="$INSTALLROOT"        \
            -DCMAKE_INSTALL_LIBDIR:PATH=lib                   \
            -DENABLE_FLOAT=ON
      make -C "$BUILDDIR/fftw3f" ''${JOBS+-j "$JOBS"}
      make -C "$BUILDDIR/fftw3f" install

      #Modulefile
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin --lib > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  Vc = stdenv.mkDerivation {
    name = "Vc";
    version = "1.4.5";
    
    
    src=(builtins.fetchGit {
    rev="e0d229154cc7e5d5c766b333936b18040264a2e0";
    url="https://github.com/VcDevel/Vc.git";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Vc
      PKGVERSION=1.4.5
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      cmake $SOURCEDIR -G Ninja -DCMAKE_INSTALL_PREFIX=$INSTALLROOT -DBUILD_TESTING=OFF

      cmake --build . --target install ''${JOBS+-j $JOBS}

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib --cmake > $MODULEFILE
      cat >> "$MODULEFILE" <<EoF		
      prepend-path ROOT_INCLUDE_PATH \$PKG_ROOT/include		
      EoF
      runHook postInstall
    '';
  };

  pythia = stdenv.mkDerivation {
    name = "pythia";
    version = "v8315-alice1";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/v8315-alice1";
    url="https://github.com/alisw/pythia8.git";});

    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      lhapdf
      HepMC
      boost
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=pythia
      PKGVERSION=v8315-alice1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export LHAPDF_ROOT=${ lhapdf.out }
      LHAPDF_VERSION=${ lhapdf.version }
      LHAPDF_REVISION=1
      
      export HEPMC_ROOT=${ HepMC.out }
      HEPMC_VERSION=${ HepMC.version }
      HEPMC_REVISION=1
      
      export BOOST_ROOT=${ boost.out }
      BOOST_VERSION=${ boost.version }
      BOOST_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      rsync -a --chmod=ug=rwX --delete --exclude '**/.git' --delete-excluded $SOURCEDIR/ ./
      case $ARCHITECTURE in
        osx*)
          # If we preferred system tools, we need to make sure we can pick them up.
          [[ ! $BOOST_ROOT ]] && BOOST_ROOT=`brew --prefix boost`
        ;;
      esac

      ./configure --prefix=$INSTALLROOT \
                  --enable-shared \
                  ''${HEPMC_ROOT:+--with-hepmc2="$HEPMC_ROOT"} \
                  ''${LHAPDF_ROOT:+--with-lhapdf6="$LHAPDF_ROOT"} \
                  ''${BOOST_ROOT:+--with-boost="$BOOST_ROOT"}

      if [[ $ARCHITECTURE =~ "slc5.*" ]]; then
          ln -s LHAPDF5.h include/Pythia8Plugins/LHAPDF5.cc
          ln -s LHAPDF6.h include/Pythia8Plugins/LHAPDF6.cc
          sed -i -e 's#\$(CXX) -x c++ \$< -o \$@ -c -MD -w -I\$(LHAPDF\$\*_INCLUDE) \$(CXX_COMMON)#\$(CXX) -x c++ \$(<:.h=.cc) -o \$@ -c -MD -w -I\$(LHAPDF\$\*_INCLUDE) \$(CXX_COMMON)#' Makefile
      fi

      make ''${JOBS+-j $JOBS}
      make install
      chmod a+x $INSTALLROOT/bin/pythia8-config

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${LHAPDF_REVISION:+lhapdf/$LHAPDF_VERSION-$LHAPDF_REVISION} ''${BOOST_REVISION:+boost/$BOOST_VERSION-$BOOST_REVISION} ''${HEPMC_REVISION:+HepMC/$HEPMC_VERSION-$HEPMC_REVISION}
      # Our environment
      set PYTHIA_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv PYTHIA_ROOT \$PYTHIA_ROOT
      setenv PYTHIA8DATA \$PYTHIA_ROOT/share/Pythia8/xmldoc
      setenv PYTHIA8 \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path PATH \$PYTHIA_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$PYTHIA_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$PYTHIA_ROOT/include
      EoF
      runHook postInstall
    '';
  };

  Xcode = stdenv.mkDerivation {
    name = "Xcode";
    version = "2409";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Xcode
      PKGVERSION=2409
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      exit 0
      runHook postInstall
    '';
  };

  zlib = stdenv.mkDerivation {
    name = "zlib";
    version = "v1.3.1";
    
    
    src=(builtins.fetchGit {
    rev="925af44f3cde53c6b076611c297850091b5dc7bb";
    url="https://github.com/madler/zlib";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=zlib
      PKGVERSION=v1.3.1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      rsync -a --chmod=ug=rwX --delete --exclude '**/.git' --delete-excluded $SOURCEDIR/ ./

      ./configure --prefix="$INSTALLROOT"

      make ''${JOBS+-j $JOBS}
      make install
      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib > "$MODULEFILE"
      runHook postInstall
    '';
  };

  Clang = stdenv.mkDerivation {
    name = "Clang";
    version = "v18.1.8";
    
    
    src=(builtins.fetchGit {
    rev="7f97f9dbe9cd3a27df753ed034e24941b1423a58";
    url="https://github.com/alisw/llvm-project-reduced";});

    
    
    
    buildInputs = [
      Python
      curl
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python
      curl
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=Clang
      PKGVERSION=v18.1.8
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_REVISION=1
      
      export CURL_ROOT=${ curl.out }
      CURL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export CURL_ROOT=${ curl.out }
      CURL_VERSION=${ curl.version }
      CURL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      # Unsetting default compiler flags in order to make sure that no debug
      # information is compiled into the objects which make the build artifacts very
      # big.
      unset CXXFLAGS
      unset CFLAGS
      unset LDFLAGS

      case $ARCHITECTURE in
        # Needed to have the C headers
        osx_*) DEFAULT_SYSROOT=$(xcrun --show-sdk-path) ;;
        *) DEFAULT_SYSROOT= ;;
      esac
      case $ARCHITECTURE in
        *_x86-64) LLVM_TARGETS_TO_BUILD=X86 ;;
        *_arm64) LLVM_TARGETS_TO_BUILD=AArch64 ;;
        *_aarch64) LLVM_TARGETS_TO_BUILD=AArch64 ;;
        *) echo 'Unknown LLVM target for architecture' >&2; exit 1 ;;
      esac

      # BUILD_SHARED_LIBS=ON is needed for e.g. adding dynamic plugins to clang-tidy.
      # Apache Arrow needs LLVM_ENABLE_RTTI=ON.
      cmake "$SOURCEDIR/llvm" \
        -G Ninja \
        -DLLVM_ENABLE_PROJECTS='clang;clang-tools-extra;compiler-rt' \
        -DLLVM_ENABLE_RUNTIMES='libcxx;libcxxabi' \
        -DLLVM_TARGETS_TO_BUILD="''${LLVM_TARGETS_TO_BUILD:?}" \
        -DCMAKE_BUILD_TYPE=Release \
        ''${COMPILER_RT_OSX_ARCHS:+-DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON} \
        ''${COMPILER_RT_OSX_ARCHS:+-DCOMPILER_RT_OSX_ARCHS=''${COMPILER_RT_OSX_ARCHS}} \
        -DCMAKE_INSTALL_PREFIX:PATH="$INSTALLROOT" \
        -DLLVM_INSTALL_UTILS=ON \
        -DPYTHON_EXECUTABLE="$(which python3)" \
        -DDEFAULT_SYSROOT="$DEFAULT_SYSROOT" \
        -DLLVM_BUILD_LLVM_DYLIB=ON \
        -DLLVM_ENABLE_RTTI=ON \
        -DBUILD_SHARED_LIBS=OFF \
        -DLIBCXXABI_USE_LLVM_UNWINDER=OFF \
        ''${GCC_TOOLCHAIN_ROOT:+-DGCC_INSTALL_PREFIX=$GCC_TOOLCHAIN_ROOT}

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      if [[ $PKGVERSION == v18.1.* ]]; then
        SPIRV_TRANSLATOR_VERSION="v18.1.3"
      else
        SPIRV_TRANSLATOR_VERSION="''${PKGVERSION%%.*}.0.0"
      fi
      git clone -b "$SPIRV_TRANSLATOR_VERSION" https://github.com/KhronosGroup/SPIRV-LLVM-Translator
      mkdir SPIRV-LLVM-Translator/build
      pushd SPIRV-LLVM-Translator/build
      cmake ../ \
        -G Ninja \
        -DLLVM_DIR="$INSTALLROOT/lib/cmake/llvm" \
        -DLLVM_BUILD_TOOLS=ON \
        -DLLVM_INCLUDE_TESTS=OFF \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX:PATH="$INSTALLROOT"
      cmake --build . -- ''${JOBS:+-j$JOBS} install
      popd

      case $ARCHITECTURE in
        osx*)
          # Add correct rpath to dylibs on Mac as long as there is no better way to
          # control rpath in the LLVM CMake.
          # Add rpath to all libraries in lib and change their IDs to be absolute paths.
          find "$INSTALLROOT/lib" -name '*.dylib' -not -name '*ios*.dylib' \
               -exec install_name_tool -add_rpath "$INSTALLROOT/lib" '{}' \; \
               -exec install_name_tool -id '{}' '{}' \;
          # In lib/clang/*/lib/darwin, the relative rpath is wrong and needs to be
          # corrected from "@loader_path/../lib" to "@loader_path/../darwin".
          find "$INSTALLROOT"/lib/clang/*/lib/darwin -name '*.dylib' -not -name '*ios*.dylib' \
               -exec install_name_tool -rpath '@loader_path/../lib' '@loader_path/../darwin' '{}' \;

          # Needed to be able to find C++ headers.
          ln -sf "$(xcrun --show-sdk-path)/usr/include/c++" "$INSTALLROOT/include/c++" ;;
      esac

      # We do not want to have the clang executables in path
      # to avoid issues with system clang on macOS.
      # We **MUST NOT** add bin-safe to the build path. Runtime
      # path is fine.
      mkdir "$INSTALLROOT/bin-safe"
      mv "$INSTALLROOT"/bin/clang* "$INSTALLROOT/bin-safe/"
      mv "$INSTALLROOT"/bin/llvm-spirv* "$INSTALLROOT/bin-safe/" # Install llvm-spirv tool
      mv "$INSTALLROOT"/bin/git-clang* "$INSTALLROOT/bin-safe/"  # we also need git-clang-format in runtime
      sed -i.bak -e "s|bin/clang|bin-safe/clang|g" "$INSTALLROOT/lib/cmake/clang/ClangTargets-release.cmake"
      rm "$INSTALLROOT"/lib/cmake/clang/*.bak

      # Check it actually works
      cat << \EOF > test.cc
      #include <iostream>
      EOF
      "$INSTALLROOT/bin-safe/clang++" -v -c test.cc

      # Modulefile
      mkdir -p etc/modulefiles
      cat > "etc/modulefiles/$PKGNAME" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0                                                          \\
                  ''${GCC_TOOLCHAIN_REVISION:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION}
      # Our environment
      set CLANG_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path PATH \$CLANG_ROOT/bin-safe
      prepend-path LD_LIBRARY_PATH \$CLANG_ROOT/lib
      EoF
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      rsync -a --delete etc/modulefiles/ "$INSTALLROOT/etc/modulefiles"
      runHook postInstall
    '';
  };

  utf8proc = stdenv.mkDerivation {
    name = "utf8proc";
    version = "v2.6.1";
    
    
    src=(builtins.fetchGit {
    rev="3203baa7374d67132384e2830b2183c92351bffc";
    url="https://github.com/JuliaStrings/utf8proc";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=utf8proc
      PKGVERSION=v2.6.1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      cmake $SOURCEDIR -DCMAKE_INSTALL_PREFIX=$INSTALLROOT -DBUILD_SHARED_LIBS=ON
      make ''${JOBS+-j $JOBS} install

      mkdir -p etc/modulefiles
      alibuild-generate-module --lib > etc/modulefiles/$PKGNAME
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  xsimd = stdenv.mkDerivation {
    name = "xsimd";
    version = "8.1.0";
    
    
    src=(builtins.fetchGit {
    rev="e4e715e9a83ff85b8dbad6fd1cda0ba200e77334";
    url="https://github.com/xtensor-stack/xsimd";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=xsimd
      PKGVERSION=8.1.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      mkdir -p $INSTALLROOT
      cd $BUILDDIR

      cmake $SOURCEDIR                                                                                 \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT

      make ''${JOBS:+-j $JOBS}
      make install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module > "$MODULEFILE"
      cat >> "$MODULEFILE" <<EoF

      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Our environment
      set XSIMD_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path LD_LIBRARY_PATH \$XSIMD_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  flatbuffers = stdenv.mkDerivation {
    name = "flatbuffers";
    version = "v24.3.25";
    
    
    src=(builtins.fetchGit {
    rev="334ffbbe337d53d9235a08f071af0ea329dcf14a";
    url="https://github.com/google/flatbuffers";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      zlib
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=flatbuffers
      PKGVERSION=v24.3.25
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      cmake "$SOURCEDIR"                                                                                                      \
            -G 'Ninja'                                                                                                        \
            -DFLATBUFFERS_BUILD_TESTS=OFF                                                                                     \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                                                                          

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      # Modulefile
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin --lib --cmake > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  RapidJSON = stdenv.mkDerivation {
    name = "RapidJSON";
    version = "v1.1.0-alice2";
    
    
    
    src=(builtins.fetchGit {
    rev="091de040edb3355dcf2f4a18c425aec51b906f08";
    url="https://github.com/Tencent/rapidjson.git";});

    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=RapidJSON
      PKGVERSION=v1.1.0-alice2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      cmake $SOURCEDIR                                                       \
            -G Ninja                                                         \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT                              \
            -DCMAKE_POLICY_DEFAULT_CMP0077=NEW                               \
            -DRAPIDJSON_BUILD_TESTS=OFF                                      \
            -DRAPIDJSON_BUILD_EXAMPLES=OFF

      ninja ''${JOBS:+-j$JOBS} install

      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib --cmake > $MODULEFILE
      cat << EOF >> $MODULEFILE
      prepend-path ROOT_INCLUDE_PATH \$PKG_ROOT/include
      EOF
      runHook postInstall
    '';
  };

  double-conversion = stdenv.mkDerivation {
    name = "double-conversion";
    version = "v3.1.5";
    
    
    src=(builtins.fetchGit {
    rev="5fa81e88ef24e735b4283b8f7454dc59693ac1fc";
    url="https://github.com/google/double-conversion";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=double-conversion
      PKGVERSION=v3.1.5
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      mkdir -p $INSTALLROOT

      # Downloaded by CMake, built, and linked statically (not needed at runtime):
      #   zlib, lz4, brotli
      #
      # Taken from our stack, linked statically (not needed at runtime):
      #   flatbuffers
      #
      # Taken from our stack, linked dynamically (needed at runtime):
      #   boost

      cmake $SOURCEDIR                          \
            -DBUILD_TESTING=OFF                 \
            -DBUILD_SHARED_LIBS=OFF             \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT

      make ''${JOBS:+-j $JOBS} install

      # Trivial module file to keep the linter happy.
      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0
      # Our environment
      EoF
      runHook postInstall
    '';
  };

  re2 = stdenv.mkDerivation {
    name = "re2";
    version = "2024-07-02";
    
    
    src=(builtins.fetchGit {
    rev="cf8f19116192016936b306b033f9860cff6f0b5c";
    url="https://github.com/google/re2";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      abseil
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      abseil
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=re2
      PKGVERSION=2024-07-02
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_VERSION=${ abseil.version }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/sh
      cmake $SOURCEDIR                           \
            -G Ninja                             \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT  \
            -DCMAKE_INSTALL_LIBDIR=lib

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib > "$MODULEFILE"
      runHook postInstall
    '';
  };

  AliEn-CAs = stdenv.mkDerivation {
    name = "AliEn-CAs";
    version = "v1";
    
    
    
    src=(builtins.fetchGit {
    rev="5fac97c4132df4bba9434a40a3f214401def20fa";
    url="https://github.com/alisw/alien-cas.git";});

    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=AliEn-CAs
      PKGVERSION=v1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      DEST="$INSTALLROOT/globus/share/certificates"
      mkdir -p "$DEST"
      # Make sure we ignore .git and other hidden repositories when doing the find
      find "$SOURCEDIR" -not -path '*/[@.]*' -type d -maxdepth 1 -mindepth 1 -exec rsync -av {}/ "$DEST" \;

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module > "$MODULEFILE"
      cat >> "$MODULEFILE" <<EOF
      setenv X509_CERT_DIR \$::env(BASEDIR)/AliEn-CAs/\$version/globus/share/certificates
      EOF
      runHook postInstall
    '';
  };

  UUID = stdenv.mkDerivation {
    name = "UUID";
    version = "v2.27.1";
    
    
    src=(builtins.fetchGit {
    rev="a24d32e00da30c78ace5a0786d8c1777f2636a61";
    url="https://github.com/alisw/uuid";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=UUID
      PKGVERSION=v2.27.1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      rsync --no-specials --no-devices --chmod=ug=rwX -av --delete --exclude .git/ --delete-excluded "$SOURCEDIR/" .
      if [[ $AUTOTOOLS_ROOT == "" ]]  && which brew >/dev/null; then
        PATH=$PATH:$(brew --prefix gettext)/bin
      fi

      perl -p -i -e 's/AM_GNU_GETTEXT_VERSION\(\[0\.18\.3\]\)/AM_GNU_GETTEXT_VERSION([0.18.2])/' configure.ac

      case $ARCHITECTURE in
        osx_*) disable_shared=yes ;;
        *) disable_shared= ;;
      esac

      # Avoid building docs
      GTKDOCIZE=echo autoreconf -ivf
      # --disable-nls so we don't depend on gettext/libintl at runtime on Intel Macs.
      ./configure ''${disable_shared:+--disable-shared}   \
                  "--libdir=$INSTALLROOT/lib"           \
                  "--prefix=$INSTALLROOT"               \
                  --disable-all-programs                \
                  --disable-silent-rules                \
                  --disable-tls                         \
                  --disable-nls                         \
                  --disable-rpath                       \
                  --without-ncurses                     \
                  --enable-libuuid
      make ''${JOBS:+-j$JOBS} libuuid.la libuuid/uuid.pc install-uuidincHEADERS
      mkdir -p "$INSTALLROOT/lib" "$INSTALLROOT/share/pkgconfig"
      cp -a libuuid/uuid.pc "$INSTALLROOT/share/pkgconfig"
      cp -a .libs/libuuid.a* "$INSTALLROOT/lib"
      if [ -z "$disable_shared" ]; then
        cp -a .libs/libuuid.so* "$INSTALLROOT/lib"
      fi
      rm -rf "$INSTALLROOT/man"
      runHook postInstall
    '';
  };

  abseil = stdenv.mkDerivation {
    name = "abseil";
    version = "20240722.0";
    
    
    src=(builtins.fetchGit {
    rev="4447c7562e3bc702ade25105912dce503f0c4010";
    url="https://github.com/abseil/abseil-cpp";});

    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=abseil
      PKGVERSION=20240722.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      mkdir -p $INSTALLROOT
      cmake $SOURCEDIR                             \
        -G Ninja                                   \
        ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}    \
        -DCMAKE_INSTALL_LIBDIR=lib                 \
        -DBUILD_TESTING=OFF                        \
        -DCMAKE_INSTALL_PREFIX=$INSTALLROOT

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib --bin --cmake > "$MODULEFILE"
      runHook postInstall
    '';
  };

  lhapdf = stdenv.mkDerivation {
    name = "lhapdf";
    version = "v6.5.2";
    
    
    src=(builtins.fetchGit {
    rev="4f3b63aa75fbe40850659cd63eb2c5bd69e4b10a";
    url="https://github.com/alisw/LHAPDF";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=lhapdf
      PKGVERSION=v6.5.2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -ex
      case $ARCHITECTURE in
        osx*)
          # If we preferred system tools, we need to make sure we can pick them up.
          [[ ! $AUTOTOOLS_ROOT ]] && PATH=$PATH:`brew --prefix gettext`/bin
          # Do not compile Python2 bindings on Mac
          DISABLE_PYTHON=1
        ;;
        *)
          EXTRA_LD_FLAGS="-Wl,--no-as-needed"
        ;;
      esac

      rsync -a --chmod=ug=rwX --exclude '**/.git' $SOURCEDIR/ ./

      export LIBRARY_PATH="$LD_LIBRARY_PATH"

      if type "python" &>/dev/null; then
        # Python2 or Python3 point to "python"
        if python -c 'import sys; exit(0 if sys.version_info.major >=3 else 1)'; then
          # LHAPDF not yet ready for Python3
          DISABLE_PYTHON=1
        fi
      else
        # Python2 not installed and Python3 points to "python3"
        DISABLE_PYTHON=1
      fi

      autoreconf -ivf
      ./configure --prefix=$INSTALLROOT ''${DISABLE_PYTHON:+--disable-python}

      make ''${JOBS+-j $JOBS} all
      make install

      pushd "$INSTALLROOT"
        # Fix ambiguity between lib/lib64
        if [[ ! -d lib && -d lib64 ]]; then
          ln -nfs lib64 lib
        elif [[ -d lib && ! -d lib64 ]]; then
          ln -nfs lib lib64
        fi
        # Uniform Python library path
        pushd lib
          find $PWD -name "python3*" -exec ln -nfs {} python \;
        popd
      popd

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${GCC_TOOLCHAIN_REVISION:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION} \\
                           ''${PYTHON_MODULES_ROOT:+Python-modules/$PYTHON_MODULES_VERSION-$PYTHON_MODULES_REVISION} 
      # Our environment
      set LHAPDF_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv LHAPDF_ROOT \$LHAPDF_ROOT
      prepend-path PATH \$LHAPDF_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$LHAPDF_ROOT/lib
      prepend-path PYTHONPATH \$LHAPDF_ROOT/lib/python/site-packages
      prepend-path LHAPDF_DATA_PATH \$LHAPDF_ROOT/share/LHAPDF
      EoF
      runHook postInstall
    '';
  };

  HepMC = stdenv.mkDerivation {
    name = "HepMC";
    version = "HEPMC_02_06_10";
    
    
    src=(builtins.fetchGit {
    rev="9ae8f429ab0977db46db1601e0984115a8c4e2ee";
    url="https://gitlab.cern.ch/hepmc/HepMC.git";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=HepMC
      PKGVERSION=HEPMC_02_06_10
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      cmake  $SOURCEDIR                           \
             -Dmomentum=GEV                       \
             -Dlength=MM                          \
             -Dbuild_docs:BOOL=OFF                \
             -DCMAKE_INSTALL_PREFIX=$INSTALLROOT

      make ''${JOBS+-j $JOBS}
      make install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      cat > "$MODULEFILE" <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ''${GCC_TOOLCHAIN_ROOT:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION}
      # Our environment
      set HEPMC_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv HEPMC_ROOT \$HEPMC_ROOT
      prepend-path PATH \$HEPMC_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$HEPMC_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

in
{
  inherit Rivet HepMC3 YODA fastjet cgal GMP Python Python-modules alibuild-recipe-tools defaults-release ROOT hdf5 boost MPFR curl Python-modules-list arrow AliEn-Runtime GSL XRootD TBB protobuf FFTW3 Vc pythia Xcode zlib Clang utf8proc xsimd flatbuffers RapidJSON double-conversion re2 AliEn-CAs UUID abseil lhapdf HepMC;
}
