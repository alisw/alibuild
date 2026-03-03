{ stdenv, fetchurl, mkShell }:

let
  fetchurlWithAuth = { url, sha256, ... }@attrs:
    fetchurl (attrs // {
      inherit url sha256;
      netrcPhase = ''
        export PATH=/usr/bin:$PATH
        curlOpts="$curlOpts --cert /Users/ktf/.globus/usercert.pem --key /Users/ktf/.globus/userkey.pem"
      '';
  });
  hyperloop = import ./hyperloop.nix {
    stdenv=stdenv; 
    fetchurl=fetchurlWithAuth;
  };
in
# This function returns another function which expects:
#   { testId, sha256 }
  { testId, sha256, dataset, release, script }:
  mkShell {
    buildInputs = [
      (hyperloop.config {testId = "${testId}"; sha256="${sha256}";})
      dataset
    ];
    unpackPhase = "true";
    shellHook = ''
      mkdir -p $out
      find $buildInputs -name "*.root" >$out/input_data.txt
      find $buildInputs -name configuration.json -exec install -m 666 {} $out/ \;
      /Users/ktf/src/alibuild/alienv printenv -w /Users/ktf/src/sw ${release} >$out/environment.sh
      source $out/environment.sh
      cat <<EOF >$out/run.sh
        ${script}
      EOF

      cd $out
    '';
  }
