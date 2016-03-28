# Source this file from your .bashrc, .zshrc or .kshrc.
# Do not forget to export ALICE_WORK_PREFIX first.
if test -z "$ALICE_WORK_PREFIX"; then
  echo "Export ALICE_WORK_PREFIX to make the alienv shortcut work." >&2
else
  alienv() {
    for A in "$@"; do
      if ! test `echo "$A" | cut -b1` = -; then
        if test "$A" = load || test "$A" = unload; then
          unset A
          eval `$ALICE_WORK_PREFIX/alibuild/alienv -w $ALICE_WORK_PREFIX/sw "$@"`
          return $?
        else
          break
        fi
      elif test "$A" = -c; then
        break
      fi
    done
    unset A
    $ALICE_WORK_PREFIX/alibuild/alienv -w $ALICE_WORK_PREFIX/sw "$@"
  }
fi
