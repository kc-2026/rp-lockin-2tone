"""
Shared scaffolding for the P-series bench scripts. Not a test, not a library.

Five scripts share the same shape -- connect, do a small number of measured
things, print a block that can be pasted into SESSION_LOG.md, and leave the
hardware safe whatever happens. This holds that shape in one place so the
scripts hold only their measurement.

THE SAFETY CONTRACT, which every script here inherits
-----------------------------------------------------
* `session()` disarms both outputs and closes the link on EVERY exit path,
  including an exception and a Ctrl-C. H7.4 was this exact failure in a script.
* Anything that drives an output is behind `require_consent()`, which refuses
  unless the operator passed `--i-am-present` AND typed the confirmation. A
  flag alone is too easy to leave in a shell history.
* Nothing here restarts the board's SCPI server. That is Kevin's, by request.
* Nothing here writes to the laser. The P-series needs only reads from it.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rp_lockin import plan_two_tone_grid  # noqa: E402
from rp_lockin.hardware import RedPitaya  # noqa: E402

PLAN = plan_two_tone_grid(1e6)


def add_common_args(ap, needs_output=False):
    ap.add_argument("--host", default=os.environ.get("RP_HOST",
                                                     "rp-fffe42.local"),
                    help="board hostname (default: $RP_HOST)")
    ap.add_argument("--decimation", type=int, default=8,
                    help="capture decimation (default 8, the settled value)")
    if needs_output:
        ap.add_argument("--i-am-present", action="store_true",
                        help="REQUIRED. This step drives a physical output.")
        ap.add_argument("--yes", action="store_true",
                        help="skip the typed confirmation (scripted runs only)")
    return ap


@contextlib.contextmanager
def session(host: str, what: str):
    """Connect, and guarantee the outputs are off afterwards.

    The disarm is in a finally, not at the end of the happy path, because the
    interesting failures are the ones that raise halfway through.
    """
    banner(what)
    print(f"connecting to {host} ...")
    rp = RedPitaya(host)
    try:
        print(f"  {rp.idn()}")
        yield rp
    finally:
        try:
            rp.close()          # disables both outputs
            print("\noutputs disabled, link closed.")
        except Exception as exc:                        # noqa: BLE001
            print(f"\n!! COULD NOT DISARM CLEANLY: {exc}", file=sys.stderr)
            print("!! CHECK THE OUTPUTS BY HAND BEFORE TOUCHING ANYTHING.",
                  file=sys.stderr)


def require_consent(args, what: str, detail: str) -> None:
    """Refuse to drive an output without a present, consenting operator."""
    print()
    print("=" * 72)
    print(f"THIS DRIVES A PHYSICAL OUTPUT: {what}")
    print(detail)
    print("=" * 72)
    if not getattr(args, "i_am_present", False):
        raise SystemExit(
            "refusing: pass --i-am-present. This step energises hardware and "
            "the docs say it needs somebody in the room."
        )
    if getattr(args, "yes", False):
        print("(--yes given; proceeding without the typed confirmation)")
        return
    try:
        reply = input("type 'drive' to proceed, anything else to stop: ")
    except EOFError:
        raise SystemExit("refusing: no console to confirm on.")
    if reply.strip().lower() != "drive":
        raise SystemExit("stopped at the operator's request.")


def check_helper(rp) -> None:
    """Deep captures need the board-side helper. Fail early and say how."""
    if rp.fast_read_available():
        return
    raise SystemExit(
        "the fast-read helper is not running on the board, so deep captures "
        "will fail.\n"
        "  scp scripts/rp_fastread.py root@<host>:/dev/shm/\n"
        "  ssh -n root@<host> \"nohup setsid python3 /dev/shm/rp_fastread.py "
        "> /dev/shm/rp_fastread.log 2>&1 < /dev/null &\"\n"
        "It lives in /dev/shm, which is RAM, so it is gone after every reboot."
    )


def banner(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


class Results:
    """Collects lines for a block that can be pasted into SESSION_LOG.md.

    Bench numbers that live only in a terminal are lost by the next session,
    and this project's whole continuity is that log.
    """

    def __init__(self, step: str):
        self.step = step
        self.rows: list[tuple[str, str, str]] = []
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")

    def add(self, name: str, value, verdict: str = "") -> None:
        self.rows.append((name, str(value), verdict))
        mark = {"pass": "  OK  ", "fail": " FAIL ", "": "      "}.get(verdict,
                                                                      " ?    ")
        print(f"  [{mark}] {name}: {value}")

    def ok(self, name, value):
        self.add(name, value, "pass")

    def fail(self, name, value):
        self.add(name, value, "fail")

    @property
    def failures(self) -> list:
        return [r for r in self.rows if r[2] == "fail"]

    def report(self) -> str:
        lines = [f"### {self.step} -- run {self.started}", ""]
        for name, value, verdict in self.rows:
            tag = {"pass": "PASS", "fail": "**FAIL**"}.get(verdict, "--")
            lines.append(f"- {tag} {name}: {value}")
        lines.append("")
        lines.append(f"**{len(self.failures)} failure(s) of {len(self.rows)} "
                     f"checks.**")
        return chr(10).join(lines)

    def finish(self) -> int:
        banner(f"{self.step} -- paste this into SESSION_LOG.md")
        print(self.report())
        return 1 if self.failures else 0


def summarise(x: np.ndarray, name: str = "") -> str:
    x = np.asarray(x, dtype=float)
    return (f"{name}n={x.size} min={x.min():.6g} max={x.max():.6g} "
            f"mean={x.mean():.6g} rms={np.sqrt(np.mean(x ** 2)):.6g}")
