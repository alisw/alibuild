{ pkgs, stdenv, fetchurl, mkShell }:

# This function returns another function which expects:
#   { testId, sha256 }
let
  config = { testId, sha256 }:

    stdenv.mkDerivation {
      name = "hyperloop-config-${builtins.replaceStrings [ "/" ] [ "_" ] testId}";

      srcs = [(fetchurl {
        url = "http://alimonitor.cern.ch/train-workdir/tests/${testId}/configuration.json";
        sha256 = sha256;
      })
      ];
      unpackPhase = "true";
      buildPhase = "true";

      installPhase = ''
        mkdir -p $out
        cp $srcs $out/configuration.json
      '';
    };

  modules = stdenv.mkDerivation {
      name = "environment-modules";
      srcs = [(pkgs.fetchurl {
        url = "https://github.com/envmodules/modules/releases/download/v5.5.0/modules-5.5.0.tar.gz";
        sha256 = "sha256-rQ42DHrcJRWpmDaGPZhJmzrYnNdUhiVJmyApOEWwQMs=";
      })];
      buildInputs = [ pkgs.autoconf 
        pkgs.tcl
      ];
      configurePhase = ''
        ./configure --prefix $out --with-tcl=${pkgs.tcl}/lib
      '';
      buildPhase = ''
        make -j 20
      '';
      installPhase = ''
        make install
      '';
  };

  release = { version }:
    stdenv.mkDerivation {
      name = "hyperloop-release-${builtins.replaceStrings ["/"] ["_"] version}";
      buildInputs = [ modules pkgs.direnv];

      unpackPhase = "true";
      installPhase = ''
        mkdir -p $out
        #WORK_DIR=/Users/ktf/src/sw source "/Users/ktf/src/sw/osx_arm64/${version}/etc/profile.d/init.sh"
        #env >$out/env.sh
      '';
    };

  test = { testId, sha256, dataset, version, script, tasks }:
    mkShell {
      buildInputs = [
        (config {testId = "${testId}"; sha256="${sha256}";})
        dataset
        (release {version = version;})
      ];
      propagatedBuildInputs = [
      ];
      nativeBuildInputs = [
      ];
      unpackPhase = "true";
      shellHook = ''
        mkdir -p $out
        TEST_DIR=/Users/ktf/src/sw/BUILD/O2Physics-latest/O2Physics/
        find $buildInputs -name "*.root" >$out/input_data.txt
        find $buildInputs -name configuration.json -exec install -m 660 {} $out/ \;
        set -x
        cat <<EOF >$out/run.sh
          ${builtins.concatStringsSep " | \\\\\n" (builtins.map (task: "stage/bin/${task} --configuration json://configuration.json") tasks)} --aod-file @input_data.txt
        EOF
        cat <<EOF >$out/build.sh
          ${builtins.concatStringsSep "\n" (builtins.map (task: "ninja stage/bin/${task}") tasks)}
        EOF
        chmod +x $out/run.sh
        cp $out/input_data.txt $TEST_DIR/
        cp $out/run.sh $TEST_DIR/
        cp $out/build.sh $TEST_DIR/
        cp $out/configuration.json $TEST_DIR/
      '';
    };
in
{
  inherit config test release;
}
