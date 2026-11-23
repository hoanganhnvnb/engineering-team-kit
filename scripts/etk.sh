#!/bin/sh
# Run one of the plugin's scripts with the first Python that actually works.
# A `python3` on PATH can be a broken shim (pyenv/asdf without its root, a
# deleted venv), so each candidate is tried before it's used.
#   etk.sh discover            project snapshot
#   etk.sh run <args...>       ledger: init / check / render / stats / latest
dir=$(dirname "$0")
case "$1" in
  discover) script="$dir/discover.py" ;;
  run) script="$dir/etk_run.py" ;;
  *) echo "usage: etk.sh discover | run <args>" >&2; exit 2 ;;
esac
shift
for py in python3 /usr/bin/python3 /usr/local/bin/python3 python; do
  if "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
    exec "$py" "$script" "$@"
  fi
done
echo "engineering-team: no working Python 3.8+ found (tried python3, /usr/bin/python3, /usr/local/bin/python3, python)" >&2
exit 127
