# Bash completion for alibuild commands:
#   aliBuild, alienv
#
# Installation:
#   eval "$(aliBuild completion bash)"

# ---------------------------------------------------------------------------
# Helper: complete package names from the config directory (alidist/*.sh)
# ---------------------------------------------------------------------------
_alibuild_packages() {
  local config_dir="${ALIBUILD_CONFIG_DIR:-alidist}"
  if [[ -d "$config_dir" ]]; then
    COMPREPLY+=( $(awk '
      FILENAME ~ /\/defaults-/ { nextfile }
      /^package:/ { sub(/^package: */, ""); print; nextfile }
    ' "$config_dir"/"${cur,,}"*.sh 2>/dev/null) )
  fi
}

# ---------------------------------------------------------------------------
# Helper: complete defaults names from the config directory
# ---------------------------------------------------------------------------
_alibuild_defaults() {
  local config_dir="${ALIBUILD_CONFIG_DIR:-alidist}"
  if [[ -d "$config_dir" ]]; then
    local -a defaults
    defaults=( "$config_dir"/defaults-*.sh )
    defaults=( "${defaults[@]##*/}" )
    defaults=( "${defaults[@]%.sh}" )
    defaults=( "${defaults[@]#defaults-}" )
    COMPREPLY+=( $(compgen -W "${defaults[*]}" -- "$cur") )
  fi
}

# ---------------------------------------------------------------------------
# aliBuild / pb completion
# ---------------------------------------------------------------------------
_aliBuild_complete() {
  local cur prev words cword
  _init_completion || return

  # Track the config dir if -c/--config-dir was given
  local i
  for (( i=1; i < cword; i++ )); do
    case "${words[i]}" in
      -c|--config-dir|--config)
        ALIBUILD_CONFIG_DIR="${words[i+1]}"
        ;;
    esac
  done

  # Find the subcommand
  local subcmd=""
  for (( i=1; i < cword; i++ )); do
    case "${words[i]}" in
      build|clean|deps|doctor|init|analytics|architecture|version|completion)
        subcmd="${words[i]}"
        break
        ;;
    esac
  done

  # Complete global options or subcommand name
  if [[ -z "$subcmd" ]]; then
    COMPREPLY=( $(compgen -W "
      -d --debug -n --dry-run
      build clean deps doctor init analytics architecture version completion
    " -- "$cur") )
    return
  fi

  # Complete subcommand-specific options
  case "$subcmd" in
    build)
      case "$prev" in
        -a|--architecture|-z|--devel-prefix|-e|-j|--jobs|--plugin|--docker-image|--docker-extra-args|-v|--remote-store|--write-store)
          return ;;
        --defaults)
          _alibuild_defaults; return ;;
        --no-local|--disable|--force-rebuild)
          _alibuild_packages; return ;;
        --annotate)
          return ;;
        -C|--chdir|-w|--work-dir|-c|--config-dir|--reference-sources)
          _filedir -d; return ;;
      esac
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "
          -a --architecture --defaults --force-unknown-architecture
          -z --devel-prefix -e -j --jobs -u --fetch-repos
          --no-local --force-tracked --plugin --disable --force-rebuild
          --annotate --only-deps
          --docker --docker-image --docker-extra-args -v
          --no-remote-store --remote-store --write-store --insecure
          -C --chdir -w --work-dir -c --config-dir --reference-sources
          --aggressive-cleanup --no-auto-cleanup
          --always-prefer-system --no-system
        " -- "$cur") )
      else
        _alibuild_packages
      fi
      ;;
    clean)
      case "$prev" in
        -a|--architecture) return ;;
        -C|--chdir|-w|--work-dir) _filedir -d; return ;;
      esac
      COMPREPLY=( $(compgen -W "
        -a --architecture --aggressive-cleanup -C --chdir -w --work-dir
      " -- "$cur") )
      ;;
    deps)
      case "$prev" in
        -a|--architecture|-e|--docker-image|--docker-extra-args)
          return ;;
        --defaults)
          _alibuild_defaults; return ;;
        --disable)
          _alibuild_packages; return ;;
        --outdot|--outgraph)
          _filedir; return ;;
        -c|--config-dir)
          _filedir -d; return ;;
      esac
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "
          -a --architecture --defaults --disable -e
          --neat --outdot --outgraph
          --docker --docker-image --docker-extra-args
          -c --config-dir
          --always-prefer-system --no-system
        " -- "$cur") )
      else
        _alibuild_packages
      fi
      ;;
    doctor)
      case "$prev" in
        -a|--architecture|-e|--docker-image|--docker-extra-args|--remote-store|--write-store)
          return ;;
        --defaults)
          _alibuild_defaults; return ;;
        --disable)
          _alibuild_packages; return ;;
        -C|--chdir|-w|--work-dir|-c|--config)
          _filedir -d; return ;;
      esac
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "
          -a --architecture --defaults --disable -e
          --docker --docker-image --docker-extra-args
          --no-remote-store --remote-store --write-store --insecure
          -C --chdir -w --work-dir -c --config
          --always-prefer-system --no-system
        " -- "$cur") )
      else
        _alibuild_packages
      fi
      ;;
    init)
      case "$prev" in
        -a|--architecture|--dist|-z|--devel-prefix)
          return ;;
        --defaults)
          _alibuild_defaults; return ;;
        -C|--chdir|-w|--work-dir|-c|--config-dir|--reference-sources)
          _filedir -d; return ;;
      esac
      if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "
          -a --architecture --defaults -z --devel-prefix --dist
          -C --chdir -w --work-dir -c --config-dir --reference-sources
        " -- "$cur") )
      else
        _alibuild_packages
      fi
      ;;
    analytics)
      COMPREPLY=( $(compgen -W "on off" -- "$cur") )
      ;;
    architecture)
      ;;
    version)
      COMPREPLY=( $(compgen -W "-a --architecture" -- "$cur") )
      ;;
    completion)
      COMPREPLY=( $(compgen -W "bash zsh" -- "$cur") )
      ;;
  esac
}

# ---------------------------------------------------------------------------
# alienv completion
# ---------------------------------------------------------------------------
_alienv_complete() {
  local cur prev words cword
  _init_completion || return

  # Find the subcommand
  local subcmd=""
  local i
  for (( i=1; i < cword; i++ )); do
    case "${words[i]}" in
      enter|setenv|printenv|load|unload|q|query|list|avail|modulecmd|shell-helper|help)
        subcmd="${words[i]}"
        break
        ;;
    esac
  done

  if [[ -z "$subcmd" ]]; then
    case "$prev" in
      -a|--architecture) return ;;
      -w|--work-dir) _filedir -d; return ;;
    esac
    COMPREPLY=( $(compgen -W "
      -a --architecture -w --work-dir --no-refresh -q --shellrc --dev
      enter setenv printenv load unload q query list avail modulecmd shell-helper help
    " -- "$cur") )
  fi
}

# ---------------------------------------------------------------------------
# Register completions
# ---------------------------------------------------------------------------
complete -F _aliBuild_complete aliBuild
complete -F _alienv_complete alienv
