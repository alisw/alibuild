{stdenv, pkgs, systemDeps}:
let
   properUnpack = ''
      runHook preUnpack;
      echo "foo"
      env
      runHook postUnpack;
   '';
   filterGit = what: pkgs.lib.cleanSourceWith { src=what; filter=path: type: !( (builtins.match ".git" path) != null || (builtins.match ".cache" path) != null); };

  AliPhysics = stdenv.mkDerivation {
    name = "AliPhysics";
    version = "0_O2";
    
    
    
    
    
    src=(filterGit /Users/ktf/src/AliPhysics);

    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      AliRoot
      RooUnfold
      treelite
      KFParticle
      boost
      ZeroMQ
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=AliPhysics
      PKGVERSION=0_O2
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
      
      
      export ALIROOT_ROOT=${ AliRoot.out }
      ALIROOT_VERSION=${ AliRoot.version }
      ALIROOT_REVISION=1
      
      export ROOUNFOLD_ROOT=${ RooUnfold.out }
      ROOUNFOLD_VERSION=${ RooUnfold.version }
      ROOUNFOLD_REVISION=1
      
      export TREELITE_ROOT=${ treelite.out }
      TREELITE_VERSION=${ treelite.version }
      TREELITE_REVISION=1
      
      export KFPARTICLE_ROOT=${ KFParticle.out }
      KFPARTICLE_VERSION=${ KFParticle.version }
      KFPARTICLE_REVISION=1
      
      export BOOST_ROOT=${ boost.out }
      BOOST_VERSION=${ boost.version }
      BOOST_REVISION=1
      
      export ZEROMQ_ROOT=${ ZeroMQ.out }
      ZEROMQ_VERSION=${ ZeroMQ.version }
      ZEROMQ_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      # Picking up ROOT from the system when ours is disabled
      [[ -z "$ROOT_ROOT" ]] && ROOT_ROOT="$(root-config --prefix)"

      # Uses the same setup as AliRoot
      if [[ $CMAKE_BUILD_TYPE == COVERAGE ]]; then
        source $ALIROOT_ROOT/etc/gcov-setup.sh
      fi

      # Use ninja if in devel mode, ninja is found and DISABLE_NINJA is not 1
      if [[ ! $CMAKE_GENERATOR && $DISABLE_NINJA != 1 && $DEVEL_SOURCES != $SOURCEDIR ]]; then
        NINJA_BIN=ninja-build
        type "$NINJA_BIN" &> /dev/null || NINJA_BIN=ninja
        type "$NINJA_BIN" &> /dev/null || NINJA_BIN=
        # AliPhysics contains Fortran code, which requires at least ninja v1.10
        # in order to build with ninja, otherwise the build must fall back to make
        NINJA_VERSION_MAJOR=0
        NINJA_VERSION_MINOR=0
        if [ "x$NINJA_BIN" != "x" ]; then
          NINJA_VERSION_MAJOR=$($NINJA_BIN --version | sed -e 's/.* //' | cut -d. -f1)
          NINJA_VERSION_MINOR=$($NINJA_BIN --version | sed -e 's/.* //' | cut -d. -f2)
        fi
        NINJA_VERSION=$(($NINJA_VERSION_MAJOR * 100 + $NINJA_VERSION_MINOR))
        [[ $NINJA_BIN && $NINJA_VERSION -ge 110 ]] && CMAKE_GENERATOR=Ninja || true
        unset NINJA_BIN
      fi

      cmake "$SOURCEDIR"                                                 \
            -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-Wno-error -g"             \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                        \
            -DCMAKE_EXPORT_COMPILE_COMMANDS=ON                           \
            -DROOTSYS="$ROOT_ROOT"                                       \
            ''${CMAKE_GENERATOR:+-G "$CMAKE_GENERATOR"}                    \
            ''${CMAKE_BUILD_TYPE:+-DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE"}  \
            ''${ALIEN_RUNTIME_ROOT:+-DALIEN="$ALIEN_RUNTIME_ROOT"}         \
            ''${FASTJET_ROOT:+-DFASTJET="$FASTJET_ROOT"}                   \
            ''${ROOUNFOLD_ROOT:+-DROOUNFOLD="$ROOUNFOLD_ROOT"}             \
            ''${CGAL_ROOT:+-DCGAL="$CGAL_ROOT"}                            \
            ''${MPFR_ROOT:+-DMPFR="$MPFR_ROOT"}                            \
            ''${GMP_ROOT:+-DGMP="$GMP_ROOT"}                               \
            ''${TREELITE_ROOT:+-DTREELITE_ROOT="$TREELITE_ROOT"}           \
            ''${ZEROMQ_ROOT:+-DZEROMQ="$ZEROMQ_ROOT"}                      \
            ''${BOOST_ROOT:+-DBOOST_ROOT="$BOOST_ROOT"}                    \
            -DALIROOT="$ALIROOT_ROOT"

      cmake --build . -- ''${IGNORE_ERRORS:+-k} ''${JOBS+-j $JOBS} install
      # ctest will succeed if no load_library tests were found
      ctest -R load_library --output-on-failure ''${JOBS:+-j $JOBS}

      # Copy the compile commands in the installation and source directory (only if devel mode!)
      cp -v compile_commands.json ''${INSTALLROOT}
      DEVEL_SOURCES="$(readlink "$SOURCEDIR" || echo "$SOURCEDIR")"
      if [[ $DEVEL_SOURCES != $SOURCEDIR ]]; then
        sed -i.deleteme -e "s|$SOURCEDIR|$DEVEL_SOURCES|" compile_commands.json
        rm -f compile_commands.json.deleteme
        ln -nfs "$BUILDDIR/compile_commands.json" "$DEVEL_SOURCES/compile_commands.json"
      fi

      [[ $CMAKE_BUILD_TYPE == COVERAGE ]]                                                       \
        && mkdir -p "$WORK_DIR/''${ARCHITECTURE}/profile-data/AliRoot/$ALIROOT_VERSION-$ALIROOT_REVISION/"  \
        && rsync -acv --filter='+ */' --filter='+ *.c' --filter='+ *.cxx' --filter='+ *.cpp' --filter='+ *.cc' --filter='+ *.hpp' --filter='+ *.h' --filter='+ *.gcno' --filter='- *' "$BUILDDIR/" "$WORK_DIR/''${ARCHITECTURE}/profile-data/AliRoot/$ALIROOT_VERSION-$ALIROOT_REVISION/"

      # Modulefile
      mkdir -p etc/modulefiles
      cat > etc/modulefiles/$PKGNAME <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 AliRoot/$ALIROOT_VERSION-$ALIROOT_REVISION ''${ROOUNFOLD_REVISION:+RooUnfold/$ROOUNFOLD_VERSION-$ROOUNFOLD_REVISION} ''${TREELITE_REVISION:+treelite/$TREELITE_VERSION-$TREELITE_REVISION} ''${KFPARTICLE_REVISION:+KFParticle/$KFPARTICLE_VERSION-$KFPARTICLE_REVISION} ''${JEMALLOC_REVISION:+jemalloc/$JEMALLOC_VERSION-$JEMALLOC_REVISION}
      # Our environment
      setenv ALIPHYSICS_VERSION \$version
      setenv ALIPHYSICS_RELEASE \$::env(ALIPHYSICS_VERSION)
      set ALICE_PHYSICS \$::env(BASEDIR)/$PKGNAME/\$::env(ALIPHYSICS_RELEASE)
      setenv ALICE_PHYSICS \$ALICE_PHYSICS
      prepend-path PATH \$ALICE_PHYSICS/bin
      prepend-path LD_LIBRARY_PATH \$ALICE_PHYSICS/lib
      prepend-path ROOT_INCLUDE_PATH \$ALICE_PHYSICS/include
      prepend-path ROOT_DYN_PATH \$ALICE_PHYSICS/lib
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  AliRoot = stdenv.mkDerivation {
    name = "AliRoot";
    version = "0_O2";
    
    
    
    
    
    src=(filterGit /Users/ktf/src/AliRoot);

    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      DPMJET
      fastjet
      GEANT3
      GEANT4_VMC
      Vc
      ZeroMQ
      JAliEn-ROOT
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=AliRoot
      PKGVERSION=0_O2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export DPMJET_ROOT=${ DPMJET.out }
      DPMJET_VERSION=${ DPMJET.version }
      DPMJET_REVISION=1
      
      export FASTJET_ROOT=${ fastjet.out }
      FASTJET_VERSION=${ fastjet.version }
      FASTJET_REVISION=1
      
      export GEANT3_ROOT=${ GEANT3.out }
      GEANT3_VERSION=${ GEANT3.version }
      GEANT3_REVISION=1
      
      export GEANT4_VMC_ROOT=${ GEANT4_VMC.out }
      GEANT4_VMC_VERSION=${ GEANT4_VMC.version }
      GEANT4_VMC_REVISION=1
      
      export VC_ROOT=${ Vc.out }
      VC_VERSION=${ Vc.version }
      VC_REVISION=1
      
      export ZEROMQ_ROOT=${ ZeroMQ.out }
      ZEROMQ_VERSION=${ ZeroMQ.version }
      ZEROMQ_REVISION=1
      
      export JALIEN_ROOT_ROOT=${ JAliEn-ROOT.out }
      JALIEN_ROOT_VERSION=${ JAliEn-ROOT.version }
      JALIEN_ROOT_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      # Picking up ROOT from the system when ours is disabled
      [[ -z "$ROOT_ROOT" ]] && ROOT_ROOT="$(root-config --prefix)"

      # If building DAQ utilities verify environment integrity
      [[ $ALICE_DAQ ]] && ( source /date/setup.sh )

      # Generates an environment file to be loaded in case we need code coverage
      if [[ $CMAKE_BUILD_TYPE == COVERAGE ]]; then
      mkdir -p $INSTALLROOT/etc
      cat << EOF > $INSTALLROOT/etc/gcov-setup.sh
      export GCOV_PREFIX=''${GCOV_PREFIX:-"$WORK_DIR/''${ARCHITECTURE}/profile-data/AliRoot/$PKGVERSION-$PKGREVISION"}
      export GCOV_PREFIX_STRIP=$(echo $INSTALLROOT | sed -e 's|/$||;s|^/||;s|//*|/|g;s|[^/]||g' | wc -c | sed -e 's/[^0-9]*//')
      EOF
      source $INSTALLROOT/etc/gcov-setup.sh
      fi

      FVERSION=`gfortran --version | grep -i fortran | sed -e 's/.* //' | cut -d. -f1`
      SPECIALFFLAGS=""
      if [ $FVERSION -ge 10 ]; then
         echo "Fortran version $FVERSION"
         SPECIALFFLAGS=1
      fi
      # Use ninja if in devel mode, ninja is found and DISABLE_NINJA is not 1
      if [[ ! $CMAKE_GENERATOR && $DISABLE_NINJA != 1 && $DEVEL_SOURCES != $SOURCEDIR ]]; then
        NINJA_BIN=ninja-build
        type "$NINJA_BIN" &> /dev/null || NINJA_BIN=ninja
        type "$NINJA_BIN" &> /dev/null || NINJA_BIN=
        # AliRoot contains Fortran code, which requires at least ninja v1.10
        # in order to build with ninja, otherwise the build must fall back to make
        NINJA_VERSION_MAJOR=0
        NINJA_VERSION_MINOR=0
        if [ "x$NINJA_BIN" != "x" ]; then
          NINJA_VERSION_MAJOR=$($NINJA_BIN --version | sed -e 's/.* //' | cut -d. -f1)
          NINJA_VERSION_MINOR=$($NINJA_BIN --version | sed -e 's/.* //' | cut -d. -f2)
        fi
        NINJA_VERSION=$(($NINJA_VERSION_MAJOR * 100 + $NINJA_VERSION_MINOR))
        [[ $NINJA_BIN && $NINJA_VERSION -ge 110 ]] && CMAKE_GENERATOR=Ninja || true
        unset NINJA_BIN
      fi

      cmake $SOURCEDIR                                                     \
            -DCMAKE_CXX_FLAGS_RELWITHDEBINFO="-Wno-error -g"               \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                          \
            -DCMAKE_EXPORT_COMPILE_COMMANDS=ON                             \
            -DCMAKE_Fortran_COMPILER=gfortran                              \
            -DROOTSYS="$ROOT_ROOT"                                         \
            ''${CMAKE_GENERATOR:+-G "$CMAKE_GENERATOR"}                      \
            ''${CMAKE_BUILD_TYPE:+-DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE"}    \
            ''${ALIEN_RUNTIME_ROOT:+-DALIEN="$ALIEN_RUNTIME_ROOT"}           \
            ''${JALIEN_ROOT_ROOT:+-DJALIEN_LIBS=$JALIEN_ROOT_ROOT}           \
            ''${ALIEN_ROOT_LEGACY_ROOT:+-DALIEN_LIBS=$ALIEN_ROOT_LEGACY_ROOT}\
            ''${FASTJET_ROOT:+-DFASTJET="$FASTJET_ROOT"}                     \
            ''${DPMJET_ROOT:+-DDPMJET="$DPMJET_ROOT"}                        \
            ''${ZEROMQ_ROOT:+-DZEROMQ=$ZEROMQ_ROOT}                          \
            ''${ALICE_DAQ:+-DDA=ON -DDARPM=ON -DdaqDA=$DAQ_DALIB}            \
            ''${ALICE_DAQ:+-DAMORE_CONFIG=$AMORE_CONFIG}                     \
            ''${ALICE_DAQ:+-DDATE_CONFIG=$DATE_CONFIG}                       \
            ''${ALICE_DAQ:+-DDATE_ENV=$DATE_ENV}                             \
            ''${ALICE_DAQ:+-DDIMDIR=$DAQ_DIM -DODIR=linux}                   \
            ''${ALICE_SHUTTLE:+-DDIMDIR=$HOME/dim -DODIR=linux}              \
            ''${ALICE_SHUTTLE:+-DSHUTTLE=ON -DApMon=$ALIEN_RUNTIME_ROOT}     \
            -DOCDB_INSTALL=PLACEHOLDER                                     \
            ''${SPECIALFFLAGS:+-DCMAKE_Fortran_FLAGS="-fallow-argument-mismatch"}

      cmake --build . -- ''${IGNORE_ERRORS:+-k} ''${JOBS+-j $JOBS} install
      # ctest will succeed if no load_library tests were found
      ctest -R load_library --output-on-failure ''${JOBS:+-j $JOBS}
      [[ $ALICE_DAQ && ! $ALICE_DISABLE_DA_RPMS ]] && { make daqDA-all-rpm && make ''${JOBS+-j $JOBS} install; }

      # Copy the compile commands in the installation and source directory (only if devel mode!)
      cp -v compile_commands.json ''${INSTALLROOT}
      DEVEL_SOURCES="$(readlink "$SOURCEDIR" || echo "$SOURCEDIR")"
      if [[ $DEVEL_SOURCES != $SOURCEDIR ]]; then
        sed -i.deleteme -e "s|$SOURCEDIR|$DEVEL_SOURCES|" compile_commands.json
        rm -f compile_commands.json.deleteme
        ln -nfs "$BUILDDIR/compile_commands.json" "$DEVEL_SOURCES/compile_commands.json"
      fi

      rsync -av $SOURCEDIR/test/ $INSTALLROOT/test

      [[ $CMAKE_BUILD_TYPE == COVERAGE ]]                                                       \
        && mkdir -p "$WORK_DIR/''${ARCHITECTURE}/profile-data/AliRoot/$PKGVERSION-$PKGREVISION/"  \
        && rsync -acv --filter='+ */' --filter='+ *.c' --filter='+ *.cxx' --filter='+ *.cpp' --filter='+ *.cc' --filter='+ *.hpp' --filter='+ *.h' --filter='+ *.gcno' --filter='- *' "$BUILDDIR/" "$WORK_DIR/''${ARCHITECTURE}/profile-data/AliRoot/$PKGVERSION-$PKGREVISION/"

      # Modulefile
      mkdir -p etc/modulefiles
      cat > etc/modulefiles/$PKGNAME <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0                                                                                                \\
                  ''${ROOT_REVISION:+ROOT/$ROOT_VERSION-$ROOT_REVISION}                                                     \\
                  ''${DPMJET_REVISION:+DPMJET/$DPMJET_VERSION-$DPMJET_REVISION}                                             \\
                  ''${FASTJET_REVISION:+fastjet/$FASTJET_VERSION-$FASTJET_REVISION}                                         \\
                  ''${GEANT3_REVISION:+GEANT3/$GEANT3_VERSION-$GEANT3_REVISION}                                             \\
                  ''${ZEROMQ_REVISION:+ZeroMQ/$ZEROMQ_VERSION-$ZEROMQ_REVISION}                                             \\
                  ''${GEANT4_VMC_REVISION:+GEANT4_VMC/$GEANT4_VMC_VERSION-$GEANT4_VMC_REVISION}                             \\
                  ''${VC_REVISION:+Vc/$VC_VERSION-$VC_REVISION}                                                             \\
                  ''${JALIEN_ROOT_REVISION:+JAliEn-ROOT/$JALIEN_ROOT_VERSION-$JALIEN_ROOT_REVISION}                         \\
                  ''${ALIEN_ROOT_LEGACY_REVISION:+AliEn-ROOT-Legacy/$ALIEN_ROOT_LEGACY_VERSION-$ALIEN_ROOT_LEGACY_REVISION}
      # Our environment
      set ALIROOT_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv ALIROOT_VERSION \$version
      setenv ALICE \$::env(BASEDIR)/$PKGNAME
      setenv ALIROOT_RELEASE \$::env(ALIROOT_VERSION)
      set ALICE_ROOT \$::env(BASEDIR)/$PKGNAME/\$::env(ALIROOT_RELEASE)
      setenv ALICE_ROOT \$ALICE_ROOT
      prepend-path PATH \$ALICE_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$ALICE_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$ALICE_ROOT/include
      prepend-path ROOT_INCLUDE_PATH \$ALICE_ROOT/include/Pythia8
      prepend-path ROOT_DYN_PATH \$ALICE_ROOT/lib
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  RooUnfold = stdenv.mkDerivation {
    name = "RooUnfold";
    version = "V02-00-01-alice6";
    
    
    src=(builtins.fetchGit {
    rev="4f3ca16a52ede762a5eb20a5d8990602f0ecf7a1";
    url="https://github.com/alisw/RooUnfold";});

    
    
    
    buildInputs = [
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      boost
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=RooUnfold
      PKGVERSION=V02-00-01-alice6
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
      
      export BOOST_ROOT=${ boost.out }
      BOOST_VERSION=${ boost.version }
      BOOST_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      cmake $SOURCEDIR                              \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT     \
            ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD} \
            ''${CMAKE_BUILD_TYPE:+-DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE"}    \
            -DROOT_DIR=$ROOT_ROOT \
            -DCMAKE_INSTALL_LIBDIR=lib
      make ''${JOBS:+-j$JOBS} install
      #make test

      rsync -av $SOURCEDIR/include/ $INSTALLROOT/include/
      # Modulefile
      mkdir -p etc/modulefiles
      cat > etc/modulefiles/$PKGNAME <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 ROOT/$ROOT_VERSION-$ROOT_REVISION ''${BOOST_REVISION:+boost/$BOOST_VERSION-$BOOST_REVISION}
      # Our environment
      setenv ROOUNFOLD_RELEASE \$version
      setenv ROOUNFOLD_VERSION $PKGVERSION
      set ROOUNFOLD_ROOT \$::env(BASEDIR)/$PKGNAME/\$::env(ROOUNFOLD_RELEASE)
      setenv ROOUNFOLD_ROOT \$ROOUNFOLD_ROOT
      prepend-path PATH \$ROOUNFOLD_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$ROOUNFOLD_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$ROOUNFOLD_ROOT/include
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  treelite = stdenv.mkDerivation {
    name = "treelite";
    version = "8498081";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/8498081";
    url="https://github.com/dmlc/treelite";});

    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=treelite
      PKGVERSION=8498081
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      rsync -a $SOURCEDIR/ src/
      pushd src
        git submodule update --init --recursive
      popd

      cmake src                                   \
        ''${CMAKE_GENERATOR:+-G "$CMAKE_GENERATOR"} \
        -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"     \
        -DUSE_OPENMP=OFF

      cmake --build . -- ''${JOBS:+-j$JOBS} install

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
      set TREELITE_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path PATH \$TREELITE_ROOT/bin
      prepend-path ROOT_INCLUDE_PATH \$TREELITE_ROOT/include
      prepend-path ROOT_INCLUDE_PATH \$TREELITE_ROOT/runtime/native/include
      prepend-path LD_LIBRARY_PATH \$TREELITE_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  KFParticle = stdenv.mkDerivation {
    name = "KFParticle";
    version = "v1.1-5";
    
    
    src=(builtins.fetchGit {
    rev="efa03d1e52a848b3b6db2916620de641143fc06f";
    url="https://github.com/alisw/KFParticle";});

    
    
    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      Vc
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=KFParticle
      PKGVERSION=v1.1-5
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export VC_ROOT=${ Vc.out }
      VC_VERSION=${ Vc.version }
      VC_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      cmake $SOURCEDIR                                        \
            ''${VC_REVISION:+-DVc_INCLUDE_DIR=$VC_ROOT/include}  \
            ''${VC_VERSIOM:+-DVc_LIBRARIES=$VCROOT/lib/libVc.a} \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT               \
            -DCMAKE_BUILD_TYPE="$CMAKE_BUILD_TYPE"            \
            -DFIXTARGET=FALSE
      make ''${JOBS+-j $JOBS} install

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
      module load BASE/1.0 ''${GCC_TOOLCHAIN_REVISION:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION} ''${VC_REVISION:+Vc/$VC_VERSION-$VC_REVISION} ''${ROOT_REVISION:+ROOT/$ROOT_VERSION-$ROOT_REVISION}
      # Our environment
      set KFPARTICLE_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv KFPARTICLE_ROOT \$KFPARTICLE_ROOT
      set BASEDIR \$::env(BASEDIR)
      prepend-path ROOT_INCLUDE_PATH \$BASEDIR/$PKGNAME/\$version/include
      prepend-path LD_LIBRARY_PATH \$BASEDIR/$PKGNAME/\$version/lib
      EoF
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

      rsync -a --chmod=ug=rwX --exclude '**/.git' --delete --delete-excluded "$SOURCEDIR"/ "$BUILDDIR"/
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
      mkdir -p "$INSTALLROOT"/etc/modulefiles && rsync -a --delete etc/modulefiles/ "$INSTALLROOT"/etc/modulefiles
      runHook postInstall
    '';
  };

  ZeroMQ = stdenv.mkDerivation {
    name = "ZeroMQ";
    version = "v4.3.5";
    
    
    src=(builtins.fetchGit {
    rev="4d9c8f8ccf4f659e8397cad42f8496551f534597";
    url="https://github.com/zeromq/libzmq";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=ZeroMQ
      PKGVERSION=v4.3.5
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      cd $BUILDDIR
      cmake $SOURCEDIR                          \
            -G Ninja                            \
            -DENABLE_WS=OFF                     \
            -DBUILD_TESTS=OFF                   \
            -DCMAKE_INSTALL_LIBDIR=lib          \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT

      ninja ''${JOBS+-j $JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --lib > $MODULEFILE
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
    version = "v6-32-06-alice1";
    
    
    src=(builtins.fetchGit {
    rev="10b8d555b926de44c7bd59c29aa7bb170619e7d0";
    url="https://github.com/alisw/root.git";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      arrow
      AliEn-Runtime
      Python-modules
      XRootD
      TBB
      protobuf
      FFTW3
      Vc
      pythia
      nlohmann_json
      CMake
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
      PKGVERSION=v6-32-06-alice1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
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
      
      export NLOHMANN_JSON_ROOT=${ nlohmann_json.out }
      NLOHMANN_JSON_VERSION=${ nlohmann_json.version }
      NLOHMANN_JSON_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

  DPMJET = stdenv.mkDerivation {
    name = "DPMJET";
    version = "v19.3.7-alice1";
    
    
    src=(builtins.fetchGit {
    rev="98d4e2f6ffa4bf337a44df4b80686b4449acd2b2";
    url="https://github.com/alisw/DPMJET.git";});

    
    
    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=DPMJET
      PKGVERSION=v19.3.7-alice1
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      FVERSION=`gfortran --version | grep -i fortran | sed -e 's/.* //' | cut -d. -f1`
      SPECIALFFLAGS=""
      if [ $FVERSION -ge 10 ]; then
         echo "Fortran version $FVERSION"
         SPECIALFFLAGS=1
      fi

      cmake  $SOURCEDIR                           \
             -DCMAKE_INSTALL_PREFIX=$INSTALLROOT  \
             ''${SPECIALFFLAGS:+-DCMAKE_Fortran_FLAGS="-fallow-argument-mismatch"}

      make ''${JOBS+-j $JOBS} install

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
      set DPMJET_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv DPMJET_ROOT \$DPMJET_ROOT
      prepend-path PATH \$DPMJET_ROOT/bin
      prepend-path LD_LIBRARY_PATH \$DPMJET_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  fastjet = stdenv.mkDerivation {
    name = "fastjet";
    version = "v3.4.1_1.052-alice2";
    
    
    src=(builtins.fetchGit {
    rev="e15ac4faf9eed84677de3a9f3af9c054425e303c";
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
      PKGVERSION=v3.4.1_1.052-alice2
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

  GEANT3 = stdenv.mkDerivation {
    name = "GEANT3";
    version = "v4-4";
    
    
    src=(builtins.fetchGit {
    rev="512399095b51664a06109f3ba5d9e3286d49f8ce";
    url="https://github.com/vmc-project/geant3";});

    
    
    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      VMC
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=GEANT3
      PKGVERSION=v4-4
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export VMC_ROOT=${ VMC.out }
      VMC_VERSION=${ VMC.version }
      VMC_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      FVERSION=`gfortran --version | grep -i fortran | sed -e 's/.* //' | cut -d. -f1`
      SPECIALFFLAGS=""
      if [ $FVERSION -ge 10 ]; then
         echo "Fortran version $FVERSION"
         SPECIALFFLAGS=1
      fi
      cmake $SOURCEDIR -DCMAKE_INSTALL_PREFIX=$INSTALLROOT      \
                       -DCMAKE_BUILD_TYPE=$CMAKE_BUILD_TYPE     \
                       ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}  \
                       -DCMAKE_SKIP_RPATH=TRUE \
                       ''${SPECIALFFLAGS:+-DCMAKE_Fortran_FLAGS="-fallow-argument-mismatch -fallow-invalid-boz -fno-tree-loop-distribute-patterns"}
      make ''${JOBS:+-j $JOBS} install

      [[ ! -d $INSTALLROOT/lib64 ]] && ln -sf lib $INSTALLROOT/lib64

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
      module load BASE/1.0 ROOT/$ROOT_VERSION-$ROOT_REVISION VMC/$VMC_VERSION-$VMC_REVISION
      # Our environment
      set GEANT3_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv GEANT3_ROOT \$GEANT3_ROOT
      setenv GEANT3DIR \$GEANT3_ROOT
      setenv G3SYS \$GEANT3_ROOT
      prepend-path LD_LIBRARY_PATH \$GEANT3_ROOT/lib64
      prepend-path ROOT_INCLUDE_PATH \$GEANT3_ROOT/include/TGeant3
      EoF
      runHook postInstall
    '';
  };

  GEANT4_VMC = stdenv.mkDerivation {
    name = "GEANT4_VMC";
    version = "v6-6-p3";
    
    
    src=(builtins.fetchGit {
    rev="33820285a3d91b6f79e767f02d4de041ac8a9a4e";
    url="https://github.com/vmc-project/geant4_vmc";});

    
    
    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      VMC
      GEANT4
      vgm
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=GEANT4_VMC
      PKGVERSION=v6-6-p3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export VMC_ROOT=${ VMC.out }
      VMC_VERSION=${ VMC.version }
      VMC_REVISION=1
      
      export GEANT4_ROOT=${ GEANT4.out }
      GEANT4_VERSION=${ GEANT4.version }
      GEANT4_REVISION=1
      
      export VGM_ROOT=${ vgm.out }
      VGM_VERSION=${ vgm.version }
      VGM_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      LDFLAGS="$LDFLAGS -L$GEANT4_ROOT/lib"            \
        cmake "$SOURCEDIR"                             \
          -GNinja                                      \
          -DCMAKE_CMAKE_BUILD_TYPE=''${CMAKE_BUILD_TYPE} \
          -DGeant4VMC_USE_VGM=ON                       \
          -DCMAKE_INSTALL_LIBDIR=lib                   \
          -DGeant4VMC_BUILD_EXAMPLES=OFF               \
          -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
          ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}

      cmake --build . -- ''${JOBS+-j $JOBS} install

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
      module load BASE/1.0 ''${GEANT4_REVISION:+GEANT4/$GEANT4_VERSION-$GEANT4_REVISION} ''${ROOT_REVISION:+ROOT/$ROOT_VERSION-$ROOT_REVISION} ''${VMC_REVISION:+VMC/$VMC_VERSION-$VMC_REVISION} vgm/$VGM_VERSION-$VGM_REVISION
      # Our environment
      set GEANT4_VMC_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv GEANT4_VMC_ROOT \$GEANT4_VMC_ROOT
      setenv G4VMCINSTALL \$GEANT4_VMC_ROOT
      setenv USE_VGM 1
      prepend-path PATH \$GEANT4_VMC_ROOT/bin
      prepend-path ROOT_INCLUDE_PATH \$GEANT4_VMC_ROOT/include/geant4vmc
      prepend-path ROOT_INCLUDE_PATH \$GEANT4_VMC_ROOT/include/g4root
      prepend-path LD_LIBRARY_PATH \$GEANT4_VMC_ROOT/lib
      EoF
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

  JAliEn-ROOT = stdenv.mkDerivation {
    name = "JAliEn-ROOT";
    version = "0.7.14";
    
    
    src=(builtins.fetchGit {
    rev="6cf9c228e746dfc8d5ac7bb9e1c6b5e57d2a700b";
    url="https://gitlab.cern.ch/jalien/jalien-root.git";});

    
    
    
    buildInputs = [
      json-c
      CMake
      zlib
      Alice-GRID-Utils
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      xjalienfs
      XRootD
      libwebsockets
      libuv
      json-c
      CMake
      zlib
      Alice-GRID-Utils
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=JAliEn-ROOT
      PKGVERSION=0.7.14
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export JSON_C_ROOT=${ json-c.out }
      JSON_C_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_REVISION=1
      
      export ALICE_GRID_UTILS_ROOT=${ Alice-GRID-Utils.out }
      ALICE_GRID_UTILS_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export XJALIENFS_ROOT=${ xjalienfs.out }
      XJALIENFS_VERSION=${ xjalienfs.version }
      XJALIENFS_REVISION=1
      
      export XROOTD_ROOT=${ XRootD.out }
      XROOTD_VERSION=${ XRootD.version }
      XROOTD_REVISION=1
      
      export LIBWEBSOCKETS_ROOT=${ libwebsockets.out }
      LIBWEBSOCKETS_VERSION=${ libwebsockets.version }
      LIBWEBSOCKETS_REVISION=1
      
      export LIBUV_ROOT=${ libuv.out }
      LIBUV_VERSION=${ libuv.version }
      LIBUV_REVISION=1
      
      export JSON_C_ROOT=${ json-c.out }
      JSON_C_VERSION=${ json-c.version }
      JSON_C_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export ALICE_GRID_UTILS_ROOT=${ Alice-GRID-Utils.out }
      ALICE_GRID_UTILS_VERSION=${ Alice-GRID-Utils.version }
      ALICE_GRID_UTILS_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      SONAME=so
      case $ARCHITECTURE in
        osx*)
              SONAME=dylib
      	[[ ! $OPENSSL_ROOT ]] && OPENSSL_ROOT=$(brew --prefix openssl@3)
      	[[ ! $LIBWEBSOCKETS_ROOT ]] && LIBWEBSOCKETS_ROOT=$(brew --prefix libwebsockets)
        ;;
      esac

      # This is needed to support old version which did not have FindAliceGridUtils.cmake
      ALIBUILD_CMAKE_BUILD_DIR=$SOURCEDIR
      if [ ! -f "$JALIEN_ROOT_ROOT/cmake/modules/FindAliceGridUtils.cmake" ]; then
        ALIBUILD_CMAKE_BUILD_DIR="$BUILDDIR"
        rsync -a --exclude '**/.git' --delete "$SOURCEDIR/" "$BUILDDIR"
        rsync -a "$ALICE_GRID_UTILS_ROOT/include/" "$BUILDDIR/inc"
      fi

      cmake "$ALIBUILD_CMAKE_BUILD_DIR"                        \
            -G Ninja                                           \
            -DCMAKE_BUILD_TYPE=Debug                           \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"              \
            ''${CXXSTD:+-DCMAKE_CXX_STANDARD=''${CXXSTD}}          \
            -DROOTSYS="$ROOTSYS"                               \
            -DJSONC="$JSON_C_ROOT"                             \
            -DALICE_GRID_UTILS_ROOT="$ALICE_GRID_UTILS_ROOT"   \
             ''${OPENSSL_ROOT:+-DOPENSSL_ROOT_DIR=$OPENSSL_ROOT} \
             ''${OPENSSL_ROOT:+-DOPENSSL_INCLUDE_DIRS=$OPENSSL_ROOT/include} \
             ''${OPENSSL_ROOT:+-DOPENSSL_LIBRARIES=$OPENSSL_ROOT/lib/libssl.$SONAME;$OPENSSL_ROOT/lib/libcrypto.$SONAME} \
            -DZLIB_ROOT="$ZLIB_ROOT"                           \
            -DXROOTD_ROOT_DIR="$XROOTD_ROOT"                   \
            -DLWS="$LIBWEBSOCKETS_ROOT"
      cmake --build . -- ''${JOBS:+-j $JOBS} install

      # Modulefile
      mkdir -p etc/modulefiles
      alibuild-generate-module --lib --cmake > "etc/modulefiles/$PKGNAME"
      cat >> "etc/modulefiles/$PKGNAME" <<EoF
      # Our environment
      append-path ROOT_PLUGIN_PATH \$PKG_ROOT/etc/plugins
      prepend-path ROOT_INCLUDE_PATH \$PKG_ROOT/include
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  CMake = stdenv.mkDerivation {
    name = "CMake";
    version = "v3.31.6";
    
    
    src=(builtins.fetchGit {
    rev="a9b14138fe83e134bc3da139857b5616695bab54";
    url="https://github.com/Kitware/CMake";});

    
    
    
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
      PKGNAME=CMake
      PKGVERSION=v3.31.6
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

      cat > build-flags.cmake <<- EOF
      # Disable Java capabilities; we don't need it and on OS X might miss the
      # required /System/Library/Frameworks/JavaVM.framework/Headers/jni.h.
      SET(JNI_H FALSE CACHE BOOL "" FORCE)
      SET(Java_JAVA_EXECUTABLE FALSE CACHE BOOL "" FORCE)
      SET(Java_JAVAC_EXECUTABLE FALSE CACHE BOOL "" FORCE)

      # SL6 with GCC 4.6.1 and LTO requires -ltinfo with -lcurses for link to succeed,
      # but cmake is not smart enough to find it. We do not really need ccmake anyway,
      # so just disable it.
      SET(BUILD_CursesDialog FALSE CACHE BOOL "" FORCE)
      EOF

      $SOURCEDIR/bootstrap --prefix=$INSTALLROOT \
                           --init=build-flags.cmake \
                           ''${JOBS:+--parallel=$JOBS}
      make ''${JOBS+-j $JOBS}
      make install/strip

      
      mkdir -p etc/modulefiles
      alibuild-generate-module --bin --lib > etc/modulefiles/$PKGNAME
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
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

  zlib = stdenv.mkDerivation {
    name = "zlib";
    version = "v1.2.13";
    
    
    src=(builtins.fetchGit {
    rev="f0def284228615ddee0bf462ef856fd426ceb7e1";
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
      PKGVERSION=v1.2.13
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

  arrow = stdenv.mkDerivation {
    name = "arrow";
    version = "v17.0.0-alice6";
    
    
    src=(builtins.fetchGit {
    rev="1a4ea55104c72bb60618bd0846cac2bd16f28d71";
    url="https://github.com/alisw/arrow.git";});

    
    
    
    buildInputs = [
      zlib
      flatbuffers
      RapidJSON
      CMake
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
      CMake
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
      PKGVERSION=v17.0.0-alice6
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
            ''${PYTHON_ROOT:+-DPython3_EXECUTABLE="$(which python3)"}                               \
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
            -DCLANG_EXECUTABLE="$CLANG_EXECUTABLE"                                                        \
            ''${GCC_TOOLCHAIN_REVISION:+-DGCC_TOOLCHAIN_ROOT=`find "$GCC_TOOLCHAIN_ROOT/lib" -name crtbegin.o -exec dirname {} \;`}

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
      ApMon-CPP
      UUID
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      zlib
      AliEn-CAs
      ApMon-CPP
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
      
      export APMON_CPP_ROOT=${ ApMon-CPP.out }
      APMON_CPP_REVISION=1
      
      export UUID_ROOT=${ UUID.out }
      UUID_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export ALIEN_CAS_ROOT=${ AliEn-CAs.out }
      ALIEN_CAS_VERSION=${ AliEn-CAs.version }
      ALIEN_CAS_REVISION=1
      
      export APMON_CPP_ROOT=${ ApMon-CPP.out }
      APMON_CPP_VERSION=${ ApMon-CPP.version }
      APMON_CPP_REVISION=1
      
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

  XRootD = stdenv.mkDerivation {
    name = "XRootD";
    version = "v5.7.2";
    
    
    src=(builtins.fetchGit {
    rev="23d813812b16df91121b853696dc281aa3df6925";
    url="https://github.com/xrootd/xrootd";});

    
    
    
    buildInputs = [
      CMake
      UUID
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python-modules
      AliEn-Runtime
      CMake
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
      PKGVERSION=v5.7.2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
        osx_arm64) CMAKE_FRAMEWORK_PATH=$(brew --prefix)/Frameworks ;;
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      alibuild-recipe-tools
      abseil
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

  pythia = stdenv.mkDerivation {
    name = "pythia";
    version = "v8311";
    
    
    src=(builtins.fetchGit {
    rev="a87bede907f82a5e62490fe08d590de417b964d5";
    url="https://github.com/alisw/pythia8";});

    
    
    
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
      PKGVERSION=v8311
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

  nlohmann_json = stdenv.mkDerivation {
    name = "nlohmann_json";
    version = "v3.11.3";
    
    
    src=(builtins.fetchGit {
    rev="9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03";
    url="https://github.com/nlohmann/json";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=nlohmann_json
      PKGVERSION=v3.11.3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
        cmake "$SOURCEDIR"                             \
          -DCMAKE_BUILD_TYPE=''${CMAKE_BUILD_TYPE} \
          -DJSON_BuildTests=OFF                          \
          -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
          ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}      \

      cmake --build . -- ''${IGNORE_ERRORS:+-k} ''${JOBS+-j $JOBS} install

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > "$MODULEFILE"
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
      CMake
      curl
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      boost
      GMP
      MPFR
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

  VMC = stdenv.mkDerivation {
    name = "VMC";
    version = "v2-0";
    
    
    src=(builtins.fetchGit {
    rev="cf1f75240220d97e858dba0a4303cacc1c30041b";
    url="https://github.com/vmc-project/vmc";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=VMC
      PKGVERSION=v2-0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      # Make basic modufile first
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module > $MODULEFILE

      [ "0$ENABLE_VMC" == "0" ] && exit 0 || true

      cmake "$SOURCEDIR"                                 \
            -DCMAKE_CMAKE_BUILD_TYPE=''${CMAKE_BUILD_TYPE} \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
            -DCMAKE_INSTALL_LIBDIR=lib                   \
            ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}

      cmake --build . -- ''${JOBS:+-j$JOBS} install

      # Make backward compatible in case a depending (older) package still needs libVMC.so
      cd $INSTALLROOT/lib
      case $ARCHITECTURE in
        osx*)
            ln -s libVMCLibrary.dylib libVMC.dylib
        ;;
        *)
            ln -s libVMCLibrary.so libVMC.so
        ;;
      esac
      # update modulefile
      cat >> "$MODULEFILE" <<EoF
      # Our environment
      set VMC_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv VMC_ROOT \$VMC_ROOT
      prepend-path LD_LIBRARY_PATH \$VMC_ROOT/lib
      prepend-path ROOT_INCLUDE_PATH \$VMC_ROOT/include/vmc
      EoF
      runHook postInstall
    '';
  };

  GEANT4 = stdenv.mkDerivation {
    name = "GEANT4";
    version = "v11.2.0";
    
    
    src=(builtins.fetchGit {
    rev="f03d09869b65bb1efbd0b6a2bb6cd19acb25c950";
    url="https://gitlab.cern.ch/geant4/geant4.git";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=GEANT4
      PKGVERSION=v11.2.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      # If this variable is not defined default it to OFF
      : ''${GEANT4_BUILD_MULTITHREADED:=OFF}

      # Data sets directory:
      # if not set (default), data sets will be installed in CMAKE_INSTALL_DATAROOTDIR
      : ''${GEANT4_DATADIR:=""}

      cmake $SOURCEDIR                                                \
        -DGEANT4_INSTALL_DATA_TIMEOUT=2000                            \
        -DCMAKE_CXX_FLAGS="-fPIC"                                     \
        -DCMAKE_INSTALL_PREFIX:PATH="$INSTALLROOT"                    \
        -DCMAKE_INSTALL_LIBDIR="lib"                                  \
        -DCMAKE_BUILD_TYPE=RelWithDebInfo                             \
        -DGEANT4_BUILD_TLS_MODEL:STRING="global-dynamic"              \
        -DGEANT4_ENABLE_TESTING=OFF                                   \
        -DBUILD_SHARED_LIBS=ON                                        \
        -DGEANT4_INSTALL_EXAMPLES=OFF                                 \
        -DCLHEP_ROOT_DIR:PATH="$CLHEP_ROOT"                           \
        -DGEANT4_BUILD_MULTITHREADED="$GEANT4_BUILD_MULTITHREADED"    \
        -DCMAKE_STATIC_LIBRARY_CXX_FLAGS="-fPIC"                      \
        -DCMAKE_STATIC_LIBRARY_C_FLAGS="-fPIC"                        \
        -DGEANT4_USE_G3TOG4=ON                                        \
        -DGEANT4_INSTALL_DATA=ON                                      \
        ''${GEANT4_DATADIR:+-DGEANT4_INSTALL_DATADIR="$GEANT4_DATADIR"} \
        -DGEANT4_USE_SYSTEM_EXPAT=OFF                                 \
        ''${XERCESC_ROOT:+-DXERCESC_ROOT_DIR=$XERCESC_ROOT}             \
        ''${CXXSTD:+-DGEANT4_BUILD_CXXSTD=$CXXSTD}                      \
        -DG4_USE_GDML=ON                                              \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

      
      make ''${JOBS+-j $JOBS}
      make install

      # we should not use cached package links
      packagecachefile=$(find ''${INSTALLROOT} -name "Geant4PackageCache.cmake")
      echo "#" > $packagecachefile

      # Install data sets
      # Can be done after Geant4 installation, if installed with -DGEANT4_INSTALL_DATA=OFF
      # ./geant4-config --install-datasets

      # Modulefile
      MODULEDIR="$INSTALLROOT/etc/modulefiles"
      MODULEFILE="$MODULEDIR/$PKGNAME"
      mkdir -p "$MODULEDIR"
      alibuild-generate-module --bin --lib > $MODULEFILE
      cat >> "$MODULEFILE" <<EOF
      # extra environment
      set GEANT4_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv GEANT4_ROOT \$GEANT4_ROOT
      EOF

      # Data sets environment
      $INSTALLROOT/bin/geant4-config --datasets |  sed 's/[^ ]* //' | sed 's/G4/setenv G4/' >> "$MODULEFILE"
      runHook postInstall
    '';
  };

  vgm = stdenv.mkDerivation {
    name = "vgm";
    version = "v5-3";
    
    
    src=(builtins.fetchGit {
    rev="d885af799d6f9dcf5018e412bb213ac81142913c";
    url="https://github.com/vmc-project/vgm";});

    
    
    
    buildInputs = [
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      ROOT
      GEANT4
      CMake
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=vgm
      PKGVERSION=v5-3
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ROOT_ROOT=${ ROOT.out }
      ROOT_VERSION=${ ROOT.version }
      ROOT_REVISION=1
      
      export GEANT4_ROOT=${ GEANT4.out }
      GEANT4_VERSION=${ GEANT4.version }
      GEANT4_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      cmake "$SOURCEDIR" \
        -DCMAKE_CMAKE_BUILD_TYPE=''${CMAKE_BUILD_TYPE} \
        -DCMAKE_INSTALL_LIBDIR="lib"                 \
        -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
        ''${CXXSTD:+-DCMAKE_CXX_STANDARD=$CXXSTD}

      make ''${JOBS+-j $JOBS} install

      # Relocation of .cmake files
      for CMAKE in $(find "$INSTALLROOT/lib" -name '*.cmake'); do
        sed -ideleteme -e "s!$ROOTSYS!\$ENV{ROOTSYS}!g; s!$G4INSTALL!\$ENV{G4INSTALL}!g" "$CMAKE"
      done
      find "$INSTALLROOT/lib" -name '*deleteme' -delete || true

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
      module load BASE/1.0 GEANT4/$GEANT4_VERSION-$GEANT4_REVISION ROOT/$ROOT_VERSION-$ROOT_REVISION
      # Our environment
      set VGM_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      setenv VGM_ROOT \$VGM_ROOT
      prepend-path LD_LIBRARY_PATH \$VGM_ROOT/lib
      EoF
      runHook postInstall
    '';
  };

  xjalienfs = stdenv.mkDerivation {
    name = "xjalienfs";
    version = "1.6.3";
    dontUnpack=true;
    
    
    
    
    buildInputs = [
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      XRootD
      AliEn-Runtime
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=xjalienfs
      PKGVERSION=1.6.3
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
      
      
      export XROOTD_ROOT=${ XRootD.out }
      XROOTD_VERSION=${ XRootD.version }
      XROOTD_REVISION=1
      
      export ALIEN_RUNTIME_ROOT=${ AliEn-Runtime.out }
      ALIEN_RUNTIME_VERSION=${ AliEn-Runtime.version }
      ALIEN_RUNTIME_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      # Use pip's --target to install under $INSTALLROOT without weird hacks. This
      # works inside and outside a virtualenv, but unset VIRTUAL_ENV to make sure we
      # only depend on stuff we installed using our Python and Python-modules.

      # on macos try to install gnureadline and just skip if fails (alienpy can work without it)
      # macos python readline implementation is build on libedit which does not work
      [[ "$ARCHITECTURE" ==  osx_* ]] && { \
          python3 -m pip install --force-reinstall \
          gnureadline || : ; }

      env ALIBUILD=1 \
          python3 -m pip install --force-reinstall \
          "git+https://gitlab.cern.ch/jalien/xjalienfs.git@$PKG_VERSION"
      # We do not need anything else, because python is going to be in path
      # if we are inside a virtualenv so no need to pretend we know where
      # the correct python is.

      # We generate the modulefile to avoid complains by dependencies
      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  libwebsockets = stdenv.mkDerivation {
    name = "libwebsockets";
    version = "v4.3.2";
    
    
    src=(builtins.fetchGit {
    rev="b0a749c8e7a8294b68581ce4feac0e55045eb00b";
    url="https://github.com/warmcat/libwebsockets";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      libuv
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=libwebsockets
      PKGVERSION=v4.3.2
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export LIBUV_ROOT=${ libuv.out }
      LIBUV_VERSION=${ libuv.version }
      LIBUV_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
      SONAME=so
      case $ARCHITECTURE in
        osx*)
          SONAME=dylib
          : "''${OPENSSL_ROOT:=$(brew --prefix openssl@3)}" ;;
      esac

      cmake $SOURCEDIR                                                    \
            -GNinja                                                       \
            -DCMAKE_C_FLAGS_RELEASE="-Wno-error"                          \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                         \
            -DCMAKE_BUILD_TYPE=RELEASE                                    \
            -DLWS_WITH_STATIC=ON                                          \
            -DLWS_WITH_SHARED=OFF                                         \
            -DLWS_WITH_IPV6=ON                                            \
            -DLWS_WITH_ZLIB=OFF                                           \
            ''${OPENSSL_ROOT:+-DOPENSSL_EXECUTABLE=$OPENSSL_ROOT/bin/openssl} \
            ''${OPENSSL_ROOT:+-DOPENSSL_ROOT_DIR=$OPENSSL_ROOT}             \
            ''${OPENSSL_ROOT:+-DOPENSSL_INCLUDE_DIRS=$OPENSSL_ROOT/include} \
            ''${OPENSSL_ROOT:+-DOPENSSL_LIBRARIES=$OPENSSL_ROOT/lib/libssl.$SONAME;$OPENSSL_ROOT/lib/libcrypto.$SONAME}     \
            ''${OPENSSL_ROOT:+-DLWS_OPENSSL_INCLUDE_DIRS=$OPENSSL_ROOT/include}                                             \
            ''${OPENSSL_ROOT:+-DLWS_OPENSSL_LIBRARIES=$OPENSSL_ROOT/lib/libssl.$SONAME;$OPENSSL_ROOT/lib/libcrypto.$SONAME} \
            -DLWS_WITH_LIBUV=ON                                           \
            ''${LIBUV_REVISION:+-DLIBUV_INCLUDE_DIRS=$LIBUV_ROOT/include}   \
            ''${LIBUV_REVISION:+-DLIBUV_LIBRARIES=$LIBUV_ROOT/lib/libuv.$SONAME} \
            -DLWS_HAVE_OPENSSL_ECDH_H=OFF                                 \
            -DLWS_WITHOUT_TESTAPPS=ON
      cmake --build . --target install ''${JOBS+-j $JOBS}
      rm -rf $INSTALLROOT/share

      # Modulefile
      mkdir -p etc/modulefiles
      alibuild-generate-module --lib --bin > etc/modulefiles/$PKGNAME
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  libuv = stdenv.mkDerivation {
    name = "libuv";
    version = "v1.40.0";
    
    
    src=(builtins.fetchGit {
    rev="6ddfc47008d2439797d54ad51bd42b81194fbcb4";
    url="https://github.com/libuv/libuv";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=libuv
      PKGVERSION=v1.40.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/sh
      cmake $SOURCEDIR                                             \
            -DCMAKE_INSTALL_PREFIX=$INSTALLROOT                    \
            -DCMAKE_INSTALL_LIBDIR=lib

      make ''${JOBS+-j $JOBS}
      make install

      mkdir -p etc/modulefiles
      alibuild-generate-module --lib --cmake > etc/modulefiles/$PKGNAME
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  json-c = stdenv.mkDerivation {
    name = "json-c";
    version = "v0.17.0";
    
    
    src=(builtins.fetchGit {
    rev="3da8e04822d4f90dba570d0d8ce013f5095002ca";
    url="https://github.com/json-c/json-c";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
    ] ++ systemDeps;

    unpackPhase = properUnpack;

    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      set -x
      PKGNAME=json-c
      PKGVERSION=v0.17.0
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e

      cmake "$SOURCEDIR"                                               \
            -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"                      \
            -DBUILD_SHARED_LIBS=OFF                                    \
            ''${CMAKE_BUILD_TYPE:+-DCMAKE_BUILD_TYPE=$CMAKE_BUILD_TYPE}

      cmake --build . --target install ''${JOBS:+-- -j$JOBS}

      mkdir -p "$INSTALLROOT/etc/modulefiles"
      alibuild-generate-module --bin --lib --cmake > "$INSTALLROOT/etc/modulefiles/$PKGNAME"
      runHook postInstall
    '';
  };

  Alice-GRID-Utils = stdenv.mkDerivation {
    name = "Alice-GRID-Utils";
    version = "0.0.7";
    
    
    src=(builtins.fetchGit {
    rev="62ce4da469426f1a9a2207a95624fede852a54c7";
    url="https://gitlab.cern.ch/jalien/alice-grid-utils.git";});

    
    
    
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
      PKGNAME=Alice-GRID-Utils
      PKGVERSION=0.0.7
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

      DST="$INSTALLROOT/include"
      mkdir -p "$DST"
      cp -v "$SOURCEDIR"/*.h "$DST/"

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
      EoF
      runHook postInstall
    '';
  };

  hdf5 = stdenv.mkDerivation {
    name = "hdf5";
    version = "1.10.9";
    
    
    src=(builtins.fetchGit {
    rev="1d90890a7b38834074169ce56720b7ea7f4b01ae";
    url="https://github.com/HDFGroup/hdf5.git";});

    
    
    
    buildInputs = [
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      PKGVERSION=1.10.9
      PKGREVISION=1
      PKGHASH=1
      INSTALLROOT=$out
      mkdir -p $INSTALLROOT
      ARCHITECTURE=osx_arm64
      JOBS=10
      SOURCEDIR=$src
      BUILDDIR=$PWD
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_VERSION=${ defaults-release.version }
      DEFAULTS_RELEASE_REVISION=1
      
      mkdir -p $BUILDDIR
      #!/bin/bash -e
        cmake "$SOURCEDIR"                             \
          -DCMAKE_CMAKE_BUILD_TYPE=''${CMAKE_BUILD_TYPE} \
          -DCMAKE_INSTALL_PREFIX="$INSTALLROOT"        \
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

  Clang = stdenv.mkDerivation {
    name = "Clang";
    version = "v18.1.8";
    
    
    src=(builtins.fetchGit {
    rev="7f97f9dbe9cd3a27df753ed034e24941b1423a58";
    url="https://github.com/alisw/llvm-project-reduced";});

    
    
    
    buildInputs = [
      Python
      CMake
      curl
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      Python
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export CURL_ROOT=${ curl.out }
      CURL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export PYTHON_ROOT=${ Python.out }
      PYTHON_VERSION=${ Python.version }
      PYTHON_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      alibuild-recipe-tools
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_VERSION=${ alibuild-recipe-tools.version }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      zlib
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export ZLIB_ROOT=${ zlib.out }
      ZLIB_VERSION=${ zlib.version }
      ZLIB_REVISION=1
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      alibuild-recipe-tools
      abseil
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export ABSEIL_ROOT=${ abseil.out }
      ABSEIL_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

  Python = stdenv.mkDerivation {
    name = "Python";
    version = "python-brew3.12.9";
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
      PKGVERSION=python-brew3.12.9
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

  AliEn-CAs = stdenv.mkDerivation {
    name = "AliEn-CAs";
    version = "v1";
    
    
    
    src=(builtins.fetchGit {
    rev="f62625ede780d455b3b7878064bcfee6bd9a4f53";
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

  ApMon-CPP = stdenv.mkDerivation {
    name = "ApMon-CPP";
    version = "v2.2.8-alice6";
    
    
    src=(builtins.fetchGit {
    rev="adbaba5c736fc1d05bd5857b889de044e13c0aba";
    url="https://github.com/alisw/apmon-cpp.git";});

    
    
    
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
      PKGNAME=ApMon-CPP
      PKGVERSION=v2.2.8-alice6
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
      rsync -a --chmod=ug=rwX --exclude='**/.git' --delete --delete-excluded \
            $SOURCEDIR/ ./
      autoreconf -ivf

      if [[ -n ''${LIBTIRPC_ROOT} ]];
      then
        export CXXFLAGS="''${CXXFLAGS} -I''${LIBTIRPC_ROOT}/include/tirpc"
        export LDFLAGS="''${LDFLAGS} -ltirpc -L''${LIBTIRPC_ROOT}/lib"
      fi

      ./configure --prefix=$INSTALLROOT
      make ''${JOBS:+-j$JOBS}
      make install

      find $INSTALLROOT -name '*.la' -delete

      # Modules
      mkdir -p etc/modulefiles
      cat > etc/modulefiles/$PKGNAME <<EoF
      #%Module1.0
      proc ModulesHelp { } {
        global version
        puts stderr "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      }
      set version $PKGVERSION-@@PKGREVISION@$PKGHASH@@
      module-whatis "ALICE Modulefile for $PKGNAME $PKGVERSION-@@PKGREVISION@$PKGHASH@@"
      # Dependencies
      module load BASE/1.0 \\
             ''${GCC_TOOLCHAIN_ROOT:+GCC-Toolchain/$GCC_TOOLCHAIN_VERSION-$GCC_TOOLCHAIN_REVISION}
      # Our environment
      set APMON_CPP_ROOT \$::env(BASEDIR)/$PKGNAME/\$version
      prepend-path LD_LIBRARY_PATH \$APMON_CPP_ROOT/lib
      EoF
      mkdir -p $INSTALLROOT/etc/modulefiles && rsync -a --delete etc/modulefiles/ $INSTALLROOT/etc/modulefiles
      runHook postInstall
    '';
  };

  UUID = stdenv.mkDerivation {
    name = "UUID";
    version = "v2.27.1";
    
    
    
    
    src=(builtins.fetchGit {
    ref="refs/tags/alice/v2.27.1";
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
      rsync --chmod=ug=rwX -av --delete --exclude '**/.git' "$SOURCEDIR/" .
      if [[ $AUTOTOOLS_ROOT == "" ]]  && which brew >/dev/null; then
        PATH=$PATH:$(brew --prefix gettext)/bin
      fi

      perl -p -i -e 's/AM_GNU_GETTEXT_VERSION\(\[0\.18\.3\]\)/AM_GNU_GETTEXT_VERSION([0.18.2])/' configure.ac

      case $ARCHITECTURE in
        osx_*) disable_shared=yes ;;
        *) disable_shared= ;;
      esac

      autoreconf -ivf
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      CMake
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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
      rsync -a --delete --exclude '**/.git' $SOURCEDIR/ ./
      perl -p -i -e 's/ doc / /' Makefile.am
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
      CMake
      alibuild-recipe-tools
      defaults-release
      pkgs.apple-sdk_15
    ] ++ systemDeps;
    propagateBuildInputs = [
      CMake
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
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_REVISION=1
      
      export ALIBUILD_RECIPE_TOOLS_ROOT=${ alibuild-recipe-tools.out }
      ALIBUILD_RECIPE_TOOLS_REVISION=1
      
      export DEFAULTS_RELEASE_ROOT=${ defaults-release.out }
      DEFAULTS_RELEASE_REVISION=1
      
      
      export CMAKE_ROOT=${ CMake.out }
      CMAKE_VERSION=${ CMake.version }
      CMAKE_REVISION=1
      
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

in
{
  inherit AliPhysics AliRoot RooUnfold treelite KFParticle boost ZeroMQ defaults-release ROOT DPMJET fastjet GEANT3 GEANT4_VMC Vc JAliEn-ROOT CMake Python-modules zlib alibuild-recipe-tools arrow AliEn-Runtime XRootD TBB protobuf FFTW3 pythia nlohmann_json cgal GMP VMC GEANT4 vgm xjalienfs libwebsockets libuv json-c Alice-GRID-Utils hdf5 Python-modules-list Clang utf8proc xsimd flatbuffers RapidJSON double-conversion re2 Python AliEn-CAs ApMon-CPP UUID abseil lhapdf HepMC MPFR curl;
}
