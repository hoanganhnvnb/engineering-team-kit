#!/bin/sh
# Entry point for the PreToolUse hook. Cheap exit for anything that isn't an
# engineering-team subagent, so the main session never pays for a Python start.
input=$(cat)
case "$input" in
  *'"agent_type"'*'engineering-team:'*) ;;
  *) exit 0 ;;
esac
here=$(dirname "$0")
. "$here/../scripts/find-python.sh" || exit 2
if etk_find_python; then
  printf '%s' "$input" | "$ETK_PY" "$here/guard.py"
  rc=$?
  case $rc in
    0|2) exit $rc ;;
  esac
  echo "[engineering-team guard] guard error (exit $rc); blocking this call" >&2
  exit 2
fi
echo "[engineering-team guard] engineering-team needs Python 3.12+ for its guard; install it or disable the plugin. $(etk_python_hint)" >&2
exit 2
