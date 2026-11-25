#!/bin/sh
# Entry point for the PreToolUse hook. Cheap exit for anything that isn't an
# engineering-team subagent, so the main session never pays for a Python start.
input=$(cat)
case "$input" in
  *'"agent_type"'*'engineering-team:'*) ;;
  *) exit 0 ;;
esac
for py in python3 /usr/bin/python3 /usr/local/bin/python3 python; do
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    printf '%s' "$input" | "$py" "$(dirname "$0")/guard.py"
    rc=$?
    case $rc in
      0|2) exit $rc ;;
    esac
    echo "[engineering-team guard] guard error (exit $rc); blocking this call" >&2
    exit 2
  fi
done
echo "[engineering-team guard] python not found; guard inactive for this call" >&2
exit 0
