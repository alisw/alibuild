# Source this file from your .bashrc, .zshrc or .kshrc.
# Do not forget to export ALICE_WORK_DIR first.
alienv() {
  if test -z "$ALICE_WORK_DIR"; then
    echo "Export ALICE_WORK_DIR to make the alienv shortcut work." >&2
    return 1
  fi
  ALICE_ALIENV__="$ALICE_ALIENV"
  if test -z "$ALICE_ALIENV__"; then
    ALICE_ALIENV__=`unset alienv; type -p alienv 2> /dev/null`
    test -z "$ALICE_ALIENV__" && ALICE_ALIENV__="$ALICE_WORK_DIR/../alibuild/alienv"
  fi
  for A in "$@"; do
    if ! test `echo "$A" | cut -b1` = -; then
      if test "$A" = load || test "$A" = unload; then
        unset A
        eval `"$ALICE_ALIENV__" -w "$ALICE_WORK_DIR" "$@"`
        return $?
      else
        break
      fi
    elif test "$A" = -c; then
      break
    fi
  done
  unset A
  "$ALICE_ALIENV__" -w "$ALICE_WORK_DIR" "$@"
}
