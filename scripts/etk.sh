#!/bin/sh
# Run one of the plugin's scripts with the first Python that actually works.
# A `python3` on PATH can be a broken shim (pyenv/asdf without its root, a
# deleted venv), so each candidate is tried before it's used.
#   etk.sh discover            project snapshot
#   etk.sh run <args...>       ledger: init / check / render / stats / latest
#   etk.sh exec <gate> --type <t> -- <cmd...>
#                              run a command and record its real exit code in the ledger
# `exec` is its own entry point on purpose: the skills pre-approve `etk.sh run:*`, and a
# pre-approved `run exec` would let any command skip the permission prompt.
dir=$(dirname "$0")
case "$1" in
  discover) script="$dir/discover.py" ;;
  run)
    if [ "${2:-}" = exec ]; then
      echo "use \`etk.sh exec ...\`, not \`etk.sh run exec ...\`" >&2
      exit 2
    fi
    script="$dir/etk_run.py" ;;
  exec) script="$dir/etk_run.py" ;;
  *) echo "usage: etk.sh discover | run <args> | exec <gate> --type <t> -- <cmd>" >&2; exit 2 ;;
esac
if [ "$1" != exec ]; then
  shift
fi
for py in python3 /usr/bin/python3 /usr/local/bin/python3 python; do
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    exec "$py" "$script" "$@"
  fi
done
echo "engineering-team: no working Python 3.8+ found (tried python3, /usr/bin/python3, /usr/local/bin/python3, python)" >&2
exit 127
