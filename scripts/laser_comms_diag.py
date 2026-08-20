"""
Why is the Santec not answering? Read-only diagnostic.

Sends nothing but `*IDN?`, which cannot change the instrument's state. Run it
when `p1_laser_check.py` reports no reply, to separate a host-side problem from
a laser-side one.

    python scripts/laser_comms_diag.py --serial COM29

It works through the combinations that could plausibly be wrong -- baud rate,
terminator, flow control -- and then tries the D2XX driver path as well, because
an FTDI device can be reached two ways and only one of them may be wired to the
instrument's firmware.

**Interpreting the result is the point:**

  * **Replies somewhere** -- note the combination and pass it to
    `p1_laser_check.py`.
  * **The port opens but nothing ever replies, on BOTH driver paths** -- the host
    side is fine and the laser is not listening. That is a front-panel setting,
    and the first one to check is the **delimiter**: it is selectable between CR,
    LF, CR+LF and **EOI** (Other tab -> Communication), and EOI is a GPIB-only
    hardware signal that cannot be sent over USB at all. On EOI the laser can
    never see a complete command. Set it to CR.
  * **The port will not open** -- driver or cable. See the VCP install sequence in
    `docs/04-hardware-reference.md`.

Observed 2026-08-14: silence on all 18 serial combinations AND over D2XX, with
the device enumerating cleanly as TSL-775 serial 2601S967 (0x2428:0116) and
flags=0, so nothing else held it. Host side eliminated.
"""

from __future__ import annotations

import argparse
import itertools
import time

TERMINATORS = {"CR": b"\r", "LF": b"\n", "CRLF": b"\r\n"}
BAUDS = (9600, 19200, 38400, 57600, 115200, 230400)
PROBE = b"*IDN?"


def serial_sweep(port: str) -> list:
    import serial

    found = []
    print(f"\n=== serial: does anything arrive unprompted? ===")
    for baud in (9600, 115200):
        try:
            with serial.Serial(port, baud, timeout=1.5) as s:
                time.sleep(1.0)
                data = s.read(4096)
            print(f"  {baud:>7} baud: {len(data)} bytes {data[:60]!r}")
        except Exception as exc:
            print(f"  {baud:>7} baud: {type(exc).__name__}: {exc}")

    print(f"\n=== serial: *IDN? across baud x terminator x flow control ===")
    print(f"{'baud':>7} {'term':>5} {'flow':>5} {'bytes':>6}  raw")
    for (baud, (tname, term)), flow in itertools.product(
            itertools.product(BAUDS, TERMINATORS.items()), (True, False)):
        try:
            with serial.Serial(port, baud, timeout=1.0) as s:
                s.dtr = s.rts = flow
                s.reset_input_buffer()
                s.reset_output_buffer()
                s.write(PROBE + term)
                s.flush()
                time.sleep(0.4)
                data = s.read(4096)
            mark = "  <== REPLY" if data else ""
            if data:
                found.append((f"serial {baud} {tname} flow={flow}", data))
            print(f"{baud:>7} {tname:>5} {str(flow):>5} {len(data):>6}  "
                  f"{data[:40]!r}{mark}")
        except Exception as exc:
            print(f"{baud:>7} {tname:>5} {str(flow):>5} {'--':>6}  "
                  f"{type(exc).__name__}")
    return found


def d2xx_sweep() -> list:
    """
    The other way to reach an FTDI device.

    Worth trying separately: if VCP answers and D2XX does not, or the reverse,
    only one interface is wired to the firmware. If NEITHER answers while the
    device still enumerates, the host side is eliminated.
    """
    found = []
    print("\n=== D2XX: what the other driver path sees ===")
    try:
        import ftd2xx
    except Exception as exc:
        print(f"  ftd2xx not installed ({exc}); skipping. pip install ftd2xx")
        return found
    try:
        n = ftd2xx.createDeviceInfoList()
    except Exception as exc:
        print(f"  enumeration failed: {type(exc).__name__}: {exc}")
        return found
    print(f"  {n} FTDI device(s)")
    for i in range(n):
        try:
            d = ftd2xx.getDeviceInfoDetail(i)
            print(f"  [{i}] desc={d.get('description')!r} "
                  f"serial={d.get('serial')!r} id=0x{d.get('id', 0):08x} "
                  f"flags={d.get('flags')}  (flags=0 means nothing else has it "
                  f"open)")
        except Exception as exc:
            print(f"  [{i}] detail failed: {exc}")
    for i in range(n):
        try:
            h = ftd2xx.open(i)
            h.setBaudRate(9600)
            h.setTimeouts(1500, 1500)
            h.purge()
            h.write(PROBE + b"\r")
            time.sleep(0.5)
            data = h.read(256)
            h.close()
            print(f"  [{i}] *IDN? -> {len(data)} bytes {data[:60]!r}"
                  f"{'  <== REPLY' if data else ''}")
            if data:
                found.append((f"d2xx[{i}]", data))
        except Exception as exc:
            print(f"  [{i}] {type(exc).__name__}: {exc}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--serial", metavar="PORT", default=None,
                    help="serial port to sweep, e.g. COM29")
    ap.add_argument("--skip-d2xx", action="store_true")
    args = ap.parse_args()

    found = []
    if args.serial:
        found += serial_sweep(args.serial)
    if not args.skip_d2xx:
        found += d2xx_sweep()

    print("\n=== verdict ===")
    if found:
        for where, data in found:
            print(f"  REPLY via {where}: {data[:80]!r}")
        print("\n  Use that combination with p1_laser_check.py.")
        return 0

    print("  Nothing replied anywhere.")
    print("  If the port opened and the device enumerated, the HOST SIDE IS FINE")
    print("  and the laser is not listening. Check, in this order:")
    print("    1. Other tab -> Communication -> DELIMITER. If it is set to EOI,")
    print("       that is a GPIB-only signal that cannot be sent over USB, so the")
    print("       laser never sees a complete command. Set it to CR.")
    print("    2. Power-cycle the laser -- clears a stuck REMOTE state.")
    print("    3. Santec's own software: if it connects, the laser IS listening")
    print("       and a setting is wrong on our side. If it does not, it is not us.")
    print("  LAN sidesteps all of this and the transport is already written.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
