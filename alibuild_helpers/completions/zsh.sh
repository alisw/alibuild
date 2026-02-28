#compdef aliBuild alienv

# Zsh completion for alibuild commands:
#   aliBuild, alienv
#
# Installation:
#   Copy this file to a directory in your $fpath, e.g.:
#     mkdir -p ~/.zsh/completions
#     cp _aliBuild ~/.zsh/completions/
#     # Add to .zshrc: fpath=(~/.zsh/completions $fpath)
#   Then restart your shell or run: autoload -Uz compinit && compinit
#
#   Alternatively, if aliBuild is installed:
#     eval "$(aliBuild completion zsh)"

# ---------------------------------------------------------------------------
# Helper: complete package names from the config directory (alidist/*.sh)
# ---------------------------------------------------------------------------
_alibuild_packages() {
  local config_dir="${opt_args[-c]:-${opt_args[--config-dir]:-alidist}}"
  local -a packages files
  if [[ -d "$config_dir" ]]; then
    files=( "$config_dir"/"${PREFIX:l}"*.sh(N) )
    files=( ${files:#*defaults-*} )
    (( $#files )) && packages=( ${(f)"$(awk '
      /^package:/ { sub(/^package: */, ""); print; nextfile }
    ' "${files[@]}")"} )
  fi
  _describe -t packages 'package' packages "$@"
}

# ---------------------------------------------------------------------------
# Helper: complete defaults names from the config directory
# ---------------------------------------------------------------------------
_alibuild_defaults() {
  local config_dir="${opt_args[-c]:-${opt_args[--config-dir]:-alidist}}"
  local -a defaults
  if [[ -d "$config_dir" ]]; then
    defaults=( "$config_dir"/defaults-*.sh(N:t:r) )
    defaults=( ${defaults#defaults-} )
  fi
  _describe -t defaults 'default' defaults "$@"
}

# ---------------------------------------------------------------------------
# Subcommand option sets
# ---------------------------------------------------------------------------

_aliBuild_cmd_build() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Build as if on the specified architecture]:architecture: ' \
    '--defaults[Use defaults from CONFIGDIR/defaults-DEFAULT.sh]:default:_alibuild_defaults' \
    '--force-unknown-architecture[Build even without a supported architecture]' \
    '(-z --devel-prefix)'{-z,--devel-prefix}'[Version name for development packages]:prefix: ' \
    '*-e[KEY=VALUE to add to the build environment]:env binding: ' \
    '(-j --jobs)'{-j,--jobs}'[Number of parallel compilation processes]:jobs: ' \
    '(-u --fetch-repos)'{-u,--fetch-repos}'[Fetch updates to repositories in MIRRORDIR]' \
    '*--no-local[Do not pick up package from local checkout]:package:_alibuild_packages' \
    '--force-tracked[Do not pick up any packages from a local checkout]' \
    '--plugin[Plugin to use for the actual build]:plugin: ' \
    '*--disable[Do not build package and its unique dependencies]:package:_alibuild_packages' \
    '*--force-rebuild[Always rebuild package from scratch]:package:_alibuild_packages' \
    '*--annotate[Store comment in build metadata for package]:PACKAGE=COMMENT: ' \
    '--only-deps[Only build dependencies, not the main package]' \
    '--docker[Build inside a Docker container]' \
    '--docker-image[Docker image to build inside of]:image: ' \
    '--docker-extra-args[Arguments to pass to docker run]:args: ' \
    '*-v[Additional volume to mount inside Docker container]:volume: ' \
    '--no-remote-store[Disable the use of the remote store]' \
    '--remote-store[Where to find prebuilt tarballs to reuse]:store: ' \
    '--write-store[Where to upload newly built packages]:store: ' \
    '--insecure[Do not validate TLS certificates for remote store]' \
    '(-C --chdir)'{-C,--chdir}'[Change to directory before building]:directory:_directories' \
    '(-w --work-dir)'{-w,--work-dir}'[Toplevel directory for builds]:directory:_directories' \
    '(-c --config-dir)'{-c,--config-dir}'[Directory containing build recipes]:directory:_directories' \
    '--reference-sources[Directory for reference git repositories]:directory:_directories' \
    '--aggressive-cleanup[Delete as much build data as possible when cleaning up]' \
    '--no-auto-cleanup[Do not clean up build directories automatically]' \
    '(--no-system)--always-prefer-system[Always use system packages when compatible]' \
    '(--always-prefer-system)--no-system[Never use system packages]::packages: ' \
    '*:package:_alibuild_packages'
}

_aliBuild_cmd_clean() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Clean up build results for this architecture]:architecture: ' \
    '--aggressive-cleanup[Delete as much build data as possible when cleaning up]' \
    '(-C --chdir)'{-C,--chdir}'[Change to directory before cleaning up]:directory:_directories' \
    '(-w --work-dir)'{-w,--work-dir}'[Toplevel directory used in previous builds]:directory:_directories'
}

_aliBuild_cmd_deps() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Resolve dependencies as if on the specified architecture]:architecture: ' \
    '--defaults[Use defaults from CONFIGDIR/defaults-DEFAULT.sh]:default:_alibuild_defaults' \
    '*--disable[Assume not building package and its dependencies]:package:_alibuild_packages' \
    '*-e[KEY=VALUE to add to the environment]:env binding: ' \
    '--neat[Produce a graph with transitive reduction]' \
    '--outdot[Keep intermediate Graphviz dot file]:file:_files' \
    '--outgraph[Store final output PDF file]:file:_files' \
    '--docker[Check system packages inside a Docker container]' \
    '--docker-image[Docker image to use]:image: ' \
    '--docker-extra-args[Arguments to pass to docker run]:args: ' \
    '(-c --config-dir)'{-c,--config-dir}'[Directory containing build recipes]:directory:_directories' \
    '(--no-system)--always-prefer-system[Always use system packages when compatible]' \
    '(--always-prefer-system)--no-system[Never use system packages]::packages: ' \
    ':package:_alibuild_packages'
}

_aliBuild_cmd_doctor() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Resolve requirements as if on the specified architecture]:architecture: ' \
    '--defaults[Use defaults from CONFIGDIR/defaults-DEFAULT.sh]:default:_alibuild_defaults' \
    '*--disable[Assume not building package and its dependencies]:package:_alibuild_packages' \
    '*-e[KEY=VALUE to add to the build environment]:env binding: ' \
    '--docker[Check system packages inside a Docker container]' \
    '--docker-image[Docker image to use]:image: ' \
    '--docker-extra-args[Arguments to pass to docker run]:args: ' \
    '--no-remote-store[Disable the use of the remote store]' \
    '--remote-store[Where to find prebuilt tarballs to reuse]:store: ' \
    '--write-store[Where to upload newly built packages]:store: ' \
    '--insecure[Do not validate TLS certificates for remote store]' \
    '(-C --chdir)'{-C,--chdir}'[Change to directory before doing anything]:directory:_directories' \
    '(-w --work-dir)'{-w,--work-dir}'[Toplevel directory for builds]:directory:_directories' \
    '(-c --config)'{-c,--config}'[Directory containing build recipes]:directory:_directories' \
    '(--no-system)--always-prefer-system[Always use system packages when compatible]' \
    '(--always-prefer-system)--no-system[Never use system packages]::packages: ' \
    '*:package:_alibuild_packages'
}

_aliBuild_cmd_init() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Parse defaults using the specified architecture]:architecture: ' \
    '--defaults[Use defaults from CONFIGDIR/defaults-DEFAULT.sh]:default:_alibuild_defaults' \
    '(-z --devel-prefix)'{-z,--devel-prefix}'[Directory to clone the recipe repository into]:prefix: ' \
    '--dist[Download the given repository of build recipes]:[USER/REPO@]BRANCH: ' \
    '(-C --chdir)'{-C,--chdir}'[Change to directory before doing anything]:directory:_directories' \
    '(-w --work-dir)'{-w,--work-dir}'[Toplevel directory for builds]:directory:_directories' \
    '(-c --config-dir)'{-c,--config-dir}'[Directory where build recipes will be placed]:directory:_directories' \
    '--reference-sources[Directory for reference git repositories]:directory:_directories' \
    '::package:_alibuild_packages'
}

_aliBuild_cmd_analytics() {
  _arguments -s -S \
    ':state:(on off)'
}

_aliBuild_cmd_architecture() {
  _arguments -s -S
}

_aliBuild_cmd_version() {
  _arguments -s -S \
    '(-a --architecture)'{-a,--architecture}'[Display the specified architecture next to the version]:architecture: '
}

_aliBuild_cmd_completion() {
  _arguments -s -S \
    ':shell:(bash zsh)'
}

# ---------------------------------------------------------------------------
# Main aliBuild / pb completion
# ---------------------------------------------------------------------------
_aliBuild() {
  local curcontext="$curcontext" state state_descr line
  typeset -A opt_args

  _arguments -s -S -C \
    '(-d --debug)'{-d,--debug}'[Enable debug log output]' \
    '(-n --dry-run)'{-n,--dry-run}'[Print what would happen without doing it]' \
    '(-): :->command' \
    '(-)*:: :->option-or-argument' && return

  case "$state" in
    (command)
      local -a commands=(
        'build:Build the specified package'
        'clean:Clean up build artifacts'
        'deps:Show dependency tree for a package'
        'doctor:Check system requirements for a package'
        'init:Initialise a local development area'
        'analytics:Turn analysis data reporting on or off'
        'architecture:Display detected architecture'
        'version:Display aliBuild version'
        'completion:Output shell completion code'
      )
      _describe -t commands 'aliBuild command' commands && return
      ;;
    (option-or-argument)
      curcontext=${curcontext%:*:*}:aliBuild-$words[1]:
      local cmd="_aliBuild_cmd_${words[1]}"
      if (( $+functions[$cmd] )); then
        $cmd
      else
        _message "unknown command: $words[1]"
      fi
      ;;
  esac
}

# ---------------------------------------------------------------------------
# alienv completion
# ---------------------------------------------------------------------------
_alienv() {
  local curcontext="$curcontext" state state_descr line
  typeset -A opt_args

  _arguments -s -S -C \
    '(-a --architecture)'{-a,--architecture}'[Set architecture]:architecture: ' \
    '(-w --work-dir)'{-w,--work-dir}'[Set work directory]:directory:_directories' \
    '--no-refresh[Skip refreshing the modules directory]' \
    '-q[Quiet mode]' \
    '--shellrc[Retain shell startup files]' \
    '--dev[Add environment variables for development]' \
    '(-): :->command' \
    '(-)*:: :->option-or-argument' && return

  case "$state" in
    (command)
      local -a commands=(
        'enter:Enter new shell with modules loaded'
        'setenv:Execute command with environment defined by modules'
        'printenv:Print environment for modules'
        'load:Print environment for modules (alias for printenv)'
        'unload:Print environment for unloading modules'
        'q:List modules matching a pattern'
        'query:List modules matching a pattern'
        'list:List loaded modules'
        'avail:List all available modules'
        'modulecmd:Pass arguments to modulecmd'
        'shell-helper:Return shell initialization script'
        'help:Display help'
      )
      _describe -t commands 'alienv command' commands && return
      ;;
    (option-or-argument)
      case "$words[1]" in
        enter|setenv|printenv|load|unload)
          _message 'MODULE1[,MODULE2...]'
          ;;
        q|query)
          _message 'regexp pattern'
          ;;
        modulecmd)
          _message 'modulecmd arguments'
          ;;
        *)
          _default
          ;;
      esac
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Register completions
# ---------------------------------------------------------------------------
case "$service" in
  aliBuild) _aliBuild "$@" ;;
  alienv)   _alienv "$@" ;;
esac
