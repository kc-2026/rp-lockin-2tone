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

**LIMITATION — the drive frequencies are no longer round numbers.**

*Recorded at Edwin's explicit request when he approved the change on
2026-08-10. Anyone comparing this system against a spec, a commercial lock-in,
or an earlier dataset that says "1 MHz" needs to read this.*

The ASG can only emit integer multiples of fs/16384 = **15258.7890625 Hz**.
This is a hardware property, not a software choice: the table period is fixed
at 65.536 µs, and any frequency off that grid makes the table wrap
discontinuously and spray a 15.26 kHz spur comb across the baseband where the
swept trace lives. The nominal frequencies are all off the grid, so:

| Quantity | Nominal | Actual | Offset |
|---|---:|---:|---:|
| Carrier | 80 MHz | **80.001831 MHz** | +1831 Hz (+23 ppm) |
| f1 | 5 MHz | **5.004883 MHz** | +4883 Hz (+977 ppm) |
| f2 | 6 MHz | **5.996704 MHz** | −3296 Hz (−549 ppm) |
| \|f2 − f1\| | 1 MHz | **991.821 kHz** | −8179 Hz (−0.82%) |

Consequences to be aware of:

- **The lock-in frequency is 991.821 kHz, not 1 MHz.** Demodulate at the actual
  value. `plan_two_tone_grid().difference` is the number; do not hardcode 1e6.
- Cycles per integration time drop from 71 to 70. Immaterial against R4's 5–10.
- The carrier shift is 23 ppm, agreed as negligible for the AOMs.
- ADR-0001's remark that 1 MHz is exactly fs/250, which would make an FPGA
  demodulator a fixed 250-entry table, **no longer holds.** If FPGA work is
  ever revisited, that convenience is gone.
- `plan_two_tone_grid` snaps both tones independently. Snapping the difference
  instead would give 1.00708 MHz with f2 at 6.011963 MHz — equally exact, a
  different choice about which quantity stays nearest nominal. The independent
  snap is what was agreed and is pinned by
  `test_grid_plan_matches_the_agreed_operating_point`.

**Escape hatch:** if the ASG's table size turns out to be settable over SCPI
(Q3b, unprobed), a 250-entry table would restore exact 80/5/6 MHz and this
limitation disappears. Worth checking before anyone builds around 991.821 kHz.

**Broke / still broken:**
- ~~`setup_am_generator()` does not produce a usable signal.~~ **Fixed and
  verified.** Rewritten around the real ASG model; `make_am_table()` builds the
  full 16384-entry table and plays it at fs/16384. Verified through
  `hardware.py` itself: all three AM lines land at exactly the predicted
  frequencies, and at a 20 MHz carrier (where the analog path is flat) the
  sideband/carrier ratios are 0.512 and 0.488 against 0.500 theoretical.
  H2.3 spur check at the design point: worst spur −48.5 dBc, no comb.
- `waveforms.make_am_waveform()` embeds the wrong hardware model. Kept, because
  its arithmetic is sound and its tests are worth having, but its docstring now
  says in capitals not to drive the board with it. Use `make_am_table()`.
- ~~`hardware.py` has unbounded polling loops.~~ **Fixed.** Replaced with
  `wait_until()`, which raises `TimeoutError` with a diagnostic message. The
  deep-memory fill timeout scales with record length rather than being fixed.
  Not yet exercised against a trigger that never arrives (H7.2 proper).
- `acquire_deep_2ch` sets `Trig:Dly` to the full record, leaving no pre-roll,
  which contradicts H6.4. Not yet touched.
- The `ACQ:AXI:*` deep-memory path is entirely unverified.
- `scripts/plan.py` computes settling at 250 MS/s while the operating point is
  125 MS/s, so it reports 113 points instead of 108. Overstates, so it errs
  safe.

**Second coax (OUT2 → IN2) fitted; H2.4, H2.5 and Q3b done.**

- **Q3b: no.** `SOUR:TRAC:DATA:LEN?`, `:LENGTH?`, `SOUR:ARB:LEN?`,
  `SOUR:BUFF:SIZE?`, `SOUR:TRAC:DATA:SIZE?` all return zero bytes. The 16384
  table is fixed, so **the frequency limitation above is permanent.**
- **H2.4: passes.** Both channels generate simultaneously; carrier magnitudes
  201396 and 200157, within 0.6%.
- **H2.5 / Q6: FAILS, and not in the way expected.** The OUT2−OUT1 carrier
  phase scatters over 71–82° — *whether or not the generators are restarted*.
  Leaving them running does not fix it, so it is not injected at start.
  Ten consecutive captures with the generators untouched gave a 70.9° spread.
  Both DACs run from one clock; this is unexplained and needs a dedicated
  session.

  **Measurement trap, for whoever picks this up.** The obvious observable —
  the phase of the difference-frequency beat, reconstructed from each
  channel's envelope — is *worthless* here. The two envelopes are at different
  frequencies (328 and 393 cycles/table), so a common capture-start offset does
  not cancel: it moves their phase difference by 2π·991821·Δt, and about 1 µs
  of trigger jitter randomises it completely. I measured 72° that way and
  briefly believed it. **Use the carrier line instead** — identical on both
  channels at 5243 cycles, so a common offset cancels exactly. That is the only
  clean observable available without a third input.

  Also worth knowing: the carrier moves 115° per sample of inter-channel
  offset, versus 1.43° for the difference frequency. The carrier is an 80×
  magnifier — useful for detecting the problem, misleading about its size.

  **Impact.** Amplitude is unaffected. Phase *within* a sweep should be fine,
  since the generators run continuously through it. What is at risk is
  comparing or averaging phase *across* sweeps (bears directly on Q13).

**Next:**
1. **Q6 is the open question.** Needs Edwin's input on whether the measurement
   requires absolute phase or only phase structure within a sweep — that
   decides whether this is a blocker or a documented limitation. Then a
   dedicated session to explain the scatter; try `SOUR<n>:PHAS`, a combined
   `OUTPUT:STATE ON`, and check whether the two ADC channels are read from a
   common buffer pointer (an unequal read offset would fake this exactly).
3. Enlarge the DMA region per the corrected H6.1 (base `0x20000000`, size
   512 MB, back up `dtraw.dts` first) before any deep-memory work. Nothing in
   H5 or H6 can proceed on the shipped 2 MiB.
4. Then the `ACQ:AXI:*` path, which is the last wholly unverified part of
   `hardware.py`, followed by H3 (receive path, noise floor — Q8).
5. Fix `acquire_deep_2ch`'s trigger delay so pre-roll is possible (H6.4).

**Test suite:** 74 passing, up from 62. The 12 new ones pin the real ASG model
so it cannot silently regress.
