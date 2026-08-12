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

  **RESOLVED AS NOT BLOCKING — Edwin, 2026-08-10: the deliverable is
  amplitude only, not amplitude and phase.** `01-project-spec.md` updated.

  His reasoning, which is the physical argument and worth keeping over my
  inference: *the 80 MHz is only there to drive the AOM, so its phase carries
  no information; and the 5/6 MHz modulation phase does not matter either,
  because the lock-in recovers R.* R is the magnitude of the demodulated
  phasor and is invariant to a constant phase offset between the two drives —
  so a scatter in that offset moves the demodulated phasor around the circle
  without changing its length. Do not spend time explaining the scatter unless
  phase comes back into scope.

  **Concerns to carry forward anyway, recorded at Edwin's request:**

  1. *A relative **drift** would matter even for amplitude* — this is the one
     concern that survives Edwin's argument, because it is not a constant
     offset. A constant offset leaves R alone; a steadily advancing one does
     not. If the two
     channels' table positions slide continuously rather than jumping, that is
     equivalent to a small frequency offset on the beat, and a large enough
     offset walks the signal off the lock-in centre frequency, where the
     2250 Hz bandwidth attenuates it. Amplitude would sag without anything
     looking wrong. The observed scatter is consistent with drift of order
     ~1 Hz, which is utterly negligible against 2250 Hz — but my captures were
     seconds apart, so I cannot distinguish slow drift from fast drift that
     aliases to look random. **Check once deep memory works:** demodulate a
     single long capture and confirm the amplitude is steady end to end. That
     settles it directly and needs no extra hardware.
  2. *My original alarm was over-stated.* The carrier is ~80× more sensitive
     to inter-channel misalignment than the beat is (115° vs 1.43° per sample),
     so 75° of carrier scatter is consistent with anything from a fraction of a
     degree of beat wobble to complete randomness. I reported the alarming end
     of that range as the finding. If anyone revisits this, measure the table
     alignment directly: put the *same* modulation on both channels and
     cross-correlate the two captures. That has neither the 80× magnifier nor
     the trigger-jitter confound.
  3. *Amplitude estimator bias.* With amplitude as the sole deliverable,
     `R = sqrt(X² + Y²)` is the obvious choice and is biased upward in noise —
     CLAUDE.md lists this as a known trap. Since phase is steady within a
     sweep, rotating X + jY to a common angle and taking the real part is
     unbiased and quieter. Worth doing before quoting any noise figure from
     H3.3.

**RESOLVED LATER THE SAME DAY — the DMA capture was always fine; the SCPI
read was the broken part.** Read the section below for the diagnosis, then
this correction: `acquire_deep_fast()` performs the identical arming and
trigger sequence and returns good data. Verified by driving 1 MHz and then
2 MHz and capturing each — recovered 1.0000 and 2.0000 MHz, amplitude 361
counts against 362 measured independently, rms exactly amplitude/√2. Each
capture tracks its own drive, so it is live data, not leftovers.

So the fast read path fixed a correctness problem, not just a speed one. That
was not the reason for building it and was not anticipated.

**Two things learned while getting there, both of which cost time:**

- **`ACQ:AXI:SOUR<n>:Trig:Dly` is a post-trigger SAMPLE COUNT, not a delay.**
  Set it below the number of samples you intend to read and the tail of the
  read is whatever occupied the region beforehand. My first attempt set it to
  1000 and read a million samples; the result had the right min/max but an rms
  of 63.6 where a full sine gives 255, and no coherent tone. It looked like a
  broken capture and was a broken test.
- **`ACQ:AXI:SOUR<n>:Trig:Pos?` returns 2139095040 = 0x7F800000**, the float32
  bit pattern for infinity. Evidently broken. It does not matter yet because
  `ACQ:TRig NOW` fires immediately and the capture starts at the region base,
  so reading from offset 0 is correct. **It will matter for H6.4**, where a
  laser-triggered capture with pre-roll writes into a ring and the data will
  not start at offset 0.

---

**Original diagnosis, kept because the reasoning is still useful:**

The DMA region change worked: `ACQ:AXI:SIZE?` now reports 134217728 (128 MiB),
up from 2 MiB. 268 ms of two-channel capture at decimation 2.

**Transfer is 5.7 MB/s, and it is a hard limit worth planning around.**
Measured cleanly: six consecutive 7.6 MB reads, every one within 0.02 s of the
others. The planner assumed 100 MB/s on the reasoning that a gigabit link sets
the pace. It does not — the link is essentially idle. The bottleneck is the
SCPI server on the board's ARM core, moving about 2.9 M samples/s out of DMA
into a socket. A trivial command round trip is 46 ms.

Ruled out: our receive code (switching the accumulator from repeated
`bytes +=` concatenation, which is quadratic, to a joined chunk list changed
nothing at all) and read size. `GBE_MB_PER_S = 100.0` is now
`SCPI_MB_PER_S = 5.7`.

**A 477 MB one-second sweep therefore takes ~84 s over SCPI — but this is
fixable, and the fix is worth taking.**

Edwin pushed back on the claim that the board's CPU was the limit, and he was
right. Measured on the same cable, same board:

| Path | Rate |
|---|---:|
| SCPI binary block | 5.7 MB/s |
| Board writing its own RAM (`dd` to tmpfs) | 151 MB/s |
| **Raw TCP, board RAM → this PC** | **87 MB/s** |

**15× faster over a raw socket.** Neither the hardware nor the network is the
constraint; it is something inside the SCPI server's data path. Note the SCPI
payload is *already* raw binary — `FORMAT BIN`, 2 bytes per sample, verified by
byte count — so this is not a text-encoding cost, which was my first guess and
was wrong.

At 87 MB/s a 477 MB sweep transfers in **5.5 s instead of 84 s**.

**Proposed fast read path** (not yet built, needs a scope decision — see
below). Keep SCPI for what it is good at: configuration, arming, triggering,
all small commands where the 46 ms round trip is irrelevant. Replace only the
bulk read. The captured samples sit at a known physical address
(`ACQ:AXI:START?` = 0x1000000), so a small board-side helper can `mmap`
`/dev/mem` and stream the region over a socket.

Two things to work out when building it: the region is a ring buffer, so the
wrap has to be handled using `ACQ:AXI:SOUR<n>:Trig:Pos?`; and each channel has
its own contiguous sub-region, set by `ACQ:AXI:SOUR<n>:SET:Buffer`, so they do
not need de-interleaving.

**Scope decision needed.** `CLAUDE.md` says "Code and this agent both run on
the control PC," and this would put a small data-pump script on the board.
It is not FPGA work so R7 is untouched, but it is a genuine deviation from the
stated architecture and should be agreed rather than assumed. The alternative
is to accept 84 s per sweep, which is survivable for a burst measurement but
makes H7.1 half an hour of transfers.

*How this was nearly mis-reported, twice.* First I divided the whole
`acquire_deep_2ch` call time by the bytes returned and called it a transfer
rate — that included setup, arming and trigger polling, and gave ~4 MB/s.
Then an intermediate benchmark showed 55.9 MB/s and I briefly believed the
transfer was fine; that reading was an artefact of the benchmark consuming
bytes already sitting in the receive buffer from the previous read. The
repeated single-size measurement is the trustworthy one, and the fast reading
never reproduced.

`acquire_deep_2ch` then *appeared* to work: 200000 samples/channel at
decimation 2, with IN1 showing 1.0000 MHz and IN2 2.0000 MHz — correct counts,
correct channel mapping, no duplicated buffer. **That result did not hold up.**

On later calls it returns railed data (min −2048, max +2047) and, decisively,
**byte-identical statistics at decimation 1 and decimation 2** (ch1 mean 193.2,
rms 865.0 in both). Two different decimations cannot produce identical data
from a live capture. Confirmed against a silent input: with both outputs off,
ordinary `acquire()` reads a quiet 25–31 count band while `acquire_deep_2ch`
on the same input returns full-scale noise. **It is reading stale or
uninitialised DMA memory, not capturing.**

Two concrete defects found while diagnosing, both worth fixing regardless:

1. **`acquire_deep_2ch` calls `ACQ:RST`, which wipes the coupling and gain that
   `setup_acquisition` just applied.** Any caller doing the documented
   setup-then-acquire sequence silently loses its input configuration.
2. **`ACQ:AXI:DATA:Units RAW` does not take effect.** After the call,
   `ACQ:DATA:UNITS?` reads `VOLTS`. The set spelling appears to be unsupported
   and silently ignored — precisely the failure mode documented earlier, where
   a misspelled setting is indistinguishable from success. (The returned byte
   count is still consistent with int16, so this may be a separate AXI units
   setting that is not queryable; either way it is unverified.)

**Consequence: the drift question is still open.** Both attempts to measure it
were invalidated, and neither by the board:

- First at decimation 2, where the 80 MHz carrier is **above the 62.5 MHz
  Nyquist** and aliases to 45 MHz, badly attenuated by the decimation filter.
  145° of scatter, and a straight line through it gave a fictitious 175 Hz
  offset. **Do not measure the 80 MHz carrier at decimation 2.**
- Then at decimation 1, which fixed the aliasing but hit the railed-data bug
  above. Phase from a clipped signal means nothing.

Lesson worth carrying: both runs would have looked plausible if the signal
levels had not been printed. **Always print min/max/rms alongside any phase
result** — it is the only thing that distinguishes a measurement from a
noise measurement.

**Next:**
1. **Fix `acquire_deep_2ch` before anything else.** It is the gate for H5, H6
   and the Phase 1 exit criterion. Start with whether the buffer is genuinely
   being armed: check `ACQ:AXI:SOUR<n>:TRIG:FILL?` transitions 0→1 rather than
   reading 1 immediately from a previous run, and whether
   `ACQ:AXI:SOUR<n>:ENable OFF` in a `finally` block leaves the region in a
   state that breaks the next capture. Note the *first* call after the reboot
   worked and later ones did not, which points at leftover state rather than a
   wrong command.
2. Re-measure the drift once deep capture is trustworthy — at **decimation 1**,
   with signal levels printed.
3. The DMA region was enlarged from 2 MiB to 128 MB on
   2026-08-10 (`reg = <0x1000000 0x8000000>`, staged deliberately: the node
   name and base are unchanged so the `dma_region` alias on line 19 of the DTS
   stays valid, and 144 MB is the hard ceiling before colliding with
   `labuf@a000000`). That is 0.27 s of two-channel capture at decimation 2 —
   enough to exercise the whole `ACQ:AXI:*` path and cover H5.2. Going to the
   full 512 MB needs the upper half of RAM, which means renaming the node
   *and* updating that alias, and the region would sit above the `mem=512M`
   cap where the kernel may refuse it. Prove the path at 128 MB first.
3. Enlarge the DMA region per the corrected H6.1 (base `0x20000000`, size
   512 MB, back up `dtraw.dts` first) before any deep-memory work. Nothing in
   H5 or H6 can proceed on the shipped 2 MiB.
4. Then the `ACQ:AXI:*` path, which is the last wholly unverified part of
   `hardware.py`, followed by H3 (receive path, noise floor — Q8).
5. Fix `acquire_deep_2ch`'s trigger delay so pre-roll is possible (H6.4).

**Test suite:** 74 passing, up from 62. The 12 new ones pin the real ASG model
so it cannot silently regress.
