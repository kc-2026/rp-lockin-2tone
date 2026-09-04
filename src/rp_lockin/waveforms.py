"""
Drive waveform construction for the two-tone AOM experiment.

Both outputs carry an 80 MHz AOM drive amplitude-modulated at f1 and f2. The
80 MHz is what the acousto-optic modulators need in order to diffract at all;
the DUT never sees it, only light gated at f1 and f2. The DUT
mixes them and the response appears at |f2 - f1|.

The whole design turns on one arithmetic fact: a repeating buffer only replays
seamlessly if it contains a whole number of cycles of BOTH the carrier and the
modulation. Miss that and every buffer wrap injects a discontinuity, scattering
spurs across the baseband -- exactly where the swept trace lives. See
docs/03-frequency-plan.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import ASG_BUFFER_MAX, BASE_SAMPLE_RATE

__all__ = ["AsgTable", "GridTwoTonePlan", "TwoTonePlan", "asg_grid",
           "make_am_table", "make_am_waveform", "plan_two_tone",
           "plan_two_tone_grid", "snap_to_asg_grid"]


# ---------------------------------------------------------------------------
# The real generator model -- measured on the board, 2026-08-12
# ---------------------------------------------------------------------------
#
# The ASG does NOT replay the N samples you load. It always traverses a fixed
# 16384-entry table, and SOUR:FREQ:FIX sets how many times per second that
# traversal happens. Entries never written stay zero.
#
# So a 50-entry buffer played at fs/50 emits essentially nothing: the phase
# accumulator steps ~328 entries per clock and skips straight over the data.
# Measured min -2, max +4 counts -- noise.
#
# Setting the frequency to fs/16384 steps exactly one entry per DAC clock,
# which reproduces the whole table faithfully at the full sample rate. Verified
# at 0.0153, 80.0018 and 0.9918 MHz, each dominant with the next line >=53 dB
# down.
#
# The consequence is that the table period is fixed at 16384 samples =
# 65.536 us, so every frequency must be an integer multiple of fs/16384. Buffer
# length is no longer something to choose -- see make_am_waveform's note.

def asg_grid(fs: float = BASE_SAMPLE_RATE) -> float:
    """Frequency spacing the ASG can actually emit: fs / 16384.

    At 250 MS/s this is 15258.7890625 Hz. Any drive frequency must be an
    integer multiple of it, or the table wraps discontinuously every 65.536 us
    and scatters a spur comb across the baseband.
    """
    return fs / ASG_BUFFER_MAX


def snap_to_asg_grid(f: float, fs: float = BASE_SAMPLE_RATE) -> tuple[float, int]:
    """Nearest emittable frequency to f, and its cycle count per table.

    Returns (frequency, cycles). The cycle count is the useful number: it is
    what actually goes into the table, and being an integer is precisely what
    makes the wrap seamless.
    """
    grid = asg_grid(fs)
    cycles = int(round(f / grid))
    if cycles < 1:
        raise ValueError(
            f"{f:g} Hz is below the ASG's {grid:.4f} Hz resolution -- the "
            f"table cannot hold even one cycle."
        )
    if cycles >= ASG_BUFFER_MAX // 2:
        raise ValueError(
            f"{f:g} Hz is at or above the table's Nyquist "
            f"({fs / 2:g} Hz). Lower the frequency."
        )
    return cycles * grid, cycles


@dataclass(frozen=True)
class AsgTable:
    """A full 16384-entry ASG table and the frequency to play it at."""

    samples: np.ndarray     # length 16384, normalised to -1..+1
    play_freq: float        # fs/16384 -- one table entry per DAC clock
    carrier: float          # the frequency actually emitted, post-snap
    modulation: float       # ditto
    carrier_cycles: int     # whole cycles per table -- integer by construction
    mod_cycles: int

    def describe(self) -> str:
        return (
            f"table       {len(self.samples)} entries, "
            f"played at {self.play_freq:.4f} Hz "
            f"({1e6 / self.play_freq:.3f} us period)\n"
            f"carrier     {self.carrier / 1e6:.6f} MHz "
            f"({self.carrier_cycles} cycles per table)\n"
            f"modulation  {self.modulation / 1e6:.6f} MHz "
            f"({self.mod_cycles} cycles per table)"
        )


def make_am_table(carrier: float, modulation: float,
                  fs: float = BASE_SAMPLE_RATE,
                  depth: float = 1.0) -> AsgTable:
    """
    Build a full 16384-entry AM table for the real ASG.

    Use this, not make_am_waveform, to drive hardware. Both frequencies are
    snapped to the fs/16384 grid, because that is the only way the table wraps
    without a discontinuity. The snap is at most half a grid step -- 7.6 kHz at
    250 MS/s, or 95 ppm of an 80 MHz carrier.

    Cycle counts rather than frequencies are used to build the table, so the
    whole-cycle property is exact by construction rather than to within
    floating-point tolerance.
    """
    if not 0 < depth <= 1.0:
        raise ValueError("depth must be in (0, 1]")

    f_c, n_c = snap_to_asg_grid(carrier, fs)
    f_m, n_m = snap_to_asg_grid(modulation, fs)
    if n_m >= n_c:
        raise ValueError("modulation frequency must be below the carrier")
    if n_c + n_m >= ASG_BUFFER_MAX // 2:
        raise ValueError(
            f"upper sideband ({(f_c + f_m) / 1e6:g} MHz) is above Nyquist"
        )

    k = np.arange(ASG_BUFFER_MAX)
    env = 1.0 + depth * np.cos(2 * np.pi * n_m * k / ASG_BUFFER_MAX)
    wave = env * np.cos(2 * np.pi * n_c * k / ASG_BUFFER_MAX)
    wave = wave / np.max(np.abs(wave))
    return AsgTable(samples=wave, play_freq=asg_grid(fs), carrier=f_c,
                    modulation=f_m, carrier_cycles=n_c, mod_cycles=n_m)


@dataclass(frozen=True)
class GridTwoTonePlan:
    """Two-tone drive frequencies snapped onto the ASG grid."""

    carrier: float
    f1: float
    f2: float
    fs: float
    carrier_cycles: int
    f1_cycles: int
    f2_cycles: int

    @property
    def difference(self) -> float:
        """The lock-in frequency. Exact, because it is a whole number of grid
        steps: (f2_cycles - f1_cycles) * fs / 16384."""
        return abs(self.f2 - self.f1)

    @property
    def play_freq(self) -> float:
        return asg_grid(self.fs)

    def periods_per_tau(self, tau: float) -> float:
        return tau * self.difference

    def describe(self) -> str:
        g = asg_grid(self.fs)
        return "\n".join([
            f"ASG grid     {g:.4f} Hz  (fs/16384; table period "
            f"{1e6 * ASG_BUFFER_MAX / self.fs:.3f} us)",
            f"carrier      {self.carrier / 1e6:.6f} MHz  "
            f"({self.carrier_cycles} cycles/table)",
            f"f1           {self.f1 / 1e6:.6f} MHz  "
            f"({self.f1_cycles} cycles/table)",
            f"f2           {self.f2 / 1e6:.6f} MHz  "
            f"({self.f2_cycles} cycles/table)",
            f"|f2 - f1|    {self.difference / 1e3:.3f} kHz  "
            f"({self.f2_cycles - self.f1_cycles} cycles/table)  "
            f"<-- lock-in frequency",
        ])


def plan_exact_am(carrier: float, modulation: float,
                  fs: float = BASE_SAMPLE_RATE,
                  max_play: float = 10e6,
                  carrier_tol: float = 0.5e6) -> tuple[int, int, int] | None:
    """Cycle counts and an integer PLAY RATE giving the modulation exactly.

    MEASURED ON THE BOARD, 2026-08-28, correcting two things this project had
    recorded and one thing this function previously assumed.

    The rule is simply::

        output frequency = cycles_in_table x play_rate

    and the play rate is a free setting, quantised to 1 Hz. Both facts were
    checked directly:

    * A 16384-entry table holding ONE modulation cycle and 80 carrier cycles,
      played at 1000000 Hz, produced a carrier at 80.0018 MHz with sidebands at
      78.995 and 80.978 MHz -- exactly 80 MHz AM'd at 1 MHz, at the same
      amplitude as the default-grid path. Kevin said he had done this before,
      and he was right.
    * SOUR:FREQ:FIX accepts 1 MHz and 5 MHz. There is no 15258 Hz ceiling; that
      number is only fs/16384, which is the rate at which the table advances
      one entry per DAC clock, not a limit on anything.

    So `mod_cycles` may be as low as 1, and the fs/16384 "grid" -- along with
    the hunt for a divisor under 15258 -- disappears. Any modulation that is a
    whole number of hertz is reachable exactly.

    The CARRIER lands on the nearest multiple of the same play rate, so its
    error is at most play_rate/2. Larger mod_cycles means a lower play rate and
    a closer carrier -- but that is the WRONG trade, and the search used to
    make it.

    **Why the fewest modulation cycles wins.** The output is
    `mod_cycles x play_rate`, so whatever error the board has in realising the
    play rate is multiplied by mod_cycles, and it lands on the MODULATION --
    the one frequency the lock-in has to match. The carrier error it buys in
    exchange lands on the AOM, whose acoustic passband is megahertz wide and
    cannot tell.

    Measured on the bench 2026-09-01: 915 kHz planned as 12 cycles at
    76250 Hz demodulated with a ~0.69 Hz offset, which drew a smooth arch from
    -76 mV through zero to +134 mV and back across a 1 s sweep -- indis-
    tinguishable from a wavelength-dependent response. 1 MHz, which plans as a
    single cycle at 1000000 Hz, showed none of it. Twelve times the cycles,
    twelve times the frequency error.

    So: take the FEWEST modulation cycles whose carrier still lands within
    `carrier_tol`, and use the carrier error only to break ties. 915 kHz now
    plans as 1 cycle at 915000 Hz, putting the carrier at 79.605 MHz -- 395 kHz
    off 80 MHz, and beneath the AOM's notice.

    If nothing meets `carrier_tol` the search falls back to the closest carrier
    it can find, so a modulation that was plannable before still is.

    Also measured, and NOT free: driving at a high play rate raised spurs at
    36.0 and 54.0 MHz to ~6% and ~4.6% of the carrier, against ~0.2% for the
    default grid. They sit far from the modulation and an AOM will not diffract
    them efficiently, but they are there.

    Returns (carrier_cycles, mod_cycles, play_rate_hz), or None when the
    modulation is not a whole number of hertz.
    """
    if modulation <= 0 or carrier <= 0:
        return None
    m = int(round(modulation))
    if abs(m - modulation) > 1e-6 or m < 1:
        return None                         # not a whole number of hertz

    best_near = None        # within carrier_tol: fewest cycles wins
    best_any = None         # fallback: closest carrier, as before
    for n_m in range(1, int(m ** 0.5) + 1):
        if m % n_m:
            continue
        for cycles in {n_m, m // n_m}:      # divisor pairs
            play = m // cycles
            if play > max_play or play < 1:
                continue
            n_c = int(round(carrier / play))
            # At least 8 table entries per carrier cycle. Nyquist alone (2)
            # is not enough: a table holding 8000 carrier cycles in 16384
            # entries technically satisfies it while representing the carrier
            # with 2.05 points, and the reconstruction is then all alias. The
            # configuration measured working on 2026-08-28 had 80 cycles --
            # 204.8 points each -- and the DAC's 250 MS/s is the real limit
            # on the output either way.
            if n_c < 1 or n_c > ASG_BUFFER_MAX // 8:
                continue
            if n_c + cycles >= ASG_BUFFER_MAX // 2:
                continue
            err = abs(n_c * play - carrier)
            found = (n_c, cycles, play)
            # Fewest MODULATION cycles first, because mod_cycles multiplies
            # whatever error the board has in the play rate and puts it on the
            # frequency the lock-in must match. Carrier error only breaks ties.
            if err <= carrier_tol:
                key = (cycles, err)
                if best_near is None or key < best_near[0]:
                    best_near = (key, found)
            # Kept so a modulation whose every pairing misses carrier_tol is
            # still plannable rather than suddenly refused.
            key_any = (err, -play)
            if best_any is None or key_any < best_any[0]:
                best_any = (key_any, found)
    best = best_near or best_any
    return None if best is None else best[1]


def make_am_table_exact(carrier: float, modulation: float,
                        fs: float = BASE_SAMPLE_RATE,
                        depth: float = 1.0) -> AsgTable:
    """An AM table whose MODULATION comes out exact, or raises.

    Same table construction as `make_am_table`; the difference is entirely in
    the play rate, which is chosen to fit rather than assumed. The carrier
    lands on the nearest multiple of that rate -- see plan_exact_am for why
    that is the right trade here.

    Use this when the modulation frequency matters and `make_am_table` when
    staying on the default grid matters; the grid path is the one Phase 1
    verified.
    """
    if not 0 < depth <= 1.0:
        raise ValueError("depth must be in (0, 1]")
    found = plan_exact_am(carrier, modulation, fs)
    if found is None:
        f_m, n_m = snap_to_asg_grid(modulation, fs)
        raise ValueError(
            f"no exact table for {carrier / 1e6:g} MHz with "
            f"{modulation / 1e3:g} kHz modulation: they are not in a ratio "
            f"that fits whole cycles in {ASG_BUFFER_MAX} entries. The nearest "
            f"on the default grid is {f_m / 1e3:.4f} kHz."
        )
    n_c, n_m, play = found
    k = np.arange(ASG_BUFFER_MAX)
    env = 1.0 + depth * np.cos(2 * np.pi * n_m * k / ASG_BUFFER_MAX)
    wave = env * np.cos(2 * np.pi * n_c * k / ASG_BUFFER_MAX)
    wave = wave / np.max(np.abs(wave))
    return AsgTable(samples=wave, play_freq=float(play),
                    carrier=n_c * float(play), modulation=n_m * float(play),
                    carrier_cycles=n_c, mod_cycles=n_m)


def make_cw_table(carrier: float, cycles: int = 80,
                  fs: float = BASE_SAMPLE_RATE,
                  max_play: float = 10e6) -> AsgTable:
    """An UNMODULATED carrier: constant envelope, one spectral line.

    This is what modulation = 0 means on this bench. Note it is **not** a DC
    voltage -- the AOM needs its 80 MHz acoustic drive, and the amplifier is
    AC-coupled, so a literal DC level would do nothing at all. What is held
    constant is the ENVELOPE.

    It is also the configuration Kevin tuned the drive level in: maximise the
    diffracted light with an unmodulated carrier, then modulate it. See
    `04-board-reference.md`, and do not add an attenuator.

    **Average RF power is about 3 dB higher than depth-1 AM at the same
    amplitude**, because the AM envelope spends half its time below full. That
    is the condition the drive was tuned at, so it is the reference rather than
    a new hazard -- but it is the loudest thing this generator emits.

    80 carrier cycles at carrier/80 is the pairing measured working on
    2026-08-28: 204.8 table entries per carrier cycle, well clear of the
    8-entry floor, and a 1 MHz play rate for an 80 MHz carrier. The play rate
    is rounded to whole hertz, which places the carrier within `cycles`/2 Hz --
    40 Hz on 80 MHz, or half a part per billion.
    """
    if carrier <= 0:
        raise ValueError("carrier must be positive")
    n_c = max(int(np.ceil(carrier / max_play)), int(cycles))
    if n_c > ASG_BUFFER_MAX // 8:
        raise ValueError(
            f"{carrier / 1e6:g} MHz needs {n_c} carrier cycles in the table, "
            f"which leaves under 8 entries per cycle and reconstructs to "
            f"alias rather than a carrier.")
    play = float(round(carrier / n_c))
    if play < 1:
        raise ValueError(f"{carrier / 1e6:g} MHz is too low for a CW table")
    k = np.arange(ASG_BUFFER_MAX)
    wave = np.cos(2 * np.pi * n_c * k / ASG_BUFFER_MAX)
    # modulation is reported as 0.0: there is none, and callers key off that.
    return AsgTable(samples=wave, play_freq=play, carrier=n_c * play,
                    modulation=0.0, carrier_cycles=n_c, mod_cycles=0)


def make_sine_table(freq: float, fs: float = BASE_SAMPLE_RATE,
                    max_play: float = 10e6) -> AsgTable:
    """A single clean tone -- no carrier, no modulation, one line.

    This is what a carrier of 0 means on this bench: not an AM waveform with
    the carrier removed, but a plain sine at the modulation frequency, for
    driving something directly or for feeding a known tone into the lock-in.

    **One cycle in the table, played at the frequency itself.** That makes any
    whole number of hertz exact, which matters here more than anywhere else:
    the lock-in will usually be told to sit on this frequency, and a few
    hertz of error comes back as a slow beat rather than as an error. The
    80-cycle pairing `make_cw_table` uses would round the play rate and put
    915 kHz out by 40 Hz.

    16384 entries per cycle is far more than the reconstruction needs; the DAC
    samples the table at 250 MS/s regardless, giving 250 output samples per
    cycle at 1 MHz.

    Both `carrier` and `modulation` on the returned table are the tone itself,
    so the Demodulate panel's f1 button lands on it.
    """
    f = int(round(freq))
    if abs(f - freq) > 1e-6 or f < 1:
        raise ValueError(
            f"a single tone must be a whole number of hertz, got {freq!r}. "
            f"The play rate is quantised to 1 Hz, and this table holds one "
            f"cycle played at the frequency itself.")
    cycles = max(1, int(np.ceil(f / max_play)))
    play = float(f) / cycles
    if play != int(play):
        raise ValueError(
            f"{f} Hz needs {cycles} cycles to stay under the {max_play:g} Hz "
            f"play-rate ceiling, and does not divide by {cycles} exactly.")
    k = np.arange(ASG_BUFFER_MAX)
    wave = np.cos(2 * np.pi * cycles * k / ASG_BUFFER_MAX)
    return AsgTable(samples=wave, play_freq=play, carrier=cycles * play,
                    modulation=cycles * play, carrier_cycles=cycles,
                    mod_cycles=cycles)


def plan_two_tone_grid(difference: float = 1e6, f1: float = 5e6,
                       carrier: float = 80e6,
                       fs: float = BASE_SAMPLE_RATE) -> GridTwoTonePlan:
    """
    Two-tone plan on the ASG's fs/16384 grid.

    This is the hardware-correct planner. `plan_two_tone` solves a different
    problem -- the shortest exactly-commensurate buffer -- which is sound
    arithmetic but does not match how this generator works.

    Both tones are snapped independently, which is what puts f2 at 393 cycles
    (5.996704 MHz) and the difference at 991.821 kHz. Snapping the *difference*
    instead and adding it to f1 would give 394 cycles and 1.00708 MHz -- also
    exact, just a different choice about which quantity stays nearest nominal.
    Neither accumulates error: once both tones are integer cycle counts, their
    difference is a whole number of grid steps by construction. The values here
    are the ones agreed with Kevin on 2026-08-12.
    """
    _, n_c = snap_to_asg_grid(carrier, fs)
    _, n_1 = snap_to_asg_grid(f1, fs)
    _, n_2 = snap_to_asg_grid(f1 + difference, fs)
    if n_2 == n_1:
        raise ValueError(
            f"difference {difference:g} Hz is below the ASG grid "
            f"({asg_grid(fs):.4f} Hz) -- f1 and f2 would land on the same "
            f"grid point and there would be no difference frequency."
        )
    grid = asg_grid(fs)
    if n_c + max(n_1, n_2) >= ASG_BUFFER_MAX // 2:
        raise ValueError("upper sideband is above Nyquist")
    return GridTwoTonePlan(
        carrier=n_c * grid, f1=n_1 * grid, f2=n_2 * grid, fs=fs,
        carrier_cycles=n_c, f1_cycles=n_1, f2_cycles=n_2,
    )


def make_am_waveform(carrier: float, modulation: float,
                     fs: float = BASE_SAMPLE_RATE,
                     depth: float = 1.0) -> tuple[np.ndarray, float]:
    """
    Build the shortest seamless repeating buffer for an AM carrier.

    *** DO NOT USE THIS TO DRIVE THE BOARD. Use make_am_table(). ***

    The arithmetic here is correct and the tests that pin it are worth keeping,
    but it models a generator that replays exactly the N samples you load at
    fs/N. The real ASG does not: it always traverses a fixed 16384-entry table.
    Loading the 50-sample buffer this returns and playing it at 5 MHz produces
    NO OUTPUT AT ALL -- measured, min -2 max +4 counts. See the module header
    and docs/04-board-reference.md.

    The buffer must contain a whole number of cycles of BOTH the carrier and
    the modulation, so the minimal length is the smallest N with N*carrier/fs
    and N*modulation/fs both integers. For 80 MHz AM'd at 5 MHz on the 250 MS/s
    board that is 50 samples; at 6 MHz it is 125. Do not assume N = fs/f_mod --
    that only happens to be right when fs/f_mod is itself an integer.

    Getting this wrong is not a subtle error: a fractional buffer glitches at
    every wrap, putting spurs at multiples of fs/N straight across the baseband
    where the swept trace lives.

    Returns (samples, playback_frequency). Load `samples` into the generator's
    arbitrary buffer and set the generator frequency to `playback_frequency`
    = fs/N, which advances the buffer exactly one sample per DAC clock.

    Raises ValueError if no buffer within the generator's depth works.
    """
    if not 0 < depth <= 1.0:
        raise ValueError("depth must be in (0, 1]")
    if not 0 < carrier < fs / 2:
        raise ValueError(f"carrier must be below Nyquist ({fs / 2 / 1e6:.1f} MHz)")
    if not 0 < modulation < carrier:
        raise ValueError("modulation frequency must be below the carrier")

    n = _minimal_buffer(fs, (carrier, modulation))
    if n is None:
        raise ValueError(
            f"No buffer <= {ASG_BUFFER_MAX} samples holds whole cycles of both "
            f"carrier={carrier / 1e6:g} MHz and modulation={modulation / 1e6:g} MHz "
            f"at {fs / 1e6:g} MS/s, so every wrap would glitch. Move the "
            f"frequencies onto the fs/N grid -- see docs/03-frequency-plan.md."
        )

    k = np.arange(n)
    env = 1.0 + depth * np.cos(2 * np.pi * modulation * k / fs)
    wave = env * np.cos(2 * np.pi * carrier * k / fs)
    wave = wave / np.max(np.abs(wave))     # normalise to the generator's -1..+1
    return wave, fs / n


def _minimal_buffer(fs: float, freqs, limit: int = ASG_BUFFER_MAX) -> int | None:
    """Smallest N <= limit making N*f/fs an integer for every f."""
    for n in range(1, limit + 1):
        if all(abs(n * f / fs - round(n * f / fs)) < 1e-9 for f in freqs):
            return n
    return None


@dataclass(frozen=True)
class TwoTonePlan:
    """A validated set of drive frequencies and the buffer that realises them."""

    carrier: float          # Hz, the AOM carrier both channels share
    f1: float               # Hz, modulation on channel 1
    f2: float               # Hz, modulation on channel 2
    buffer_samples: int     # length of the repeating buffer, both channels
    fs: float               # DAC sample rate

    @property
    def difference(self) -> float:
        """The lock-in frequency: where the DUT response appears."""
        return abs(self.f2 - self.f1)

    @property
    def buffer_period(self) -> float:
        return self.buffer_samples / self.fs

    def periods_per_tau(self, tau: float) -> float:
        """Cycles of the difference frequency inside one integration time.

        Lock-in detection needs this comfortably above ~5-10; below that the
        integrator has not seen enough of the waveform to average the carrier
        away, and the output carries residual 1f/2f ripple.
        """
        return tau * self.difference

    def check(self) -> list[str]:
        """Return a list of problems; empty means the plan is exact."""
        problems = []
        for name, f in (("carrier", self.carrier), ("f1", self.f1), ("f2", self.f2)):
            cycles = self.buffer_samples * f / self.fs
            if abs(cycles - round(cycles)) > 1e-9:
                problems.append(
                    f"{name}={f / 1e6:.6g} MHz gives {cycles:.6f} cycles per buffer, "
                    f"not an integer -> discontinuity at every wrap"
                )
        if self.buffer_samples > ASG_BUFFER_MAX:
            problems.append(
                f"buffer {self.buffer_samples} exceeds the generator's "
                f"{ASG_BUFFER_MAX}-sample limit"
            )
        if self.difference <= 0:
            problems.append("f1 and f2 must differ")
        if max(self.carrier + self.f1, self.carrier + self.f2) >= self.fs / 2:
            problems.append("upper sideband is above Nyquist")
        return problems

    def describe(self) -> str:
        lines = [
            f"carrier      {self.carrier / 1e6:g} MHz",
            f"f1           {self.f1 / 1e6:g} MHz   -> sidebands "
            f"{(self.carrier - self.f1) / 1e6:g} / {(self.carrier + self.f1) / 1e6:g} MHz",
            f"f2           {self.f2 / 1e6:g} MHz   -> sidebands "
            f"{(self.carrier - self.f2) / 1e6:g} / {(self.carrier + self.f2) / 1e6:g} MHz",
            f"|f2 - f1|    {self.difference / 1e6:g} MHz  "
            f"(period {1e6 / self.difference:.3f} us)  <-- lock-in frequency",
            f"buffer       {self.buffer_samples} samples = "
            f"{self.buffer_period * 1e6:.3f} us at {self.fs / 1e6:g} MS/s",
        ]
        problems = self.check()
        lines.append("exact: yes" if not problems else "PROBLEMS: " + "; ".join(problems))
        return "\n".join(lines)


def plan_two_tone(difference: float, f1: float = 5e6, carrier: float = 80e6,
                  fs: float = BASE_SAMPLE_RATE) -> TwoTonePlan:
    """
    Find the shortest exact repeating buffer for a two-tone AM drive.

    The buffer length N must make N*f/fs an integer for the carrier and both
    modulations simultaneously. For an 80 MHz carrier at 250 MS/s that forces
    N to be a multiple of 25; the modulations must then land on the resulting
    fs/N frequency grid.

    Raises ValueError if no buffer under the generator's limit works, rather
    than returning one that glitches at every wrap.
    """
    f2 = f1 + difference
    n = _minimal_buffer(fs, (carrier, f1, f2))
    if n is not None:
        plan = TwoTonePlan(carrier=carrier, f1=f1, f2=f2, buffer_samples=n, fs=fs)
        if not plan.check():
            return plan
    raise ValueError(
        f"No buffer <= {ASG_BUFFER_MAX} samples holds whole cycles of "
        f"carrier={carrier / 1e6:g} MHz, f1={f1 / 1e6:g} MHz and "
        f"f2={f2 / 1e6:g} MHz at {fs / 1e6:g} MS/s. Move the frequencies onto "
        f"the fs/N grid -- see docs/03-frequency-plan.md."
    )
