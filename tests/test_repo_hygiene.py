"""
No stray control characters in tracked text files.

This exists because it has happened four times, always the same way: an edit
script writes a Windows path or an escape sequence through another layer of
string processing, and a backslash escape is interpreted instead of being
written.

  * `\\0000` inside a Python string is an OCTAL escape and wrote a NUL byte,
    turning two documents binary.
  * `\\r` in "identical `\\r` delimiter" wrote a CARRIAGE RETURN into a
    markdown table.
  * `\\n` in an f-string wrote a real newline and broke the file's syntax.
  * `scripts\\bench.py` in a .cmd file wrote a BACKSPACE, silently turning it
    into "scriptsench.py" -- a launcher that looked right in a diff and could
    not possibly work.

The first three were caught by hand. The fourth was not, because the check
being used only looked for NUL and CR. Nobody notices a backspace by reading.

Text files have no business containing control characters other than tab and
newline, so this checks for all of them at once rather than for whichever one
went wrong last.
"""

import io
import os
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")

# Tab, LF and CR are legitimate. Everything else below 0x20, plus DEL, is not.
ALLOWED = {0x09, 0x0A, 0x0D}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".cmd", ".sh",
                 ".yml", ".yaml", ".json", ".gitignore", ".gitattributes"}


def tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):        # pragma: no cover
        pytest.skip("not a git checkout")
    for rel in out.split("\n"):
        rel = rel.strip()
        if not rel:
            continue
        suffix = os.path.splitext(rel)[1].lower()
        if suffix in TEXT_SUFFIXES or os.path.basename(rel).startswith("."):
            path = os.path.join(ROOT, rel)
            if os.path.isfile(path):
                yield rel, path


def test_no_stray_control_characters_in_tracked_text():
    bad = []
    for rel, path in tracked_text_files():
        data = io.open(path, "rb").read()
        for i, byte in enumerate(data):
            if byte < 0x20 and byte not in ALLOWED or byte == 0x7F:
                line = data[:i].count(b"\n") + 1
                context = data[max(0, i - 40):i + 40]
                bad.append(f"{rel}:{line} byte 0x{byte:02x} near "
                           f"{context!r}")
                break
    assert not bad, ("control characters in text files -- almost certainly a "
                     "backslash escape interpreted by a scripting layer:\n  "
                     + "\n  ".join(bad))


def test_no_lone_carriage_returns():
    """A CR that is not part of CRLF. Its own failure mode: it overwrites the
    start of the line in a terminal, so the text LOOKS truncated rather than
    corrupted, and a diff shows nothing obviously wrong."""
    bad = []
    for rel, path in tracked_text_files():
        data = io.open(path, "rb").read()
        if data.count(b"\r") - data.count(b"\r\n"):
            bad.append(rel)
    assert not bad, f"lone CR in: {bad}"


def test_the_launchers_point_at_files_that_exist():
    """The backspace incident produced a launcher naming "scriptsench.py".
    It parsed, it looked plausible, and no test would have run it."""
    import re
    for name in ("run_gui.cmd", "run_bench.cmd"):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        text = io.open(path, encoding="utf-8").read()
        for match in re.findall(r'"(scripts[\\/][A-Za-z0-9_.-]+\.py)"', text):
            target = os.path.join(ROOT, match.replace("\\", os.sep))
            assert os.path.isfile(target), \
                f"{name} launches {match!r}, which does not exist"
