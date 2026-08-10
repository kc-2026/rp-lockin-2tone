# Session log

Append a new entry at the end of every session. This is the only continuity
between agent sessions — a fresh agent must be able to resume from it without
re-deriving anything.

Template:

```
## YYYY-MM-DD — <who> — <one-line summary>
**Goal:**
**Did:**
**Learned:**
**Broke / still broken:**
**Next:**
```

---

## 2026-08-07 — Claude (Cowork, scoping session) — project bootstrap

**Goal:** Establish feasibility, fix the measurement architecture, and hand a
Claude Code agent a working starting point.

**Did:**
- Investigated `marceluda/rp_lock-in_pid` at source level. It cannot serve this
  measurement: reference generator capped at 49.6 kHz, output filter capped at
  1.2 kHz, built for a different board on a five-year-old toolchain, and it
  disables the stock signal generator. Reasoning recorded in ADR-0001
  (`docs/02-architecture.md`).
- Established that this is a burst measurement (one trace per laser sweep), so
  software demodulation over Deep Memory Acquisition is sufficient. No FPGA.
- Derived the frequency plan: f1 = 5 MHz, f2 = 6 MHz, |f2−f1| = 1 MHz, exact
  250-sample buffer. See `docs/03-frequency-plan.md`.
- Built and validated the DSP core, waveform construction, capture planner and
  DUT emulator. 62 offline tests pass.
- Wrote `hardware.py` from documentation. **Never executed.**

**Learned (the expensive parts):**
- A single FIR cannot set a 2 kHz corner at 250 MS/s — needs ~2.4M taps. The
  first implementation silently capped taps and used a filter ~100x too wide.
- FIR settling is the full impulse-response length, not the group delay.
  Trimming by group delay leaves ringing at the cutoff that mimics real noise.
- The output time axis must compensate both the trim and the group delay, or
  the whole trace shifts ~10 ms — which would bias every wavelength assignment.
- Streaming block boundaries must be bit-exact, not approximately equal. They
  are periodic, so any artefact lands identically in every sweep.
- Emulator clipping protection must rescale the ground truth too, or loopback
  tests report a phantom 2x amplitude error.
- Filter settling costs ~108 output points (22 ms) at 5000 Sa/s. The capture
  must pre-roll before the laser trigger.
- The naive buffer rule N = fs/f_mod is wrong whenever that is not an integer;
  f2 = 6 MHz needs 125 samples, not 41.67.

**Broke / still broken:**
- `hardware.py` is entirely unverified. Highest risk item.
- Deep Memory Generation not implemented — blocks full-length emulated sweeps.

**Next:** Test plan H1 — validate the SCPI transport against the real board,
starting by recording the OS version.

---

## 2026-08-10 — Claude (Claude Code) — first hardware contact; H1 essentially done

**Goal:** Onboard, validate the repo, get the board talking, and begin H1.

**Did:**
- Fixed the offline suite on Windows. `test_long_record_memory_bounded`
  imported Unix-only `resource` and failed at import, so its assertions never
  ran. Moved to stdlib `tracemalloc`. Verified it still guards: 346 MB at
  `CHUNK_SAMPLES = 1<<22` versus 4295 MB at `1<<26`, against an 800 MB bound.
- **Q10 decided by Edwin: τ stays at 71 µs / 5000 points.** Also corrected the
  spec's claim that τ is "configurable" — `dsp.py` clamps bandwidth to
  0.9 × output Nyquist and silently drops a wider request. Deliberate.
- H1.1–H1.6 complete except the deep-memory path. Details below.
- Verified `setup_acquisition` and the `setup_generator` command set against
  the board by set-then-read-back.
- **Found that `setup_am_generator` cannot work.** See below.

**Learned (the expensive parts):**

1. **The ASG does not replay a short buffer.** It always traverses a fixed
   16384-entry table; `SOUR:FREQ:FIX` is the traversal rate. `make_am_waveform`
   returns `fs/N` on the opposite assumption. Measured: a 50-sample buffer at
   5 MHz produces *no output at all* (min −2, max 4 counts). Loading the full
   table and playing at `fs/16384` = 15258.789 Hz reproduces it exactly —
   confirmed at 0.0153, 80.0018 and 0.9918 MHz, each dominant with the next
   line ≥53 dB down. **This is the biggest open item.** The offline tests could
   never have caught it: the commensurability arithmetic is right, the model of
   the hardware is wrong.
2. **The board has 1 GB, but `mem=512M` hides half of it from Linux.** I first
   concluded from `/proc/iomem` and `MemTotal` that it was a 512 MB board and
   started redesigning around decimation 4. Edwin pushed back with the
   datasheet and was right. Both of those sources show the capped view.
   `/proc/device-tree/memory/reg` is the honest one: base 0, size 0x40000000.
   The upper half, `0x20000000`–`0x3FFFFFFF`, is free for DMA and costs Linux
   nothing — so decimation 2 and the full 1 s capture are fine.
3. **The old H6.1 instruction was unsafe.** It based a 512 MB region at
   `0x1000000`, running to 528 MB and through Linux's own memory. Corrected to
   base `0x20000000`, plus a backup step: a bad device tree will not boot.
4. **A wedged SCPI server mimics a failing network.** Rapid reconnects (my
   probe opened ten in a row, which `conftest.py` explicitly warns against)
   left query latency at a 5.4 s median, max 21.9 s, in a pattern that looked
   exactly like TCP retransmission on a bad cable. Restarting the SCPI server
   fixed it: 0.050 s median. Never open a connection per command.
5. **A read timeout desynchronises the connection permanently** and yields
   believable-but-wrong values — `ACQ:AXI:SIZE?` appeared to return the region
   base. Use `*IDN?` as a sync token.
6. **Unsupported commands return zero bytes**, with no error string. A
   misspelled *setting* is indistinguishable from success, so write paths must
   be validated by reading back.
7. `*IDN?` cannot identify the model — no model name in the string. Confirmed
   the 250-12 by case label and by `monitor -f` → `z20_250`.
8. `ACQ:DATA:Units` defaults to `VOLTS` while `query_binary_int16` decodes
   int16. Wrong pairing gives the right sample count with meaningless values.
   `RAW` does take effect; the code is correct as written.

**Board facts:** `RP_HOST=rp-fffe42.local` (mDNS works; the link-local IP
changes). OS 2.00 build 37, Ubuntu 22.04.4, kernel 5.15.0-xilinx. AXI region
2 MiB at `0x1000000`. Sample rate confirmed 250 MS/s by measurement. Binary
transfer returns exactly 16384 int16 big-endian samples. Amplitude accurate to
0.1% at 1 MHz; ~1818 counts per volt on LV.

**Broke / still broken:**
- `setup_am_generator()` does not produce a usable signal. Not fixed — the fix
  changes the frequency plan and needs Edwin's decision (Q3a).
- `waveforms.make_am_waveform()` embeds the wrong hardware model. Its tests
  pass and will keep passing; they do not test against hardware.
- `hardware.py` still has unbounded polling loops (`while ... != "TD"`) with no
  timeout — H7.2's failure case would spin forever.
- `acquire_deep_2ch` sets `Trig:Dly` to the full record, leaving no pre-roll,
  which contradicts H6.4. Not yet touched.
- The `ACQ:AXI:*` deep-memory path is entirely unverified.
- `scripts/plan.py` computes settling at 250 MS/s while the operating point is
  125 MS/s, so it reports 113 points instead of 108. Overstates, so it errs
  safe.

**Next:**
1. Get a decision on Q3a (move onto the 15258.789 Hz grid) and probe Q3b
   (is the ASG table size settable? — would restore the original plan).
2. Rework `make_am_waveform` / `setup_am_generator` for the real ASG model,
   with an offline test that pins the traversal-rate relationship.
3. Then H2.3 spur check, H2.4/H2.5 two-channel start and phase repeatability.
4. Enlarge the DMA region per the corrected H6.1 before any deep-memory work.
