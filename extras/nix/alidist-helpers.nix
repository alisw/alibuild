{stdenv, pkgs}:
let
    scriptLines = {deps}: map
      (k: "${k}*) echo ${deps.${k}} ;;")
      (builtins.attrNames deps);
    o2systemdeps = {deps, name}: stdenv.mkDerivation {
      name = name;
      dontUnpack = true;
      dontBuild = true;
      propagatedBuildInputs = (builtins.attrValues deps);
      installPhase = ''
        mkdir -p $out/bin
        cat <<\EOF > $out/bin/brew
          # Parse command-line options
          while [[ $# -gt 0 ]]; do
            case "$1" in
              --prefix)
                shift
                if [[ $# -eq 0 ]]; then
                  echo "Error: --prefix provided but no value given."
                  exit 1
                fi
                PREFIX_VALUE="$1"
                ;;
              *)
                echo "Warning: Unknown argument '$1'. Ignoring."
                ;;
            esac
            shift
          done
          case $PREFIX_VALUE in
            ${builtins.concatStringsSep "\n    " (scriptLines {deps=deps;})}
            *) echo "Unknown package $PREFIX_VALUE" >&2 ; exit 1;
          esac
        EOF
        chmod +x $out/bin/brew
      '';
    };
in
{
  inherit o2systemdeps;
}
