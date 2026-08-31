# triald — functional scope

What has to survive the move out of VStim's `TrialTypeManager`, what it should
become on the way, and what is deliberately left behind.

Sources: `VStimLib/StimulusDefinition/TrialTypeManager.{h,cpp}`,
`TrialTypeManagerInterface.h`, `VStimLib/TDR.h`.

Status key: **done** — implemented and tested. **planned** — specified here, not
built. **open** — needs a decision before it can be built.

---

## Where triald sits

```
                    arm next trial
   ┌──────────┐  ──────────────────▶  ┌──────────────────┐
   │  triald  │                       │      vstimd      │  budget: one frame
   │          │  ◀──────────────────  │  scene, VTLs     │
   │ types    │        outcome        └──────────────────┘
   │ policy   │
   │ counters │  ──────────────────▶  ┌──────────────────┐
   │ records  │   trial parameters    │  microcontroller │  budget: microseconds
   │          │  ◀──────────────────  │  levers, valve   │
   └──────────┘        result         └──────────────────┘
   budget: the ITI
        │
        │  RPC · HTTP · live state
        ▼
   operators: web UI, Python client, analysis
```

The split is the reason triald can be Python. vstimd keeps everything with a
frame deadline; the microcontroller keeps everything needing microsecond
timestamps; triald decides and remembers, in the gap between trials.

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

Three orderings (`random_in_round`, `random_in_experiment`, `ascending`),
draw-without-replacement from a per-type remaining count, avoid-repeat, refill at
the end of a round or experiment.

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

**New:** stop conditions compare `>=` rather than VStim's `==`, which fires
exactly once and silently never fires again if a counter jumps.

### Automatic set switching — **done** (#239)

A rule per set (enabled, criterion, count, target). Two criteria: accepted trials
or hits in the current set. Progress resets on a switch, on a reset, and whenever
a set is loaded. Unusable targets are refused — a missing set, the set already
running, or a set with no trials in it, which would otherwise divide by zero. The
whole chain is validated at arm time, so a set three hops away that nobody filled
in is caught before a session is left alone with it overnight.

Faithful to VStim: **only `HIT` counts towards the hit criterion**, not
`EARLY_HIT` — VStim increments `m_HitsInCurrentSet` in `OnHit()` alone. Worth
revisiting with the lab, since it changes how long a training block runs.

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
which is all `triald sim` needs. Over RPC that is the wrong shape: the rig is not
your laptop.

**The daemon receives the source text and owns it from then on.**

```
1. write     my_staircase.py in your editor, under git
2. check     trialctl policy check my_staircase.py   uploads, smoke-runs, discards
3. load      trialctl policy load  my_staircase.py   uploads, stores, arms
4. daemon    writes /var/lib/triald/policies/<sha256>.py, imports it,
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

One directory per session: `manifest.json`, append-only `trials.jsonl`,
`summary.json`. Flushed per trial, so a crash costs at most the trial in flight.
Records carry the policy's own state, so an adaptive session is reconstructable.
A write failure stops the experiment by default.

### Config and persistence — **planned**

Two configs, always named:

- **rig config** — the physical setup: endpoints, results directory, serial port,
  `policy_dir`, `extra_packages`. TOML at `/etc/braemons/triald.toml`. Changes
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

### RPC surface — **planned**

ZMQ + protobuf, mirrored over WebSocket for the web UI, matching vstimd's shape.

| Group | Calls |
|---|---|
| Session | `ArmSession`, `StartSession`, `StopSession`, `PauseRecording`, `ResumeRecording` |
| Trial loop | `NextTrial → TrialSpec`, `ReportOutcome`, `CancelTrial` |
| State | `GetState`, `Subscribe → stream`, `GetCounters` |
| Sets | `ListSets`, `LoadSet`, `SaveSet` |
| Config | `GetConfig`, `SetConfig`, `ResetRounds`, `ResetCounters` |
| Scripting | `LoadPolicy(name, source) → sha256`, `CheckPolicy(source) → diagnostics`, `GetPolicy → name, source, sha256`, `GetPolicyState` |
| Environment | `ListPackages`, `InstallPackages`, `GetEnvironment` |
| Records | `ListSessions`, `GetSession`, `ReplaySession` |

`LoadPolicy` and `CheckPolicy` take **source text**, not a path — see *How a
policy reaches the daemon*. `CheckPolicy` returns diagnostics with line numbers
so the web editor can mark the offending line rather than printing a traceback
underneath it.

**The wire protocol is the contract, not the Python API.** Three clients are
planned, so the protobuf schema is written first and every client is generated or
hand-written against it — never against `triald.Session`.

### Web interface — **planned**

Served by the daemon, no separate deployment, speaking the same protobuf over
WebSocket rather than a second bespoke API.

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

Three, against the protobuf schema rather than against each other.

**Python** (`client/python`) — the reference client, mirroring vstimd's. LGPLv3
rather than the daemon's AGPLv3, so importing it does not place an experiment's
own code under copyleft — the same split vstimd uses, and for the same reason.

**MATLAB** (`client/matlab`) — over **HTTP and JSON**, not protobuf. `webread`
and `webwrite` are built in, need no toolbox, and avoid the MATLAB-to-Python
version matching that makes the `py.` bridge painful in practice. The web API
exists anyway, so this is nearly free. The `py.` bridge stays documented as an
option for anyone wanting the full typed client.

**Bonsai** (`client/bonsai`) — a `Bonsai.Triald` NuGet package exposing source
and sink operators. Bonsai is reactive, so the mapping is unusually clean: the
`Subscribe` state stream *is* an observable sequence, `NextTrial` is a source, and
`ReportOutcome` is a sink. Transport over ZeroMQ via NetMQ, or WebSocket, matching
whatever `Bonsai.ZeroMQ` already does well.

Each client ships the same small example — arm a session, run trials, report
outcomes — and CI runs it against the daemon, so the three cannot drift apart
silently.

### Microcontroller link — **planned**

`SerialBehaviourSource` over USB CDC, newline-delimited JSON at 921600 with a CRC
and a sequence number. Teensy 4.1 or RP2350 preferred over an 8-bit Arduino;
avoid ESP32 WiFi in the trial loop.

```
ITI      triald ──ARM(trial_id, params)──▶ MCU
         triald ◀──ARMED(trial_id)─────── MCU     no trial starts without this
trial    [hardware trigger edge — the MCU and vstimd see the same line]
end      triald ◀──RESULT(trial_id, …)─── MCU
```

Three properties carry the correctness: `trial_id` on every message, so a late
result cannot be attributed to the next trial; the `ARMED` ack, so no trial runs
that the MCU was not confirmed configured for; and a **hardware** trigger edge,
so reaction times are relative to stimulus onset and need no clock sync. The MCU
fails safe — valve closed on watchdog timeout, reset, or link loss.

---

## Deliberately not triald's job

`TrialTypeManager` reaches into all of these today because it lives inside
VStim's process. Keeping them out is what lets the daemon be Python.

| | |
|---|---|
| Rendering and frame timing | vstimd. triald never sees a frame. |
| The interval state machine | VStim's `ExpCtrl`/`Interval`/`TimeSqz`. If it migrates, it goes to Rust. |
| Eye monitoring | triald receives *precise fixation: true/false*, not gaze samples. |
| Digital I/O and the reward valve | triald says how many ms the type is worth; the MCU opens the valve. |
| Stimulus definitions | A trial type names a condition; what it looks like is vstimd's scene. |
| Frame-loss detection | Detected where the frames are. triald records the flag and lets it veto. |

---

## Open questions

**Who calls `NextTrial()`?** VStim's render thread pulls when it is ready, which
keeps triald purely reactive and is the simplest thing that works. triald pushing
an armed trial ahead of time removes a round trip from the ITI but makes triald
the session's clock. Pull is the safer default; revisit only if the ITI is tight.

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
2. Session and rig config files, and the VStim importer
3. **The protobuf schema.** First, and on its own: the RPC surface, the web UI
   and all three clients are generated or written against it, so it is the one
   thing that must not be discovered incrementally.
4. RPC surface over ZMQ, plus policy upload and storage
5. Web interface — session view, then the CodeMirror editor, then the charts
6. Python client, then MATLAB (HTTP/JSON), then Bonsai
7. `SerialBehaviourSource` and reference firmware
8. Packaging: numpy and scipy in the tree, nfpm, systemd, the apt archive,
   `trialctl env`
9. `ReplaySession`

The ordering has one real constraint: step 3 precedes everything downstream of
it. Steps 5 and 6 can run in parallel once it exists, and step 7 is independent
of both.
