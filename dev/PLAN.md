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
interleaved staircases come from `questplus` or PsychoPy, via a `policy_path`
virtualenv — never from the package itself.

### Session recording — **done**

One directory per session: `manifest.json`, append-only `trials.jsonl`,
`summary.json`. Flushed per trial, so a crash costs at most the trial in flight.
Records carry the policy's own state, so an adaptive session is reconstructable.
A write failure stops the experiment by default.

### Config and persistence — **planned**

Two configs, always named:

- **rig config** — the physical setup: endpoints, results directory, serial port,
  `policy_path`. TOML at `/etc/braemons/triald.toml`. Changes when the hardware
  does.
- **session config** — one experiment: sets, ordering, accept flags, stop rules,
  policy. Changes per session.

Needs: round-trip to a human-readable file, and an importer for existing VStim
configurations.

### RPC surface — **planned**

ZMQ + protobuf, mirrored over WebSocket for the web UI, matching vstimd's shape.

| Group | Calls |
|---|---|
| Session | `ArmSession`, `StartSession`, `StopSession`, `PauseRecording`, `ResumeRecording` |
| Trial loop | `NextTrial → TrialSpec`, `ReportOutcome`, `CancelTrial` |
| State | `GetState`, `Subscribe → stream`, `GetCounters` |
| Sets | `ListSets`, `LoadSet`, `SaveSet` |
| Config | `GetConfig`, `SetConfig`, `ResetRounds`, `ResetCounters` |
| Scripting | `LoadPolicy`, `CheckPolicy`, `GetPolicyState` |
| Records | `ListSessions`, `GetSession`, `ReplaySession` |

### Web interface — **planned**

Served by the daemon, no separate deployment. Live session view: current trial
type, trial number, per-type counters, progress through the round and towards the
switch rule, recent outcomes. Plus editing the declarative config and the sets,
starting and stopping recording, loading and checking a policy, and reading the
traceback when one fails.

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
3. RPC surface (protobuf schema first, shared with the web UI)
4. Web interface
5. `SerialBehaviourSource` and reference firmware
6. Packaging: nfpm, systemd, the apt archive
7. `ReplaySession`
