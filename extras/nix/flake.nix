{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs = { self, nixpkgs }: 
  let
    system = "aarch64-darwin"; # Change to "x86_64-darwin" for Intel Macs
    pkgs = import nixpkgs { inherit system; };

    fetchurlWithAuth = { url, sha256, ... }@attrs:
      pkgs.fetchurl (attrs // {
        inherit url sha256;
        netrcPhase = ''
          export PATH=/usr/bin:$PATH
          curlOpts="$curlOpts --cert /Users/ktf/.globus/usercert.pem --key /Users/ktf/.globus/userkey.pem"
        '';
    });

    hyperloop = import ./hyperloop.nix {
      pkgs=pkgs;
      stdenv=pkgs.stdenv; 
      fetchurl=fetchurlWithAuth;
      mkShell=pkgs.mkShell;
    };

    # These are depependencies which come with a custom copy
    # of the brew command which allows picking them up from the system
    fullSystemDeps = with pkgs; (helpers.o2systemdeps {name="fullSystemDeps"; deps={
      "openssl*"=  pkgs.openssl.dev;
      "xz*"= pkgs.xz.dev;
    #  "libuv*"= pkgs.libuv.dev;
    #  "lz4*"= pkgs.lz4.dev;
    #  "gsl*"= pkgs.gsl.dev;
    #  "xerces-c*"= pkgs.xercesc;
    #  "hdf5"= pkgs.hdf5.dev;
    #  "tbb"= pkgs.tbb.dev;
      "gettext"= pkgs.gettext;
      "python*"=basicPythonEnv;
    #  "cmake"= pkgs.cmake;
    #  "pcre"= pkgs.pcre;
    #  "re2"= pkgs.re2;
    #  "boost"= pkgs.boost;
    #  "iconv"= pkgs.iconv;
    #  "c-ares"= pkgs.c-ares;
    #  "double-conversion"= pkgs.double-conversion;
    #  "flatbuffers"= pkgs.flatbuffers;
    #  "clhep"= pkgs.clhep;
    #  "geant4"= pkgs.geant4;
    #  "llvm*"= customLLVM;
    #  "utf8proc"= pkgs.utf8proc;
    #  "protobuf"= pkgs.protobuf;
    #  "libffi"= pkgs.libffi;
      "zlib"= pkgs.zlib.dev;
    #  "zlib.dev"= pkgs.zlib.dev;
    #  "lz4"= pkgs.lz4;
    };});

    alisw = import ./alidist.nix {
      pkgs=pkgs;
      stdenv=pkgs.stdenv; 
      systemDeps=[fullSystemDeps
       pkgs.rsync
       pkgs.which
       pkgs.autoconf
       pkgs.automake
       pkgs.libtool
       pkgs.pkg-config 
       pkgs.m4 
       pkgs.perl
       pkgs.cmake 
       pkgs.ninja
       pkgs.gtk-doc
       pkgs.cacert
       basicPythonEnv
       pkgs.gfortran
       ];
    };

    aliphysics = import ./alidist-aliphysics.nix {
      pkgs=pkgs;
      stdenv=pkgs.stdenv; 
      systemDeps=[fullSystemDeps
       pkgs.rsync
       pkgs.which
       pkgs.autoconf
       pkgs.automake
       pkgs.libtool
       pkgs.pkg-config 
       pkgs.m4 
       pkgs.perl
       pkgs.cmake 
       pkgs.ninja
       pkgs.gtk-doc
       pkgs.cacert
       basicPythonEnv
       pkgs.gfortran
       ];
    };

    helpers = import ./alidist-helpers.nix {
      pkgs=pkgs;
      stdenv=pkgs.stdenv;
    };

    pythonEnv = pkgs.python312.withPackages (ps: with ps; [
      (ps.buildPythonPackage rec {
        pname = "alibuild";
        version = "1.17.15";
        src = /Users/ktf/src/alibuild;
        nativeBuildInputs = [ 
          pkgs.python312Packages.setuptools
          pkgs.python312Packages.setuptools_scm
          pkgs.python312Packages.pyyaml
          pkgs.python312Packages.requests
          pkgs.python312Packages.distro
          pkgs.python312Packages.jinja2
          pkgs.python312Packages.boto3
        ];
        format = "pyproject";  # Tell Nix to use `pyproject.toml` instead of `setup.py`
        propagatedBuildInputs = [
          pkgs.python312Packages.pyyaml
          pkgs.python312Packages.requests
        ];
      })
    ]);

    basicPythonEnv = pkgs.python312.withPackages (ps: with ps; [
          pkgs.python312Packages.pip
          pkgs.python312Packages.setuptools
          pkgs.python312Packages.wheel
          pkgs.python312Packages.uproot
          pkgs.python312Packages.scikit-learn
          pkgs.python312Packages.pandas
          pkgs.python312Packages.tensorflow
          pkgs.python312Packages.xgboost
          pkgs.python312Packages.ipython
          pkgs.python312Packages.matplotlib
          pkgs.python312Packages.numpy
          pkgs.python312Packages.scipy
          pkgs.python312Packages.notebook
          pkgs.python312Packages.ipywidgets
          pkgs.python312Packages.metakernel
          pkgs.python312Packages.cython
          pkgs.python312Packages.keras
          pkgs.python312Packages.dask
          pkgs.python312Packages.dask-jobqueue
    ]);
    customLLVM = pkgs.stdenv.mkDerivation {
      name = "customLLVM";
      propagatedBuildInputs = [ 
        pkgs.llvmPackages_18.clang
        pkgs.llvmPackages_18.llvm
      ];
      unpackPhase = "true";
    };
    alidist = pkgs.stdenv.mkDerivation {
      name = "alidist";
      src = /Users/ktf/src/alidist;
      nativeBuildInputs = [ 
        pkgs.rsync
      ];
      installPhase = ''
        rsync -av $src/ $out/ && rsync -av $src/.sl/ $out/.sl/
      '';
    };


    customAbseil = pkgs.stdenv.mkDerivation {
      pname = "customAbseil";
      version = "20250127.0";  # e.g., "refs/tags/21.05" or a commit hash
      # Point the derivation’s source to the flake input
      src = pkgs.fetchFromGitHub {
        owner  = "abseil";   # e.g., "nixos"
        repo   = "abseil-cpp";    # e.g., "nixpkgs"
        rev    = "20250127.0";  # e.g., "refs/tags/21.05" or a commit hash
        sha256 = "sha256-uOgUtF8gaEgcxFK9WAoAhv4GoS8P23IoUxHZZVZdpPk=";
      };

      nativeBuildInputs = [ 
        pkgs.rsync
        pkgs.git
      ];

      # Simple derivation phases, just copying everything to the output
      phases = [ "unpackPhase" "installPhase" ];
      installPhase = ''
        rsync --chown $(whoami) --chmod=Du=rwx,Dg=rx,Do=rx,Fu=rw,Fg=r,Fo=r -av $src/ $out/
        cd $out
        git init
        git add -A .
        git commit -m "Initial commit"
      '';
    };

    o2installation = pkgs.stdenv.mkDerivation {
      name = "o2installation";
      src = ./.;
      configurePhase = "true";
      buildPhase = "true";
      nativeBuildInputs = [ 
        alidist
        pythonEnv
        fullSystemDeps
        pkgs.cmake
        pkgs.ninja
        pkgs.apple-sdk_15
      ];
      propagatedBuildInputs = [ 
        fullSystemDeps
      ];
      installPhase = ''
        export GIT_SSL_NO_VERIFY=true
        mkdir -p $out
        set -e
        cd $out
        export ALIBUILD_ALLOW_SYSTEM_GEANT4=1
        python -m venv $out/venv
        source $out/venv/bin/activate
        alibuild -c ${alidist} -w $out/sw build --defaults o2 --debug arrow
      '';
    };

    apass1_test_dedx_clmask23_srcs = [
          (pkgs.fetchurl {
            # Replace with a real URL
            url = "http://alimonitor.cern.ch/train-workdir/testdata/LFN/alice/data/2024/LHC24ar/560012/apass1_test_dedx_clmask23/0330/o2_ctf_run00560012_orbit0062577312_tf0000861644_epn202/001/AO2D.root";
            sha256 = "sha256-RhybGRmpMkdWBJ3WtqVU91AztsDJP4CkJzysxInB5+w";
          })
          (pkgs.fetchurl {
            url = "http://alimonitor.cern.ch/train-workdir/testdata/LFN/alice/data/2024/LHC24ar/560012/apass1_test_dedx_clmask23/0330/o2_ctf_run00560012_orbit0060940096_tf0000810481_epn050/001/AO2D.root";
            sha256 = "sha256-HVxwMLV6uNHUnRGIE3606BO/XKbkBXRnr7bsrc2xiT0=";
          })
        ];

    apass1_test_dedx_clmask23 = pkgs.stdenv.mkDerivation {
        name = "data/2024/LHC24ar/560012/apass1_test_dedx_clmask23/0330";

        # Each file is fetched separately with pkgs.fetchurl
        srcs = apass1_test_dedx_clmask23_srcs;
        unpackPhase = "true";

        # No build steps needed, so we can skip the default phases
        buildPhase = "true";

        installPhase = ''
          mkdir -p $out
          cp ${pkgs.lib.concatStringsSep " " apass1_test_dedx_clmask23_srcs} $out/
        '';
        # (Optional) You can add meta attributes here
    };

    fairRootBuild = pkgs.mkShell {
      buildInputs = [
        #pythonEnv
        alidist
        #o2installation
        customLLVM
      ];
      propagatedBuildInputs = [ 
        fullSystemDeps
      ];
      shellHook = ''
        #export ALIBUILD_ALLOW_SYSTEM_GEANT4=1
        #source {o2installation}/venv/bin/activate
        #export ALIBUILD_WORK_DIR={self}/sw
        #echo alibuild -c {alidist} -w $out/sw build --defaults o2 --debug FairRoot
      '';
    };

    igorTest = hyperloop.test {
      testId = "0037/00377879"; 
      sha256="sha256-VqXxXswEh0io2d36HUy9JqjmqRXsm1roQZhmDui/Wb0=";
      dataset=apass1_test_dedx_clmask23;
      version="O2Physics/latest";
      tasks = [
        "o2-analysis-detector-occupancy-qa"
        "o2-analysis-timestamp"
        "o2-analysis-event-selection"
        "o2-analysis-multiplicity-table"
        "o2-analysis-centrality-table"
        "o2-analysis-track-propagation"
        "o2-analysis-trackselection"
      ];
    };
  in {
    fullSystemDeps = fullSystemDeps;
    alidist = alidist;
    customLLVM = customLLVM;
    devShells.${system} = {
      default = fairRootBuild;
      issue63046 = pkgs.mkShell {
        buildInputs = [
          pkgs.glew
          pkgs.darwin.apple_sdk.frameworks.CoreFoundation
          pkgs.darwin.objc4
          pkgs.darwin.apple_sdk.frameworks.Cocoa
          pkgs.darwin.apple_sdk.frameworks.OpenGL
          pkgs.darwin.apple_sdk.frameworks.CoreServices
          pkgs.darwin.apple_sdk.frameworks.CoreText
          pkgs.darwin.CoreSymbolication
        ];
      };
    };
    packages.${system} = {
      default = fairRootBuild;
      igorTest = igorTest;
      alisw = alisw;
      aliphysics = aliphysics;
    };
  };
}
