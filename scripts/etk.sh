#!/bin/sh
# Run one of the plugin's scripts with the first Python that actually works and is
# 3.12 or newer (see find-python.sh: $ETK_PYTHON, PATH, system paths, pyenv/uv/asdf/mise).
#   etk.sh discover            project snapshot
#   etk.sh run <args...>       ledger: init / check / render / stats / latest
#   etk.sh profile <sub> --data <plugin data dir> [args...]
#                              per-developer workflow profile: path / show / detect / set / unset /
#                              missing / confirm / remember (kept outside the repo)
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
  profile) script="$dir/etk_profile.py" ;;
  *) echo "usage: etk.sh discover | run <args> | exec <gate> --type <t> -- <cmd> | profile <sub> --data <dir>" >&2; exit 2 ;;
esac
if [ "$1" != exec ]; then
  shift
fi
. "$dir/find-python.sh"
if etk_find_python; then
  exec "$ETK_PY" "$script" "$@"
fi
echo "engineering-team: $(etk_python_hint)" >&2
exit 127
