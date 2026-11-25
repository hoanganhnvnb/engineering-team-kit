# Sourced by etk.sh, hooks/run-guard.sh, scripts/selftest.sh and evals/run.sh (not run on its own).
# `etk_find_python` sets ETK_PY to the first interpreter that runs and is 3.12 or newer, or returns 1.
# Each candidate is tried before use: a `python3` on PATH can be a broken shim (pyenv/asdf without
# its root, a deleted venv) or an old system Python.
#
# Order: $ETK_PYTHON (yours, when set), names on PATH, system locations, then the folders that
# pyenv, uv, asdf and mise install into, which are not on PATH when a shim points at another version
# ($PYENV_ROOT and $UV_PYTHON_INSTALL_DIR are honoured when set).
# Only your own home folder and system paths are searched, never the project.
ETK_PY_NAMES="python3 python3.13 python3.12 python"
ETK_PY_ABS="/usr/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3"

# The interpreter must say so itself: an exit status alone would let `true` pass.
etk_py_ok() {
  [ "$("$1" -c 'import sys; print("etk-ok" if sys.version_info >= (3, 12) else "")' 2>/dev/null)" = etk-ok ]
}

etk_try() {
  [ -n "$1" ] && etk_py_ok "$1" && ETK_PY=$1
}

etk_find_python() {
  ETK_PY=""
  # Overrides count only as absolute paths; a relative one would resolve inside the project.
  case ${ETK_PYTHON:-} in /*) etk_try "$ETK_PYTHON" && return 0 ;; esac
  for c in $ETK_PY_NAMES $ETK_PY_ABS; do
    etk_try "$c" && return 0
  done
  h=${HOME:-/nonexistent}
  pyenv=$h/.pyenv
  uvdir=$h/.local/share/uv/python
  case ${PYENV_ROOT:-} in /*) pyenv=$PYENV_ROOT ;; esac
  case ${UV_PYTHON_INSTALL_DIR:-} in /*) uvdir=$UV_PYTHON_INSTALL_DIR ;; esac
  for c in "$pyenv"/versions/*/bin/python3 "$uvdir"/*/bin/python3 \
           "$h"/.asdf/installs/python/*/bin/python3 "$h"/.local/share/mise/installs/python/*/bin/python3 \
           "$h"/.local/bin/python3.12; do
    etk_try "$c" && return 0
  done
  return 1
}

etk_python_hint() {
  echo "Python 3.12+ not found. Install one (macOS: brew install python@3.12; Debian/Ubuntu: sudo apt install python3.12; any OS: uv python install 3.12 or pyenv install 3.12), or set ETK_PYTHON=/path/to/python3.12."
}
