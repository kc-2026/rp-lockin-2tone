#!/usr/bin/env python3
"""
Fast read-out of the Red Pitaya's capture buffer. RUNS ON THE BOARD.

This is the one piece of this project that does not run on the control PC, and
it exists for one measured reason: the SCPI server delivers deep-memory blocks
at 5.7 MB/s, while a raw socket from the board's RAM to the control PC manages
87 MB/s over the same cable. A 477 MB sweep is 84 s the first way and 5.5 s the
second. The SCPI payload is already raw binary, so this is not an encoding
cost -- it is something inside the SCPI server's own data path.

SCPI still does everything else: configuration, arming, triggering. Those are
small commands where its 46 ms round trip does not matter. Only the bulk read
moves here.

Safety properties, deliberate:

  * /dev/mem is opened O_RDONLY and mapped PROT_READ. This process cannot write
    to physical memory even by mistake.
  * Only the reserved DMA region is mapped -- memory the kernel has been told
    not to use, which exists solely to hold captured samples.
  * No system state is touched. No service, no boot change, no package. It is a
    single file that does nothing until run, and removing it reverts everything.
  * Nothing listens unless this is running. Ctrl-C or QUIT ends it.

Install (from the control PC, or paste as a heredoc over SSH):

    scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/

/dev/shm is RAM, so it disappears on reboot and cannot accumulate as cruft.

Run:

    python3 /dev/shm/rp_fastread.py [base] [size] [port]

Defaults match ACQ:AXI:START? and ACQ:AXI:SIZE? on the bench board
(0x1000000, 128 MB) and port 9999.

Wire protocol, one request per connection:

    -> b"GET <offset> <length>\\n"    offset is relative to `base`
    <- exactly <length> raw bytes
    -> b"PING\\n"                     health check
    <- b"PONG\\n"
    -> b"QUIT\\n"                     server exits

Read only AFTER the capture has stopped. Reading a region while the DMA engine
is writing it returns torn data -- not dangerous, just wrong.
"""
import mmap
import os
import socket
import sys

DEFAULT_BASE = 0x1000000
DEFAULT_SIZE = 0x8000000
DEFAULT_PORT = 9999


def serve(base: int, size: int, port: int) -> None:
    # O_RDONLY + PROT_READ: writing to physical memory is not possible here.
    fd = os.open("/dev/mem", os.O_RDONLY)
    try:
        mem = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ, offset=base)
    except (OSError, ValueError) as e:
        # The usual cause is a kernel built with CONFIG_STRICT_DEVMEM, which
        # forbids reading normal RAM through /dev/mem. Nothing is broken; this
        # approach simply is not available.
        os.close(fd)
        print(f"FAILED to map /dev/mem at 0x{base:X} size 0x{size:X}: {e}",
              file=sys.stderr)
        print("If this is CONFIG_STRICT_DEVMEM, the fast path needs another "
              "route (a uio device, or a small kernel-side helper).",
              file=sys.stderr)
        raise SystemExit(2)

    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    print(f"rp_fastread: serving 0x{base:X}+0x{size:X} on port {port}",
          flush=True)

    try:
        while True:
            conn, addr = srv.accept()
            try:
                req = b""
                while not req.endswith(b"\n") and len(req) < 128:
                    chunk = conn.recv(128)
                    if not chunk:
                        break
                    req += chunk
                parts = req.decode("ascii", "replace").strip().split()
                if not parts:
                    continue
                if parts[0] == "PING":
                    conn.sendall(b"PONG\n")
                elif parts[0] == "QUIT":
                    conn.sendall(b"BYE\n")
                    break
                elif parts[0] == "GET" and len(parts) == 3:
                    off, length = int(parts[1]), int(parts[2])
                    if off < 0 or length < 0 or off + length > size:
                        # Refuse rather than silently clamp: a short read that
                        # looks like a full one is exactly the kind of quiet
                        # wrong answer this project keeps getting bitten by.
                        conn.sendall(b"")
                        print(f"  refused out-of-range {off}+{length} "
                              f"(size {size})", flush=True)
                    else:
                        conn.sendall(mem[off:off + length])
                else:
                    print(f"  bad request {req!r}", flush=True)
            finally:
                conn.close()
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)
    finally:
        srv.close()
        mem.close()
        os.close(fd)
        print("rp_fastread: stopped", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    serve(int(a[0], 0) if len(a) > 0 else DEFAULT_BASE,
          int(a[1], 0) if len(a) > 1 else DEFAULT_SIZE,
          int(a[2]) if len(a) > 2 else DEFAULT_PORT)
