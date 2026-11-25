"""scripts/selftest.sh must run the tests with Python 3.12+ and say so when there isn't one."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELFTEST = ROOT / "scripts" / "selftest.sh"


def _without_absolute_candidates(text: str) -> str:
    """find-python.sh with the absolute system paths emptied, so the runner's own Python can't be found."""
    return re.sub(r"^ETK_PY_ABS=.*$", 'ETK_PY_ABS=""', text, flags=re.M)


class SelftestPython(unittest.TestCase):
    def test_fails_with_a_clear_message_when_no_python_312(self):
        with tempfile.TemporaryDirectory() as tmp:
            for tool in ("bash", "dirname"):
                (Path(tmp) / tool).symlink_to(shutil.which(tool))
            old = Path(tmp) / "python3"
            old.write_text('#!/bin/sh\nexit 1\n')  # an interpreter that is too old (or broken)
            old.chmod(0o755)
            # A copy without the absolute candidates: on CI runners /usr/bin/python3 or
            # /usr/local/bin/python3 is 3.12+, and the real script would find it outside PATH.
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            script = scripts / "selftest.sh"
            script.write_text(SELFTEST.read_text())
            (scripts / "find-python.sh").write_text(
                _without_absolute_candidates((ROOT / "scripts" / "find-python.sh").read_text()))
            env = {"PATH": tmp, "HOME": tmp}
            r = subprocess.run([str(Path(tmp) / "bash"), str(script)], capture_output=True, text=True, env=env,
                               timeout=60)
        self.assertEqual(r.returncode, 127, r.stdout + r.stderr)
        self.assertIn("Python 3.12+ not found", r.stderr)

    def test_script_picks_the_interpreter_from_the_etk_list(self):
        etk = (ROOT / "scripts" / "etk.sh").read_text()
        selftest = SELFTEST.read_text()
        finder = (ROOT / "scripts" / "find-python.sh").read_text()
        for cand in ("python3", "python3.13", "python3.12", "/usr/bin/python3", "/usr/local/bin/python3",
                     "/opt/homebrew/bin/python3", "python", "ETK_PYTHON", "PYENV_ROOT", "/versions/*/bin/python3", "UV_PYTHON_INSTALL_DIR", ".asdf/installs/python", ".local/share/mise"):
            self.assertIn(cand, finder)
        # every launcher shares the one finder instead of keeping its own list
        for text in (etk, selftest, (ROOT / "hooks" / "run-guard.sh").read_text(),
                     (ROOT / "evals" / "run.sh").read_text()):
            self.assertIn("find-python.sh", text)
            self.assertIn("etk_find_python", text)
        self.assertNotIn("python3 -m unittest", selftest)


if __name__ == "__main__":
    unittest.main()
