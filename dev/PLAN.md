# triald — functional scope

What has to survive the move out of VStim's `TrialTypeManager`, what it should
become on the way, and what is deliberately left behind.

Sources: `VStimLib/StimulusDefinition/TrialTypeManager.{h,cpp}`,
`TrialTypeManagerInterface.h`, `VStimLib/TDR.h`.

Status key: **done** — implemented and tested. **planned** — specified here, not
built. **open** — needs a decision before it can be built.

---

## The shape of the rig

The goal is everything VStim does, taken apart along the seams it already has:
**you can visually stimulate without running a trial, without a state machine and
without any response request.** Nothing is tied to a particular piece of
hardware, and a new kind of stimulator is an addition rather than an edit.

VStim is already modular — `TrialTypeManagerInterface`, `ExperimentControllerInterface`,
`DigIoInterface`, `EyeMonInterface`, `ObjectQueueInterface` are all there. What it
lacks is *separability*: those modules share one recursive mutex, pull from each
other synchronously, and hold raw pointers to one another, so no subset of them
can run alone. The work is making the existing boundaries real, not drawing new
ones.

### An hourglass on the trigger bus

```
   decide WHAT and WHEN                          slow bus · HTTP+JSON · per trial
  ┌────────────────────────────────────────────────────────┐
  │ triald    trial types · sets · counters · policy       │  optional
  │           stop rules · acceptance · the record         │
  └────────────────────────────────────────────────────────┘
        │  configure(trial_id, trial_type) → ready → start
        │  contribute(trial_id, …) · result(trial_id, outcome)
  ═══════════════ virtual trigger lines ═══════════════════   fast bus · shm
  ┌─────────┬─────────┬─────────┬──────────┬───────────────┐
  │ vstimd  │ soundd  │ optod   │  daqd    │      MCU      │  each optional
  │ scene · │ audio   │ laser   │ TTL ⇄ VTL│ response ·    │
  │ armed   │         │         │          │ outcome ·     │
  │ anims   │         │         │          │ reward        │
  └─────────┴─────────┴─────────┴──────────┴───────────────┘
   do WHAT, coupled to each other by edges
```

**The virtual trigger line is the waist.** Everything above it decides what a
trial *is*; everything below it does something when an edge arrives. A VTL is a
VTL whether it was raised by a GPIO edge, by an armed animation finishing, by the
microcontroller, or by a person clicking a button — which is what "not tied to
hardware" means in practice. daqd is not privileged: it is the module that
bridges real TTL lines to virtual ones, and a rig with no TTL hardware simply
does not run it.

### There is no central state machine

The most important thing about this picture is what is *not* in it. VStim needs a
central `ExpCtrl` because it is one process with one thread: somebody has to own
the sequence position. Spread across participants coupled by trigger lines, that
central executor **dissolves**.

vstimd already does the half that is visual. Its animations arm on an input line,
run for an exact number of frames, pulse output lines, and **chain each other
entirely inside the server** through VTL output edges — polled at frame start,
committed at vblank, with no network round trip. A visual timeline is expressible
today with nothing above it.

What the animation vocabulary cannot do is name an **outcome**. Nothing in
*flash · couple · move · flicker* with start/final/cancel actions can say that
timing out here means `LATE` and timing out there means `NOT_STARTED`. That is
the half the microcontroller takes: response windows, correct channels, timeouts,
reward, and the outcome to name when nothing happens.

The two halves agree through **edges** — vstimd pulses stimulus onset, the MCU
opens its response window on that edge — which is the same mechanism that already
makes reaction times correct with no clock synchronisation anywhere.

So: **the lines are the state machine.** `Interval`'s branch table
(`m_virtualTriggerNextStateMappings`) does not move to a new home; it decomposes
into per-participant armed behaviour plus a coupling contract.

### Lifetimes, not just layers

The lower a module sits, the longer it lives. This is the part that is easy to
get wrong by thinking of the stack as a call graph.

| Module | Lifetime | Between trials | With no session at all |
|---|---|---|---|
| vstimd · soundd · optod · daqd · MCU | the rig — **always on** | still rendering, still bridging lines | still running |
| triald | one session | deciding the next trial | not needed |

**Always-on visual stimulation is a requirement, not a side effect.** It has
already proved its worth: you need a stimulus on the screen to align the animal,
check the display, measure luminance or debug a scene, with no experiment running
anywhere and nothing to arm. A renderer that only exists inside a trial cannot do
any of that.

So `configure` is a **borrow, not a boot**. vstimd always has a scene — a
background, a fixation point, whatever was last set. A trial says "for trial 42,
present this one" and hands it back afterwards. The readiness gate asks *are you
configured for trial 42*, never *are you alive*, which is why it can answer in
microseconds.

### Two channels, and why every module needs both

A participant needs to know *what* to do as well as *when*. Those are different
questions with different budgets, and keeping them apart is what makes the layers
separable.

| | Configure | Trigger |
|---|---|---|
| Carries | what this module does on trial *n* | now |
| Rate | once per trial | per event, per frame |
| Bus | slow | fast |
| Source | triald, or set by hand | a VTL edge |

A module that never varies per trial needs only the trigger channel. A module
being driven by hand for a demo needs only the configure channel plus somebody to
raise a line. Neither case requires anything above it to exist.

### Run any subset

This is the test of whether the decomposition is real:

| Running | Gets you |
|---|---|
| vstimd alone | a stimulus you trigger by raising a VTL by hand — alignment, display checks, luminance |
| vstimd + daqd | armed animations firing on real TTL pulses. No trial, no outcome, no response |
| + MCU | a paradigm: response windows, reward, an outcome — one condition, forever |
| + triald | conditions, weights, counters, blocks, switching, acceptance, the session record |
| soundd + optod + daqd + MCU | a screenless optogenetics rig, no renderer anywhere |

### Every module is scriptable on its own

For plenty of work the right answer is **a Python script that drives visual
stimulation and nothing else** — a psychophysics experiment, a demo, a teaching
exercise, an alignment routine. That has to be a first-class way to use the rig,
not a degraded mode you reach by disabling things.

So every module carries its own control API on the slow bus. triald is not
privileged here; it is simply the module that happens to know about trial types.
A script talking to vstimd is just another configure-channel client, and somebody
using the rig that way never has to learn that triald exists.

The honest limit is timing, and it produces a gradient rather than a cliff:

| How you drive it | Timing | Good for |
|---|---|---|
| script → vstimd, call by call | ~1 ms jitter, slow bus | demos, alignment, psychophysics at second scale |
| script → vstimd, arming animations on lines | frame-accurate, executed on the device | anything where onset matters |
| + MCU with an outcome table | frame-accurate, with responses and branching | a paradigm |
| + triald | all of the above, plus conditions, counters, blocks, the record | an experiment |

Nothing outside the render loop can be frame-accurate, so the second row is the
important one: a script that needs precise onsets *arms* behaviour and lets the
device execute it, rather than driving it a call at a time.

### Extending it

A new stimulator — an olfactometer, a laser, a tactile probe — implements four
things and **nothing above it changes**:

1. subscribe to the trigger bus, and act on an edge;
2. optionally raise VTLs of its own (onset, fault, done);
3. optionally accept `configure(trial_id, trial_type)` and answer `ready(trial_id)`,
   if what it does varies by trial;
4. register itself, so it joins the readiness gate and appears in the session
   record with its version and its own free-form `info`.

Steps 3 and 4 are the only ones triald knows about, and both are generic: triald
learns that a participant exists, never what an odour is. That is the same
promise `TrialType.params`, `Device.info` and `SessionEvent.data` already make —
stored, returned, never interpreted.

If adding a stimulator ever requires a change in triald, the boundary is in the
wrong place.

### One process or several is a deployment choice

**The module boundaries are the deliverable; the process boundaries are
packaging.** Get the two channels right and the same code runs as one native
binary hosting modules over an in-process bus, or as separate daemons over shared
memory, without the modules knowing which.

Two things are settled, and one deliberately is not:

- **triald is its own process.** It is Python, it is on the slow bus, and it has
  no timing budget. That is not up for revisiting.
- **The fast tier must be co-located**, whatever the process count. A tone, a
  laser pulse and a frame that have to land within a millisecond of each other
  need one clock and one machine. Shared memory reaches across processes on a
  box; nothing reaches across boxes at that precision.
- **How many native processes the fast tier is** stays open. The bus contract is
  what lets that decision be made late, and changed.

The honest risk of many processes is not latency — shared memory settles that —
but operational surface: N units, N configs, N logs, and explicit CPU affinity
and priorities, or the real-time modules preempt each other. That cost is real
and is the reason not to split further than the seams require.

### Where the modules come from

Every module is a VStim class, and most of the calls between them already exist
as virtual methods. That is the check on whether a boundary is in the right
place: **a cross-module call should already be a virtual in a VStim
`*Interface.h`** — and if it has no counterpart, either it is genuinely new or
the seam is wrong.

| Module | VStim | Interface already there |
|---|---|---|
| triald | `TrialTypeManager` | `TrialTypeManagerInterface` |
| vstimd | rendering, object queue, and now the visual half of `ExpCtrl` | `ObjectQueueInterface` |
| daqd | `DigIO` | `DigIoInterface` |
| MCU | the outcome half of `ExpCtrl` · `Interval` · `Valve` | `ExperimentControllerInterface` |
| eye | `EyeMon` | `EyeMonInterface` |

`ExpCtrl` is the one class that does not survive as a unit — see *The interval
table, decomposed*.

Two calls have to invert, both because a process boundary cannot be crossed
synchronously for free:

- **`GetNextTrialType()`** is pulled by the controller at `ExpCtrl.cpp:175`.
  It becomes a push — see *Who initiates a trial* under Open questions.
- **`WriteTrialResultsToTdr(eyeMon, commonResources, objectQueue)`** has the trial
  type manager reaching into the eye monitor and the object queue at trial end.
  It becomes contribution rather than collection — see *Contributions, not one
  report*.

### The trial, end to end

```
triald    decide the type · switch the set if due · check the stop rules
   │      roll this trial's random interval durations, into the record
   │      configure(trial_id, trial_type)  ──▶  every registered participant
   │      ready(trial_id)                  ◀──  all of them, or it does not start
   │      start(trial_id)                  ──▶  the participant that opens the trial
  ─── the fast bus, coupled by edges ──────────────────────────────────
          vstimd  armed animations run the visual timeline, pulse onset
          MCU     opens its window on that edge · reads the response ·
                  drives the valve · names the outcome
          daqd    bridges the real lines both ways
  ─── back on the slow bus ─────────────────────────────────────────────
   │      contribute(trial_id, …)          ◀──  vstimd: frame loss
   │                                       ◀──  eye: precise fixation
   │      result(trial_id, outcome, …)     ◀──  MCU
triald    count · accepted? · advance the round · switch · record · publish
```

The fan-out overlaps the previous trial's inter-trial interval, so the slow-bus
round trips hide inside it. That is what makes push affordable — and it is also
the hazard: a participant can be told about trial *n+1* while another is still
finishing *n*. **Configuration is staged and swapped at the start edge**, never
applied on receipt. VStim already has the shape, latching `m_RecordingTrial`
inside `GetNextTrialType()`; here the latch moves to the participant.

Note which facts travel on which bus. **The fast bus carries what must be
*timed*; the slow bus carries what must be *recorded*.** Frame loss and precise
fixation are recorded facts that also happen to veto acceptance — and acceptance
is decided in triald, at leisure, after the trial. Neither needs to reach anybody
within a frame.

Two invariants carry the correctness across every participant, and they are the
same two the microcontroller link already has:

- **`trial_id` on every message** — configure, ready, contribution, result. A
  late or missed message cannot be attributed to the wrong trial.
- **No trial starts that every participant was not confirmed configured for.**
  `StartPermittable()`, distributed. A refusal is a recorded event, not a log
  line.

## The trial loop

Eight steps. Every capability below hangs off one of them. In VStim the whole
cycle runs on the render thread under one recursive mutex; here it is an explicit
object that can be stepped, simulated and replayed.

| # | Step | Notes |
|---|---|---|
| 1 | **Arm the session** | Validate everything and refuse rather than fail later — a loaded set, a sound switch chain, a policy that imports and smoke-runs. VStim's `StartPermittable()`. |
| 2 | **Select the trial type** | Draw from the bag, or hand the decision to `select_trial()`. |
| 3 | **Publish the selection** | Trial number, type number and name, time sequence, reward, and whether it records — all latched now, stable for the whole trial. |
| 4 | **Run it elsewhere** | vstimd renders; the microcontroller watches. triald waits. |
| 5 | **Report the outcome** | One code plus every modifier. The daemon's primary inbound message. |
| 6 | **Count it, and decide whether it counted** | Two separate questions. See below. |
| 7 | **Record it** | Append-only, flushed immediately. A write failure stops the experiment. |
| 8 | **Advance, switch, or stop** | Refill the bag, fire the switch rule, check the stop conditions. Back to 2. |

## Counted versus accepted

The single distinction most likely to be lost in a port, and the one the tests
guard hardest.

- **Counted** — every reported outcome increments the per-type and total tallies.
- **Accepted** — only some outcomes consume a slot in the round, advance the
  round, and move a set towards its switch rule.

Three independent things decide acceptance, and **any of them can veto**:

1. the outcome's own accept flag,
2. frame loss, when frame-loss trials are not accepted,
3. imprecise fixation, when those are not accepted.

A hit that lost a frame is still a hit — it counts, it moves the set's hit
criterion, and it does not consume from the bag.

---

## Capability inventory

### Trial types and sets — **done**

| | |
|---|---|
| Trial type | name, trials-per-round weight, time sequence, reward ms, `params` |
| Set | named collection plus its own switch rule, so the rule travels with it |
| Store | add, get, list; validation of the whole switch chain |
| Extended numbering | `set_number * 256 + index`, for `.tdr` compatibility |
| Name reconciliation | fill blanks across sets without overwriting (#538) |
| Copy names to all | explicit overwrite, for when names genuinely disagree (#538) |

**New:** sets are addressed **by name**, not a 1-based index — an index-based
rule points somewhere else the moment sets are reordered. `TrialType.params`
carries paradigm values (a contrast, a coherence) so a continuous adaptive
procedure has somewhere to put its level.

### Selection and ordering — **done**

Five orderings, draw-without-replacement from a per-type remaining count,
avoid-repeat, refill at the end of a round or experiment.

| Ordering | The bag holds | The draw |
|---|---|---|
| `random_in_round` | one round | weighted over what is left |
| `random_in_experiment` | every round at once | weighted over what is left |
| `ascending` | one round | the lowest index with anything left |
| `descending` | one round | the highest index with anything left |
| `random_with_replacement` | one round's worth of quota | weighted over the **configured** weights |

**New: `descending` and `random_with_replacement`.** The first is the mirror of
`ascending`, so a ladder of difficulties runs easy-to-hard under one and
hard-to-easy under the other without anybody renumbering the trial types. Both
deterministic orderings ignore `avoid_repeat` - they have nothing to avoid a
repeat with, and honouring the flag would mean not running the weights.

`random_with_replacement` is the only one that puts the token back: each trial is
an independent draw and a round is balanced only in expectation, which is what
you want when a subject can learn that a condition is used up. Its round is still
`trials_per_round` accepted trials long - it has to be, or rounds and the stop
rules would mean nothing - so per-type `remaining` reads as the quota still owed
and can sit at zero while the round runs on. `TrialBag.total_remaining` is the
authority for the round in every ordering.

**New: `P(next)`.** `TrialBag.probabilities()` answers VStim's
`GetProbabilityOfNextTrialType` for all five orderings, including 1 and 0 for the
deterministic pair. It describes the declarative ordering, so it is advisory: a
policy whose `select_trial` returns a type is never consulted through it.

**New:** a seeded `random.Random` recorded with the session. VStim's
`rand() % n` is biased towards low indices and unseedable in practice, so a VStim
session cannot be reproduced. This is what makes replay possible.

### Outcomes and acceptance — **done**

The eleven-code taxonomy with its `.tdr` numeric values intact, per-outcome
accept flags with VStim's shipping defaults, and the two cross-cutting vetoes.
Counters per trial type and in total.

**New:** outcomes arrive over an interface rather than as method calls from the
render thread.

### Rounds, blocks and stopping — **done**

Round = sum of the weights; experiment = rounds × round. Stop when rounds are
done; stop after N accepted trials (#460); reset rounds and reset counters as
separate operations.

Stop-after-N takes a **criterion** of its own — accepted trials, hits, or every
completed trial whatever it ended in. The same `TrialCountCriterion` the switch
rule uses, because the question is the same one and two enums would drift.

The stop is **latched**, so it fires once per counter reset rather than on every
trial after the count is passed, and compares `>=` rather than an equality that
would silently never fire again if a counter jumped.

### Automatic set switching — **done** (#239)

A rule per set (enabled, criterion, count, target). Two criteria: accepted trials
or hits in the current set. Progress resets on a switch, on a reset, and whenever
a set is loaded. Unusable targets are refused — a missing set, the set already
running, or a set with no trials in it, which would otherwise divide by zero. The
whole chain is validated at arm time, so a set three hops away that nobody filled
in is caught before a session is left alone with it overnight.

Three criteria, shared with the stop rule: accepted trials, hits, or every
completed trial. Each set carries its own criterion and count, so the stages of a
sequence can be judged differently.

**A sequence is what a chain of rules makes** — there is no separate type for it.
Two sets pointing at each other alternate; three walk in order; a set with no
rule ends the walk. `fixation → one_line → one_half_cyc` is the shape a training
session is actually left alone with overnight, and is what `triald sim` runs.

A switch restarts round counting and the new set's block progress, while the
**session totals keep climbing across it**.

**Stopping wins over switching**: there is nothing to switch to once the
experiment is ending. VStim orders these the same way in `OnTrialCompleted()`.

Faithful to VStim: **only `HIT` counts towards the hit criterion**, not
`EARLY_HIT` — VStim increments `m_HitsInCurrentSet` in `OnHit()` alone. Worth
revisiting with the lab, since it changes how long a training block runs.

#### Counters are banked per set

With **extended trial type numbers** the sets are separate experiments whose
trial type 3 have nothing to do with each other, so each set keeps its own
counters. Without the extension, trial type 3 means the same thing in every set —
it plays the same objects and shares its name (#538) — so they share one bank.
VStim reaches the same result with a `CounterOffset` into one flat array.

Banking rather than clearing on load is what stops a session that alternates
between two sets losing a set's counts every time it comes back to it. Reset
Counts clears every bank, not only the loaded one.

### Scripting — **done**

A policy is a Python class with five optional hooks plus `snapshot()`. Returning
`None` from `select_trial` falls through to the declarative ordering. Every hook
is wrapped: an exception is logged with a traceback, recorded against the trial,
and the session carries on.

Up/down staircases ship in `triald.adaptive` with no dependencies. QUEST, Psi and
interleaved staircases come from `questplus` or PsychoPy — see *The runtime
environment* below.

#### How a policy reaches the daemon — **planned**

Today `load_policy()` takes a filesystem path on the machine running the daemon,
which is all `triald sim` needs. Over the network that is the wrong shape: the
rig is not your laptop.

**The daemon receives the source text and owns it from then on.**

```
1. write     my_staircase.py in your editor, under git
2. check     trialctl policy check my_staircase.py   uploads, smoke-runs, discards
3. load      trialctl policy load  my_staircase.py   uploads, stores, arms
4. daemon    writes /var/lib/braemons/triald/policies/<sha256>.py, imports it,
             swaps it in at the next trial boundary — never mid-trial
5. record    manifest.json carries the sha256 and a verbatim copy
```

Three reasons the daemon must hold the text rather than a path:

- the web editor needs to show and edit it, and a path means nothing to a browser
  on another machine;
- **provenance** — "which version of the staircase ran on Tuesday?" has to be
  answerable from the session directory alone, and a filename cannot answer it
  because the file changes. Same argument as recording the RNG seed;
- otherwise every policy change needs scp or a file share, which is how a rig
  ends up running a script nobody can find the source of.

Loading from a path stays as the escape hatch, for a lab keeping policies in a
git checkout on the rig itself. Either way the record is written the same way:
hash plus a stored copy.

**This is remote code execution by design, and should be a choice rather than a
discovery.** Fine on an isolated rig network — it is what makes the daemon useful
— but: bind to localhost or the rig subnet by default, never `0.0.0.0`; keep
running as the unprivileged `triald` user under `ProtectSystem=strict`; and offer
a rig-config flag that refuses uploads and loads only from a trusted directory.
The `Policy` API can only return decisions, but a policy is still Python in the
daemon's process — the sandbox is the process boundary and the systemd unit, not
the base class.

### Session recording — **done**

A session record has to be readable years later by somebody who was not there, so
it carries considerably more than trials. One directory per session:

| File | Holds |
|---|---|
| `manifest.json` | who, what, which devices, the config, the seed. A header: written at open, refreshed at close. |
| `trials.jsonl` | one line per trial, appended the moment it ends. Append-only. |
| `events.jsonl` | everything that was not a trial. Append-only. |
| `summary.json` | counts and the stop reason. |

Flushed per trial, so a crash costs at most the trial in flight. Records carry
the policy's own state, so an adaptive session is reconstructable. A write
failure stops the experiment by default.

#### Metadata

Well-known fields, grouped as VStim groups them in `SessionMetadata`, because the
grouping says what the UI should do with each one:

- **automatic** — session id, times, host, software versions, devices;
- **automatic with review** — experimenter, lab, institution, subject; filled in
  from the rig config and shown for confirmation, because a stale experimenter
  name is worse than a blank one;
- **manual** — session type and description, keywords, notes, the `has_*` flags
  saying what else was recorded alongside, total reward.

**Field names follow NWB** — `subject_id`, `species`, `sex`, `experimenter`,
`lab`, `institution`, `session_description`. The lab's recordings end up in NWB
or beside something that is, and a mechanical name-for-name conversion is worth
more than names we happen to prefer.

**Devices register themselves.** Every daemon and instrument that touched the
session appears in `devices` with its version and a free-form `info` block —
vstimd with its display mode, the microcontroller with its firmware hash, the
DAQ, the eye tracker, the acquisition system. The record then says what produced
it without anybody having to remember.

#### Custom messages

Three places take arbitrary JSON, and **triald never interprets any of them** —
stored and handed back verbatim, exactly like `TrialType.params`:

- `SessionMetadata.extra` — whatever this lab needs that triald has never heard
  of. Namespace your keys (`{"bremen": {...}}`) so a field triald adds later
  cannot collide with one of yours.
- `Device.info` — firmware hashes, display modes, sampling rates, serial numbers.
- a `SessionEvent`'s `data` — anything at all.

**Events are the custom-message channel.** An experimenter's note, a manual
reward, an electrode depth, a device reporting in, a correction to metadata typed
at the start. Each carries a `kind`, a `source`, the wall-clock time and the
trial in flight. Bare `kind` names are triald's own (`note`, `reward`,
`metadata`, `device`, `policy_error`); namespace your own with a dot
(`bremen.electrode_depth`).

Two rules keep the record trustworthy:

**Corrections are appended, never applied in place.** Realising at trial 50 that
the subject ID was typed wrong writes a new event; the manifest shows the final
answer and the event stream shows that it changed and when. A record that
silently shows only the final answer cannot be audited. An unknown metadata field
is refused outright, so a typo cannot vanish into a record nobody checks.

**Payloads are capped at 64 KiB and strictly checked.** Somebody will eventually
try to put an array in here; a record indexes what happened, and bulk data
belongs in its own file referenced by path. The serialisation check is strict on
purpose — with a `default=str` fallback a `set` would be written as `"{1, 2, 3}"`
and read back as a string, which is silent corruption of something nobody
re-checks for years.

Policy failures are recorded as events as well as logged, so a session that
misbehaved at trial 200 can say why from its own directory.

### Config and persistence — **planned**

Two configs, always named:

- **rig config** — the physical setup: endpoints, results directory, serial port,
  `policy_dir`, `extra_packages`. TOML at `/etc/braemons/triald-rig-config.toml`. Changes
  when the hardware does.
- **session config** — one experiment: sets, ordering, accept flags, stop rules,
  policy. Changes per session.

Needs: round-trip to a human-readable file, and an importer for existing VStim
configurations.

`policy_dir` is where the daemon stores uploaded policies. It is deliberately
*not* the earlier `policy_path`, which conflated two unrelated things — where
policies come from, and where their dependencies live. Dependencies are the
runtime environment's problem, below.

### The runtime environment — **planned**

**numpy and scipy ship in the package.** Without numpy, "scriptable in Python" is
a hollow promise — the first thing anyone writes wants `np.array`, and
`questplus` requires numpy plus xarray. scipy earns its place for `scipy.stats`
psychometric functions and `scipy.optimize` fitting. Roughly 20 MB and 60 MB
against a vendored-CPython package already around 50–80 MB; modern scipy wheels
bundle their own OpenBLAS, so there is no BLAS/LAPACK mess to inherit.

The asymmetry decides it: not shipping them is discovered at 2 a.m. when a policy
will not load on the rig. Shipping them costs 60 MB. If the Raspberry Pi image
ever gets tight, scipy splits into a `triald-scipy` package that the main one
`Recommends:` — installed by default, removable. Not worth doing pre-emptively.

**For everything else, extend the environment that is actually running.** The
vendored tree at `/opt/braemons/triald` is a real Python installation, so:

```
trialctl env install questplus psychopy
trialctl env list
trialctl env freeze > rig-packages.txt
```

serviced by `uv pip install --python /opt/braemons/triald/bin/python`. Everything
is ABI-compatible by construction because there is only one interpreter. This
replaces the earlier idea of a separate virtualenv on `sys.path`, which would
break the moment its Python differed from the vendored one — and fail with an ABI
error nobody enjoys reading.

Two things have to come with it or rigs drift out of step with each other:

- **declarative, not only imperative** — the rig config carries an
  `extra_packages` list applied at startup, so a rebuilt rig is reproducible and
  `env install` means "add to the list and apply";
- **in the record** — the session manifest carries the resolved package set, for
  the same reason it carries the seed and the policy hash. "Which questplus
  version produced Tuesday's thresholds" has to be answerable from the session
  directory.

Shipping numpy and scipy largely removes the need for any of this: most people
will never run `env install`. It exists for `questplus`, PsychoPy, and whatever a
lab has of its own.

**PsychoPy is never a dependency of the package.** It drags pyglet, wx and a GUI
stack onto a headless rig box. `env install psychopy` for labs whose triald
staircase has to match an existing PsychoPy experiment exactly; prefer the
standalone `questplus`, or `triald.adaptive`, otherwise.

### API surface — **done**, less two groups

Specified in full, with the reasoning, in [API.md](API.md); what follows is the
decision record behind it. `Environment` and `Records` are still **planned**, and
the config-file shapes still want models of their own.

**One transport: HTTP for request/reply, WebSocket for the state stream, JSON
throughout.** The web UI and all three clients use the identical API — there is
no mirroring layer.

This deliberately departs from vstimd, which speaks ZeroMQ and protobuf. Both of
protobuf's real benefits fail to arrive here:

- **wire efficiency** buys nothing against ~1 KB once per trial, with an
  inter-trial interval to spend;
- **one schema, many languages** does not survive contact with MATLAB, whose
  protobuf support is poor enough that its client was already going over
  HTTP/JSON — so the plan already had two wire formats before it had one client.

What is left is a `buf`/`protoc` step in every client's build, and a protocol
nobody can `curl`. For a tool people will poke at from MATLAB and a browser
console at 11pm, readable-on-the-wire is worth more than compact.

The same reasoning removes ZeroMQ: an HTTP round trip on a rig LAN costs about a
millisecond, in a gap measured in hundreds. Carrying two transports and two
encodings for one set of calls is twice the surface to build, test and keep in
step, for latency triald never needed.

vstimd's choice serves constraints triald does not have — a render loop and a
budget measured in frames. Copying it because it is vstimd's would be
cargo-culting. That leaves braemons with two daemons speaking different
protocols, which is a genuine wart and is accepted knowingly; there is no shared
client code between them to preserve. If binary and low-latency ever do matter,
the models below can gain a protobuf mapping without the API changing shape.

| Group | Calls | |
|---|---|---|
| Session | `POST /api/session/{arm,stop}`, `/session/recording/{start,pause,resume,stop}` | done |
| Trial loop | `POST /api/trial/{next,outcome,cancel}` | done |
| State | `GET /api/state`, `WS /api/stream` | done |
| Sets | `GET /api/sets`, `PUT`/`DELETE /api/sets/{name}`, `POST /api/sets/{name}/load` | done, less `SaveSet` to a file |
| Config | `GET`/`PATCH /api/config`, `POST /api/config/{reset-rounds,reset-counters}` | done |
| Scripting | `GET`/`PUT`/`DELETE /api/policy`, `POST /api/policy/check` | done |
| Events | `POST /api/events/note` | done |
| Debug | `GET`/`PUT /api/debug/sim`, `POST /api/debug/step`, `GET`/`PUT /api/debug/free-run` | done |
| Environment | `ListPackages`, `InstallPackages`, `GetEnvironment` | planned |
| Records | `ListSessions`, `GetSession`, `ReplaySession` | planned |

`GetCounters` folded into `GetState` rather than becoming a call of its own: the
counters are joined onto the trial type definitions server-side, so no client has
to match the two up, and one snapshot cannot disagree with another.

#### Contributions, not one report — **planned**

The trial loop closes a trial with one atomic `OutcomeReport`, which assumes a
single omniscient reporter. A rig made of separate daemons has no such thing:
vstimd knows the frame loss, the eye tracker knows whether fixation was precise,
the microcontroller knows the response and the reaction time, the valve knows what
was actually delivered. All four feed the accept decision.

VStim never had this problem, because `CurrentTrial` is an accumulator: the
`SetTdr*` family lets each subsystem write its piece *while the trial runs*, and
`OnOutcome()` closes it. The port kept the fields and lost the pattern.

With no central executor to aggregate on the fast bus, this is the *primary* path
rather than a fallback, and the division is clean: **the fast bus carries what
must be timed, the slow bus carries what must be recorded.** Frame loss and
precise fixation are recorded facts that happen to veto acceptance, and
acceptance is decided in triald after the trial. Neither has to reach anybody
within a frame.

So the trial loop gains the accumulator:

| `TrialTypeManagerInterface` | Wire |
|---|---|
| `SetTdr*(...)` | `PATCH /api/trial/current` - many callers, any time |
| `OnOutcome(code)` | `POST /api/trial/outcome` - one caller, closes the trial |
| `GetCurrentTrial()` | `GET /api/trial/current` |
| `StartPermittable()` | `GET /api/session/permittable`, now a distributed check |

Two things it must do that the C++ cannot. **`trial_id` on every contribution**,
so a late one cannot land on the next trial - the rule the behaviour source
already has and the wire dropped. And **`source` on every contribution**, so the
record says who claimed what; in VStim nothing records which subsystem set
`PreciseFixation`.

Per-field merge rules become explicit rather than implied. `SetTdrFrameLossTime`
is quietly *first*-write-wins - it keeps the first loss - while the rest are
last-write-wins. Invisible in C++, load-bearing on a wire where contributions can
arrive out of order.


The **debug group** is new and was not in this plan. It drives a
`SimulatedBehaviourSource` through `runner.run_trial` - the same four calls a rig
makes - so the whole daemon can be exercised with no hardware attached. It is not
a second code path pretending to be the first, which is the entire reason the
behaviour source is an interface.

`LoadPolicy` and `CheckPolicy` take **source text**, not a path — see *How a
policy reaches the daemon*. `CheckPolicy` returns diagnostics with line numbers
so the web editor can mark the offending line rather than printing a traceback
underneath it.

#### The schema survives; the compiler does not - **done for the wire**

Dropping protobuf drops the encoding, not the contract. **The wire schema is the
contract, not the Python API** — three clients are written against it, never
against `triald.Session`.

**Pydantic models → OpenAPI 3.1, which FastAPI emits for free → generated
clients.** Python and C#/.NET have mature OpenAPI generators; MATLAB skips
generation entirely and calls `webread`/`webwrite`. Schema evolution is by
convention rather than field numbers: add fields, never repurpose a name.

The models also consolidate three things that are separate today, which is worth
as much as the API:

| Today | With the models | |
|---|---|---|
| hand-written `as_dict()` in `state.py` | serialisation for free | not yet |
| config files parsed and validated by hand | validation with real messages, which matters for a file a scientist edits | not yet |
| the JSONL record shape, defined implicitly by `as_dict()` | the same models, so the record and the wire cannot drift | **done, by test** |

The third arrived without the first. `TrialRecordModel` was written to serialise
byte-for-byte to what `as_dict()` writes, and
`test_the_wire_and_the_record_carry_the_trial_identically` asserts it - which is
what turns retiring `as_dict()` from a risky refactor into a safe one. It is also
why the timestamp fields carry an explicit serialiser: pydantic spells UTC `Z`
where `datetime.isoformat()` spells it `+00:00`, and the record format has years
of files behind it, so the record wins.

This follows vstimd's own principle — *the config format is the runtime shape, no
DTO* — rather than adding a parallel set of transfer objects beside the
dataclasses. Converting `state.py` and the config types is a real refactor of
working, tested code; it belongs with the API work, not before it.

### Web interface — session view **done**; the editor and the charts **planned**

A proof of principle lives in `src/triald/web/`: three files, no build step, no
framework and no CDN, because a rig box may have no route to the internet and a
browser in a booth should not be waiting on unpkg. One WebSocket delivers a whole
`SessionState` on every change and the page redraws from it, so there is no
client-side model of the session that can disagree with the daemon about what is
happening.

It has the counters table with VStim's columns plus `P(next)`, the config
controls, the sets with their switch rules and live progress towards them, and a
debug panel that steps the simulated subject, free-runs it on a timer, or drives
one trial by hand through all eleven outcomes with the frame-loss and
imprecise-fixation modifiers - the cheapest way there is to watch a trial be
*counted but not accepted*.

Served by the daemon, no separate deployment, over the same HTTP and WebSocket
API the clients use rather than a second bespoke one.

**Session view.** Current trial type, trial number, per-type counters, progress
through the round and towards the switch rule, recent outcomes. The numbers VStim
shows in its counter dialogs, visible from any machine on the rig network instead
of the one keyboard in the booth. Plus editing the declarative config and the
trial type sets, starting and stopping recording, and reading the traceback when
a policy fails, against the trial that raised it.

#### The policy editor

**CodeMirror 6** with `@codemirror/lang-python` — about 200 KB, against Monaco's
2 MB-plus. Syntax highlighting, bracket matching and gutter error markers are
what this needs; it is not trying to be an IDE.

Because it should not become one. **The web editor is for a tweak between blocks,
not for authoring** — bump a threshold, fix a typo, restart the staircase, with
the real work in your own editor under git. If it becomes the primary path,
policies stop being version-controlled, which is one of the things triald exists
to fix. So:

- **read-only by default**, showing the running policy and its content hash;
- an explicit Edit mode, and **Check before Load is not skippable** — a syntax
  error must never reach a session;
- diagnostics marked in the gutter, from `CheckPolicy`;
- a visible **"edited in browser"** marker on a policy that did not come from a
  file, so a session record cannot quietly contain a script nobody has in git;
- swapped in at the next trial boundary, never mid-trial.

#### Performance graphs

Customisable, because every lab watches something slightly different and
hard-coding four charts guarantees three of them are the wrong ones.

The data model makes this cheap: **every trial is a row with a known schema**, so
a chart is a small declarative spec rather than code.

| Field | From |
|---|---|
| `trial_number`, `trial_type_name`, `set_name` | `TrialSpec` |
| `outcome`, `accepted`, `refusal_reason` | the acceptance decision |
| `reaction_time_ms`, `terminating_interval`, `precise_fixation`, `frame_loss`, `reward_ms` | the outcome modifiers |
| `params.*` | `TrialType.params` — contrast, coherence, whatever the paradigm has |
| `policy_state.*` | whatever `Policy.snapshot()` returned |

A spec picks a metric, an x-axis, an optional grouping, a window and a filter:

```toml
[[chart]]
title    = "Hit rate by contrast"
y        = "rate(outcome == HIT)"
x        = "params.contrast"
group_by = "set_name"
window   = 200          # trials; omit for the whole session
filter   = "accepted"
```

**Anything a policy puts in `snapshot()` becomes a plottable series for free** —
a staircase's level and reversal count are already in every trial record, so
the staircase trace needs no special support.

Ships with sensible defaults that a lab can then edit: running hit rate over
trials, performance per trial type, accuracy against a `params` value (a
psychometric curve), the staircase trace, reaction time over trials and its
distribution, outcome breakdown over time, session pace in trials per minute, and
progress towards the round and the switch criterion.

**uPlot** (~40 KB) for the rendering — it is built for live time series and
redraws cheaply at the 1 Hz the session view updates at. The chart vocabulary
here is narrow (line, bar, scatter over trials), so a full grammar of graphics is
more than the domain needs; if the spec starts growing towards one, Vega-Lite is
the thing to move to rather than to reinvent.

Two requirements that keep it useful rather than decorative: layouts are **saved
per rig** and travel with the rig config, and **the same spec works on a recorded
session**, so "why did Tuesday look odd" uses the same tool as the live view.
Export to PNG and CSV, so a chart can go into a lab notebook.

### Clients — **planned**

Three, against the OpenAPI schema rather than against each other. All three speak
the same HTTP and JSON, so none of them needs a code generator to *work* —
generation is a convenience for the typed ones, not a prerequisite.

**Python** (`client/python`) — the reference client, mirroring vstimd's. LGPLv3
rather than the daemon's AGPLv3, so importing it does not place an experiment's
own code under copyleft — the same split vstimd uses, and for the same reason.

**MATLAB** (`client/matlab`) — a thin wrapper over `webread` and `webwrite`,
which are built in and need no toolbox. This is the client that decided the
protocol: MATLAB's protobuf support is poor enough that it was going over
HTTP/JSON regardless, and a schema that one of three clients cannot use is not
doing the job it was chosen for. The `py.` bridge stays documented for anyone
wanting the typed Python client from MATLAB, with the caveat that it needs
MATLAB and Python versions that agree.

**Bonsai** (`client/bonsai`) — a `Bonsai.Triald` NuGet package exposing source
and sink operators over `HttpClient` and `ClientWebSocket`, both in the .NET base
library. Bonsai is reactive, so the mapping is unusually clean: the state stream
*is* an observable sequence, `NextTrial` is a source, and `ReportOutcome` is a
sink.

Each client ships the same small example — arm a session, run trials, report
outcomes — and CI runs it against the daemon, so the three cannot drift apart
silently.

### The microcontroller — **planned**, and no longer triald's peer

The microcontroller is a **participant on the trigger bus**, not something triald
holds a link to. It watches levers or lick ports, drives the valve, and **names
the outcome** - it is the half of VStim's interval table that vstimd's armed
animations cannot express. It arms on the edges vstimd raises, daqd bridges its
real TTL pins to virtual ones, and it reports the finished trial to triald over
the slow bus. triald never learns which channel a lick port is.

That is a change of position. It was previously specified as triald's own serial
peer, which put a hardware link and a firmware protocol behind the daemon that is
supposed to have no timing budget.

```
ITI      triald ──configure(trial_id, outcome table)──▶ MCU
         triald ◀──ready(trial_id)──────────────────── MCU   no trial without this
trial    [vstimd pulses stimulus onset; the MCU opens its window on that edge]
end      triald ◀──result(trial_id, outcome, RT, …)── MCU
```

Teensy 4.1 or RP2350 over USB CDC, newline-delimited JSON at 921600 with a CRC and
a sequence number; avoid ESP32 WiFi in the trial loop. `seq` covers link-level
retry, `trial_id` covers trial-level attribution — different jobs, both needed.

Three properties carry the correctness, and they are the same three every other
participant needs: `trial_id` on every message, so a late result cannot be
attributed to the next trial; the `ARMED` ack, so no trial runs that the MCU was
not confirmed configured for; and a **hardware** trigger edge, so reaction times
are relative to stimulus onset and need no clock sync. The MCU fails safe — valve
closed on watchdog timeout, reset, or link loss.

**The firmware never learns the trial type.** It receives channels, windows and a
reward duration, which is what keeps it stable while paradigms change. For a
two-port lick task that means `correct_response` as a *list* of channels: `[]`
for no response required, `[0]` for the left port, and `[0, 1]` for either —
which is how shaping starts.

#### What this leaves `behaviour.py` as

`BehaviourSource` is documented as "the microcontroller seam". It is now the
**simulator seam**: the interface `SimulatedBehaviourSource` implements so that
`triald sim`, the debug stepper and the tests drive the real trial loop rather
than a parallel one. That is worth keeping for exactly that reason, and
`SerialBehaviourSource` comes off the roadmap — a real rig's outcomes arrive from
the microcontroller over the slow bus, and its link is the rig's to own, not
triald's.

### The interval table, decomposed — **open**

VStim's `ExpCtrl` / `Interval` / `TimeSqz` / `Valve` (~4,700 lines) is the
*within*-trial state machine: a run of intervals, each waiting on a timer, a
trigger line, a gaze window or a response, and each naming where to go next and
which outcome to end on.

**It is a state machine that configures itself from the trial type.** A trial
type names a state graph — `TrialTypeConfig::iTimeSequence` in VStim, and
triald's own `TrialType.statemachine_graph` — the graph *is* the machine's configuration, and
the machine reloads it at the start of every trial. Choosing a trial type and
choosing a state machine are one act. That is why the trial type is the join key
between triald's configuration and everything below it, and why neither side owns
a paradigm on its own.

The coupling runs both ways. `TimeSequence::Update(currentFrame, ttm, …)` takes
the trial type manager and calls into it while the trial runs: the `SetTdr*`
family is how each interval writes what it learned into `CurrentTrial`, and
`TerminateSequenceWithOutcome` is how the machine closes it.

**This is the one VStim class that does not survive as a unit.** It splits in
three, along the line between what must be timed and what must be recorded.

| Half of `Interval` | Goes to | Why |
|---|---|---|
| durations, frame counts, VTL out-lines, chaining | **vstimd's armed animations** | frame-accurate, already built, already chains inside the server |
| response windows, correct channels, timeouts, reward, `m_iTrialOutcomeAfterTimeout` | **the microcontroller** | microseconds, and only it can name an outcome in real time |
| the millisecond values, the branch structure, the outcome names | **triald** | declarative data: editable, recordable, and varyable per trial by a policy |

The line inside `Interval` is already drawn. Its config half is **milliseconds** —
`m_FixTime_ms`, `m_RandInterval_ms`, the transitions, the VTL mappings,
`m_iTrialOutcomeAfterTimeout`. Its runtime half is **frames** — `m_iFrame`,
`m_nFrame`, `m_FixTime_frm`, recomputed by `RecomputeDurationInFrames()`.
Milliseconds are declarative and portable; frames are execution and belong where
the display clock is.

#### What replaces the branch table

`m_virtualTriggerNextStateMappings` — a vector of (line, edge) → next state — does
not move to a new home. It becomes **per-participant armed behaviour plus a
coupling contract**: which line each participant raises, and which line each one
arms on. vstimd pulses stimulus onset; the MCU opens its response window on that
edge; the MCU pulses trial-over; vstimd's end-interval animation arms on that.

That contract is the artefact replacing the interval table, and it has to be
written down. Line numbers agreed by convention between two firmware images and a
scene file is exactly how a rig accumulates knowledge nobody can reconstruct.

#### What triald would own

The interval values as *data*, and the trial type's binding to them. Three things
follow that a bare index cannot give:

- **the record says what actually ran**, rather than an index into a file that
  has since been edited;
- **a policy can vary an interval** — a staircase on stimulus duration is a
  policy computing `m_FixTime_ms` for one interval per trial, and today there is
  nowhere to put that;
- **sequences can be addressed by name.** — **done.** `time_sequence = 3` had
  exactly the disease the set switch rules had before #239: edit sequence 3 and
  every trial type pointing at it silently changes meaning. Sets were cured by
  naming them, and `TrialType.statemachine_graph` is the same cure: a name, carried through
  `TrialSpec` into the record and out to the executor in `TrialParameters`.
  triald validates nothing about it — the executor owns the graphs and refuses a
  name it does not have.

There is no placeholder for this in the code, deliberately. `TrialParameters`
briefly carried a response channel and a response window, filled in by the runner
from the trial type *index* — right by accident for a two-condition set and wrong
for every other one. Those fields were never read, and a wrong answer nobody
consumes is worse than no answer, so they are gone: what an executor is
configured with is the executor's business until this table exists.

When it does, a two-port lick task needs `correct_response` as a *list* of
channels — `[]` for no response, `[0]` for the left port, `[0, 1]` for either,
which is how shaping starts.

**triald rolls the random durations.** `m_RandInterval_ms` and
`m_MaxNoRandIntervals` are rolled at runtime by
`ResetFrameCounterAndComputeRandomDuration()` and never recorded, so a VStim
trial's actual timing cannot be recovered afterwards. With the machine
decomposed, two participants have to *agree* on a randomised interval anyway, so
somebody must roll it once — and triald already owns a seeded RNG recorded with
the session. Rolling it there resolves the agreement problem and makes replay
exact. Improvement, not workaround.

Executors produce outcomes; triald decides whether they count. The table names
the outcome because only an executor can decide it in real time, and acceptance
stays in triald.

#### Two costs of the decomposition

**The paradigm becomes two artefacts** — vstimd's armed animations and the MCU's
outcome table — where VStim has one interval table. "What does this paradigm do"
loses its single place to be read. Mitigated by triald owning and shipping both,
so the record holds them together and there is one place to author them, but it
is a real loss and should be named as one.

**Nobody owns "where are we in the trial".** VStim's Experiment Controller shows
the interval table and the current interval; with no central executor there is no
such view. It has to be designed in deliberately — the participant that owns the
sequence position publishing it — or it will be missed the first time a paradigm
misbehaves at 11pm.

#### Two overlaps to settle first

`ExperimentControllerConfig::m_SimulateAllowedResp` is a "perfect subject" mode,
and triald has `SimulatedBehaviourSource`. Two simulators at two layers; decide
which is authoritative before they disagree.

The error time extensions — `m_EarlyErrTime_ms`, `m_EyeErrTime_ms`,
`m_LateErrTime_ms` — are punishment timeouts keyed by outcome. triald knows
outcomes, the executor knows time. Values in triald's config, enforcement in the
executor.
---

## Deliberately not triald's job

`TrialTypeManager` reaches into all of these today because it lives inside
VStim's process. Keeping them out is what lets the daemon be Python.

| | |
|---|---|
| Rendering and frame timing | vstimd. triald never sees a frame. |
| Running the within-trial sequence | It has no single owner any more: vstimd's armed animations and the microcontroller's outcome table, coupled by edges. triald holds the *values* — see *The interval table, decomposed*. |
| Eye monitoring | triald receives *precise fixation: true/false*, not gaze samples. |
| Digital I/O and the reward valve | daqd bridges the lines, the microcontroller opens the valve. triald says only how many ms the trial type is worth. |
| The trigger bus | Raising and consuming virtual trigger lines. triald never touches one — it works in trials, not edges. |
| Stimulator hardware of any kind | Sound, odour, lasers, tactile. A new one registers itself and needs no change here; if it ever does, the boundary is wrong. |
| Stimulus definitions | A trial type names a condition; what it looks like is vstimd's scene. |
| Frame-loss detection | Detected where the frames are. triald records the flag and lets it veto. |

---

## Open questions

**Who calls `NextTrial()`?** ~~Open~~ — **triald initiates.** This is the one
place the daemon architecture deliberately departs from VStim, where
`ExpCtrl.cpp:175` has the experiment controller pull `ttm->GetNextTrialType()`.

In one process under one mutex the question is moot: there is nobody to tell. The
moment the rig is N processes that each configure themselves from the trial type,
somebody has to start the fan-out and collect the readiness, and that is a
requirement VStim never had. Three things then decide it:

- **the readiness gate needs one collector.** If the controller pulls, the
  controller collects readiness and triald degrades from the session authority to
  a lookup service;
- **stopping.** Under pull, "this session should end" has to be expressed by
  refusing the next pull. Under push triald simply does not start another trial;
- **set switching happens between trials**, and the thing that does the
  between-trials work should be the thing that starts the next one.

The old worry - that pushing makes triald the session's clock - is answered by
where the jitter lands. triald times the *trial* boundary, never stimulus onset:
onset is a trigger edge from the controller, so triald's jitter falls in the ITI
where there is slack. Nothing about this puts a frame deadline on the slow bus.

**Does the 256-trial-type ceiling stay?** It exists because of `.tdr`'s
fixed-width fields and the `set × 256 + type` encoding that analysis scripts
decode. Internally nothing needs a limit. Either the wire format keeps the
encoding, or it breaks with it and ships a translation for old data.

**Does triald write `.tdr` at all?** Probably not. A `.tdr` carries eye data,
common resources and object data that triald does not have. More likely: triald
writes JSONL, and a separate tool assembles a `.tdr` from triald's records plus
vstimd's, for as long as the old pipelines are alive.

**One daemon per rig, or one serving several?** One per rig matches vstimd and
keeps failure domains small. Cross-rig counters are a real request, but making
triald multi-session from the start would put a session ID through every RPC
above. A single-session daemon plus a separate aggregator is probably the shape.

**How does an existing VStim configuration come over?** Fifteen versions of
binary archiver hold every set a lab has built up. Cheapest path: VStim already
has `GetConfigString()`, which serialises to JSON — a one-off export from VStim,
imported by triald, avoids reimplementing the binary reader entirely.

---

## Roadmap

1. ~~Domain logic, policy API, simulator, tests~~ — **done**
2. ~~The API schema~~ — **done** for the wire and the record shape, in
   `api/schemas.py`. Outstanding: the config-file shapes, and retiring
   `state.py`'s `as_dict()` methods in favour of the models.
3. ~~HTTP and WebSocket API, plus policy upload and storage~~ — **done**
4. ~~Web interface, session view~~ — **done**
5. Session and rig config files, and the VStim importer
6. Python client, then MATLAB (HTTP/JSON), then Bonsai
7. Web interface: the CodeMirror editor, then the charts
8. The coupling contract, then the microcontroller's outcome table and firmware
9. Packaging: numpy and scipy in the tree, nfpm, systemd, the apt archive,
   `trialctl env`
10. `ReplaySession`, and the `Records` API group

Steps 5 to 8 are independent of one another. Step 5 is the one that unblocks a
real rig: until config files exist the daemon starts on the demo experiment or
on nothing.
