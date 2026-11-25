"""scripts/selftest.sh must run the tests with Python 3.12+ and say so when there isn't one."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELFTEST = ROOT / "scripts" / "selftest.sh"


def _path_candidates_only(text: str) -> str:
    """selftest.sh with only the PATH-relative interpreter names left in `candidates`."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("candidates="):
            names = line.split("=", 1)[1].strip().strip('"').split()
            line = 'candidates="' + " ".join(n for n in names if not n.startswith("/")) + '"\n'
        out.append(line)
    return "".join(out)


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
            script = Path(tmp) / "scripts" / "selftest.sh"
            script.parent.mkdir()
            text = SELFTEST.read_text()
            script.write_text(_path_candidates_only(text))
            self.assertNotIn("/usr/bin/python3", script.read_text())
            env = {"PATH": tmp, "HOME": tmp}
            r = subprocess.run([str(Path(tmp) / "bash"), str(script)], capture_output=True, text=True, env=env,
                               timeout=60)
        self.assertEqual(r.returncode, 127, r.stdout + r.stderr)
        self.assertIn("Python 3.12+ not found", r.stderr)

    def test_script_picks_the_interpreter_from_the_etk_list(self):
        etk = (ROOT / "scripts" / "etk.sh").read_text()
        selftest = SELFTEST.read_text()
        for cand in ("python3", "python3.13", "python3.12", "/usr/bin/python3", "/usr/local/bin/python3",
                     "/opt/homebrew/bin/python3", "python"):
            self.assertIn(cand, etk)
            self.assertIn(cand, selftest)
        self.assertNotIn("python3 -m unittest", selftest)


if __name__ == "__main__":
    unittest.main()
