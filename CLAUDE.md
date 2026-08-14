# Agent onboarding — read this first, every session

You are working on a two-tone lock-in measurement system for a Red Pitaya
SIGNALlab 250-12. A human (Kevin) has the board on his bench and can rewire it,
but is not watching continuously.

**Read in this order before doing anything:**

1. This file.
2. `docs/01-project-spec.md` — what is being built and why.
3. `SESSION_LOG.md` — what previous sessions did and what state things are in.
4. Whatever doc covers the area you are about to touch.

**At the end of every session, append to `SESSION_LOG.md`.** Multiple sessions
will work on this. The log is the only continuity between them. Record what you
did, what you learned, what broke, and what you would do next. Be specific
enough that a fresh agent can resume without re-deriving anything.

---

## The one-paragraph summary

Two 80 MHz carriers, amplitude modulated at f1 = 5 MHz and f2 = 6 MHz, drive a
DUT through AOMs. The DUT mixes them; a photodetector returns the
intermodulation response at |f2 − f1| ≈ 991.821 kHz and nothing else. A **Santec**
laser sweeps its wavelength over ~1 s. We capture the photodetector on IN1,
trigger the capture from the laser's trigger output on IN2, demodulate in
software, and deliver a 5000-point trace of **amplitude** across the sweep.

**The wavelength axis comes from the laser over serial, not from trigger timing**
(Kevin, 2026-08-14). The Santec reports wavelength against relative time from its
first trigger; that trigger also starts the capture, so both share t = 0. Reading
the Santec is new work that exists nowhere in the codebase yet.

**The trap to design against is Q21:** both sides call t = 0 "the first trigger",
independently. Latch the second pulse instead of the first and every wavelength
is off by one time step, with a trace that looks entirely normal.

Everything is done in software on a control PC. There is no FPGA work in scope.

---

## Ground rules

### Safety

Loopback phase only, for now. Within that:

- **Never exceed the Red Pitaya's own specifications.** Output range is
  software-selectable; do not command amplitudes outside it.
- **The DUT, the amplifier chain, the AOMs and the photodetector are NOT
  connected** during loopback work. If you believe a test needs them, stop and
  write the request into `SESSION_LOG.md` — do not improvise a way around it.
- **Leave outputs off when you finish.** `tests/hardware/conftest.py` does this
  automatically; preserve that behaviour.
- Going beyond loopback requires a dedicated planning session with the human.
  There is a placeholder for it in `docs/04-test-plan.md`. Do not start it
  unilaterally.

### Verified versus unverified code

This distinction matters more than usual here.

| Area | Status |
|---|---|
| `src/rp_lockin/dsp.py` | **Trusted.** 76 offline tests. Do not change without re-running them. |
| `planning.py`, `emulator.py` | **Trusted.** Same suite. |
| `waveforms.py` — `make_am_table`, `plan_two_tone_grid` | **Trusted and hardware-verified.** Use these to drive the board. |
| `waveforms.py` — `make_am_waveform`, `plan_two_tone` | **Sound arithmetic, WRONG hardware model.** Kept because their tests are worth having. Driving the board with them produces no output at all. |
| `hardware.py` — SCPI transport, generator, `acquire`, `acquire_deep_fast` | **Verified against the board 2026-08-12.** |
| `hardware.py` — `acquire_deep_2ch` | **The SCPI read is broken.** Arming is fine; the read returns garbage. Use `acquire_deep_fast`. |
| `scripts/rp_fastread.py` | **Runs ON THE BOARD**, not the control PC. The one deliberate exception to "everything runs on the PC". |

`hardware.py` is deliberately isolated from the maths so a wrong command string
produces a connection error rather than corrupted physics. **Keep it that way.**
Do not move signal processing into the transport layer.

Your first hardware task is H1 in `docs/04-test-plan.md`: walk `hardware.py`
method by method and confirm each SCPI command against the board's actual OS
version. Every method carries a `VERIFY:` note naming what to check.

### Testing discipline

```bash
pytest                      # offline suite — must always pass
pytest -m "not slow"        # quick loop while iterating
RP_HOST=<ip> pytest tests/hardware -m hardware    # needs the board
```

- The offline suite must pass before you touch hardware, and again before you
  commit.
- **Do not delete a failing test to make the suite green.** Several tests exist
  because the corresponding bug was real and produced plausible-looking wrong
  answers. They are documented as such in their docstrings.
- When you fix a hardware-discovered bug, add an offline test that would have
  caught it, if one can exist.

### Things that will bite you

These are all real, all previously encountered, and all produce *believable*
wrong answers rather than crashes:

1. **Buffer commensurability.** A repeating waveform buffer must contain whole
   cycles of the carrier AND the modulation. Off-grid frequencies glitch at
   every wrap and scatter spurs across the baseband — exactly where the trace
   lives. Use `plan_two_tone()`; never hand-roll frequencies.
2. **The naive buffer rule is wrong.** N = fs/f_mod only works when that is an
   integer. The real minimum is the smallest N making N·f/fs whole for *every*
   frequency involved. f2 = 6 MHz needs 125 samples, not 41.67.
3. **Filter settling costs ~108 points** at 5000 Sa/s — about 22 ms, 2% of a
   sweep. The capture must pre-roll before the laser trigger or the start of
   every trace is garbage. See `planning.settling_points()`.
4. **The time axis is not zero-based.** `LockinResult.t` is referenced to the
   start of the input record and already compensates settling and group delay.
   Do not add your own offset — the wavelength calibration depends on this.
5. **`mean(R)` is a biased amplitude estimator** in noise. Use the vector mean
   of X + jY.
6. **Streaming block boundaries are periodic.** An artefact there lands at the
   same place in every sweep and looks like DUT structure. `test_chunked_equals_
   single_shot` pins this to exact equality; keep it exact, not approximate.

### Conventions

- Python ≥ 3.10, numpy + scipy. Keep dependencies minimal.
- Comments explain *why*, not *what*. Non-obvious numerical choices get a
  sentence of justification.
- Errors should refuse and explain, not silently degrade. If a record is too
  short or a frequency is off-grid, raise with a message saying what to do
  instead. This codebase already does that in several places — match the style.
- Commit in logical units with messages saying what changed and why.

---

## Environment

- Code and this agent both run on the control PC.
- The board is reachable over the network; the human will supply `RP_HOST`.
  Nobody else uses the board.
- The board's SCPI server must be running: web interface → Development → SCPI
  server → Run. Port 5000.
- SSH access to the board is available for the device-tree change described in
  `docs/05-hardware-notes.md`. Rebooting the board is permitted.
- **OS version: 2.00, build 37** (Ubuntu 22.04.4, kernel 5.15.0-xilinx).
  Recorded in `docs/05-hardware-notes.md`. It is in
  `/opt/redpitaya/version.txt`, not `/etc/redpitaya_version`, which does not
  exist on this image.

## Quick orientation

```bash
python -c "from rp_lockin import plan_two_tone; print(plan_two_tone(1e6).describe())"
python -c "from rp_lockin import describe_capture_plan; print(describe_capture_plan(1.0, 1e6))"
pytest -q
```

## Current state — updated 2026-08-14

Phase 0 complete. **Phase 1's exit criterion is met** — H6.5 captured a full
second on both channels, triggered, with pre-roll, and recovered seven amplitude
levels to within 1%. 76 offline tests pass. **But Phase 1 is not finished:** all
of H7, H3.5's board half, and H5.2/H5.3 remain.

Key-based SSH is installed, so the board helper no longer needs a human — see
"Talking to the board" below.

| Test | State |
|---|---|
| H1 transport | done — OS 2.00, 250 MS/s confirmed by measurement, binary transfer verified |
| H2.1–H2.4 transmit | done — AM lines exact, depth 0.512/0.488 vs 0.500, worst spur −48.5 dBc |
| H2.5 / Q6 phase | failed, **downgraded, and its residual risk is now closed** by H3.2 |
| H3.1 amplitude linearity | done — linear over 2.4 decades; 0.3% spread above 20 mV |
| H3.2 phase stability | done — 0.002° over 28 ms |
| H3.3 noise floor / Q8 | **done, revised twice — σ = 3.57 µV per trace point; ≥36 µV of signal gives SNR 10.** Do not quote the earlier 2.96 µV |
| H3.4 √bandwidth law | done — holds to 2–4% over 8× in bandwidth |
| H3.5 offset response | **offline half only**; board half not started |
| H4.1–H4.4 trigger | done — edges recovered exactly, inputs aligned to 0.0005 samples, `Trig:Pos` solved |
| H5.1 Deep Memory Gen | **answered: NOT AVAILABLE.** 16384-point ceiling is permanent |
| H5.2 / H5.3 | superseded — H6.5 emulated the DUT by stepping amplitude instead |
| H6.1 memory move | **deliberately not done** — see the memory section in `05-hardware-notes.md` |
| H6.4 pre-roll | done — and two real `acquire_deep_fast` defects fixed getting there |
| H6.5 full capture | **PASSES** — the Phase 1 exit criterion |
| H7.1–H7.4 robustness | **none started. This is the main remaining Phase 1 work.** |

**The largest open work is not on this list.** The wavelength axis now comes from
the Santec laser over serial (Kevin, 2026-08-14), and **no driver for that exists**
— not a line of it. Q18–Q20 are answered, so its shape is now known; what remains
is the serial command set, the port settings, and whether the wavelength table
streams live or is dumped after the sweep.

That change also **defused the decimation/memory question.** It was live only
because the wavelength axis depended on recovering trigger intervals exactly; it
no longer does. Do not start the device-tree move — see `05-hardware-notes.md`.

**Two numbers from H3.3 not to re-derive or guess at:**

- **The demodulator's noise gain is NOT the nominal bandwidth.** 4232.7 Hz
  analytically, **4763 Hz measured** — both about 1.9× the nominal 2250 Hz.
  Using the −3 dB bandwidth instead gives 2.45 µV against 3.57 measured,
  **46% low, in the dangerous direction.** Pinned by
  `test_quadrature_noise_gain_matches_filter_chain`.
- **A switching-supply harmonic sits 17.9 kHz from the lock-in frequency, and
  it is ~32 µV — 11× the noise floor.** Rejected by >200 dB today, but only
  **1.77%** of switcher drift from landing on it, where it would look like a
  strong, clean, steady DUT response rather than interference.
  **504.868 kHz and its multiples are off limits for any future
  difference frequency**, with several kHz of margin.

**Three things bit hard this session and are worth knowing before you start:**

1. The generator never worked as written — `make_am_waveform` models a device
   this board is not. Fixed by `make_am_table`; see `03-frequency-plan.md`.
2. **The drive frequencies are not round numbers.** The lock-in frequency is
   **991.821 kHz, not 1 MHz.** Never hardcode `1e6`; use
   `plan_two_tone_grid().difference`.
3. Deep captures need `scripts/rp_fastread.py` running on the board. It lives
   in `/dev/shm`, which is RAM, so **it disappears on every reboot.**

`docs/06-open-questions.md` lists what is still undecided. If you resolve one,
move it into the relevant doc and note it in the session log.

## Getting the environment up

`.venv/` is gitignored, so a fresh clone needs:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
.venv/bin/python -m pip install -e ".[dev]"         # Linux
pytest -q                                            # expect 76 passed
```

Most machines here run Windows; keep the suite passing on it. One test uses
`tracemalloc` rather than the Unix-only `resource` module for exactly that
reason — do not "simplify" it back.

## Talking to the board

```bash
export RP_HOST=rp-fffe42.local     # mDNS; the link-local IP changes on reconnect
```

- **SCPI does not auto-start after a reboot.** Web interface → Development →
  SCPI server → Run. Port 5000.
- **One persistent connection, always.** Opening a connection per command
  wedges the server, and the symptom is multi-second latency that looks
  exactly like a failing cable, not an error.
- For deep captures, start the helper first. It lives in `/dev/shm`, which is
  RAM, so **it is gone after every reboot** and these two commands are the
  routine. Key-based SSH was installed on the control PC on 2026-08-12, so this
  needs no password and no human:

  ```bash
  scp scripts/rp_fastread.py root@rp-fffe42.local:/dev/shm/
  ssh -n root@rp-fffe42.local "nohup setsid python3 /dev/shm/rp_fastread.py > /dev/shm/rp_fastread.log 2>&1 < /dev/null &"
  ```

  `setsid` and the redirects matter: without them the helper dies when the SSH
  session closes, which looks identical to "the helper was never started".
  Confirm with `RedPitaya.fast_read_available()`, and read
  `/dev/shm/rp_fastread.log` if it says False. Stop it cleanly by sending
  `QUIT\n` to port 9999.

- **The board's root filesystem is mounted read-write** (confirmed
  2026-08-14: `/dev/root / ext4 rw,relatime,errors=remount-ro`), apparently
  left that way by the 2026-08-12 device-tree edit. That is why the documented
  `rw` step appears unnecessary — and note `rw`/`ro` are interactive shell
  shortcuts that do not exist in a one-shot `ssh host "..."` command; use
  `mount -o remount,rw /` there. A permanently writable root on an SD card is a
  mild corruption risk on power loss; worth putting back with
  `mount -o remount,ro /` once the device-tree work is finished.
