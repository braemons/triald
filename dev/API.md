# triald — the API

What crosses the wire, in both directions. Everything here is generated from
`src/triald/api/schemas.py`; the models are the contract, and this file is the
prose that says why each shape is the shape it is. The live OpenAPI document is
at `/openapi.json`, with Swagger at `/docs`.

**One transport: HTTP for request/reply, a WebSocket for the state stream, JSON
throughout.** The web UI and all three clients use the identical API — there is
no mirroring layer, and nothing reaches into `triald.Session` by a private route.
See dev/PLAN.md, *API surface*, for why this is not protobuf and not ZeroMQ.

**One daemon, one session.** No call carries a session id. That matches
one-daemon-per-rig; cross-rig aggregation is a separate tool's job.

```sh
triald serve                                  # 127.0.0.1:8420, demo experiment
triald serve --port 8080 --results-dir ~/data --policy staircase.py
```

Binding is to localhost by default and never `0.0.0.0`. A policy is Python
running inside the daemon's process, so this API is remote code execution by
design; exposing it should be a decision, not a discovery.

---

## The shape of it

```
                    arm next trial
   ┌──────────┐  ──────────────────▶  ┌──────────────────┐
   │  triald  │                       │      vstimd      │
   │          │  ◀──────────────────  │                  │
   └──────────┘        outcome        └──────────────────┘
        │
        │  HTTP · WebSocket
        ▼
   web UI · Python · MATLAB · Bonsai
```

Six calls make a session run. Everything else is settings, inspection or debug:

| | |
|---|---|
| `POST /api/session/arm` | validate everything and start |
| `POST /api/trial/next` | select the next trial type → `TrialSpec` |
| *(the trial happens elsewhere)* | vstimd renders; the microcontroller watches |
| `POST /api/trial/outcome` | report how it ended → `TrialRecord` |
| `GET /api/state` · `WS /api/stream` | what is happening |
| `POST /api/session/stop` | end it |

---

## Coming in

Three request bodies carry everything a rig sends. The rest of the API is
settings.

### `OutcomeReport` — the primary inbound message

`POST /api/trial/outcome`. Every counter, every round, every set switch and every
line of the record is driven from this one object, so it has to carry every
modifier that participates in the accept decision — the daemon has no other way
to learn them.

| Field | Type | Meaning |
|---|---|---|
| `trial_id` | int | **Required.** Which trial this is the outcome of. `409` if it is not the trial in flight. |
| `outcome` | int or name | The `.tdr` code. `1` and `"HIT"` are both accepted; always returned as the code. |
| `manipulandum` | int or name | Which input device produced it. |
| `reaction_time_ms` | float? | Recorded, never used in the accept decision. |
| `terminating_interval` | int? | The interval the trial ended in. |
| `precise_fixation` | bool | **From the eye monitor.** False can veto acceptance on its own. |
| `frame_loss` | `{interval, frame}`? | **From vstimd.** Non-null can veto acceptance on its own. |
| `reward_ms` | int | What was *actually* delivered, which may differ from the type's setting. |
| `hit_condition` | bool | Whether the time sequence set a hit condition. |
| `simulated` | bool | The outcome came from a simulator, not an animal. |
| `note` | str? | Free text, recorded verbatim. |

`trial_id` addresses the message; it is not part of the outcome and is not
written into the record, which already carries the trial's number. It is required
rather than defaulted, and an outcome for any other trial is **refused** rather
than accepted: the report comes from another machine over a network, and one that
arrives late or twice would otherwise be attributed to the trial *after* the one
it belongs to. triald cannot tell which of the two is the truth, so it takes
neither.

The eleven outcome codes are a **wire contract**: they are in every `.tdr` the lab
has written and every analysis script that reads one, and are never renumbered.

```
-1 UNDETERMINED   2 WRONG_RESPONSE        5 EARLY   8 UNEXPECTED_START_SIGNAL
 0 NOT_STARTED    3 EARLY_HIT             6 LATE    9 WRONG_START_SIGNAL
 1 HIT            4 EARLY_WRONG_RESPONSE  7 EYE_ERROR  10 CANCELLED
```

### `SessionConfig` / `ConfigPatch` — the declarative settings

`GET /api/config`, `PATCH /api/config`. Everything the web UI can edit without
anybody writing Python. A patch carries only the fields you are changing; `null`
means "leave it alone", except on `stop_after_trials`, where null is itself a
value meaning "no limit" — clear it by sending `0`.

| Field | Meaning |
|---|---|
| `initial_set` | Name of the set to start in. |
| `ordering` | One of the five below. |
| `rounds` | Rounds in an experiment. Round = the sum of the weights. |
| `avoid_repeat` | Exclude the previous type from the draw, while anything else is left. |
| `acceptance` | The eleven accept flags plus the two vetoes. |
| `stop_when_rounds_done` | Stop after the last trial of the last round. |
| `stop_after_trials` + `stop_criterion` | Stop after N trials of a chosen kind. |
| `extend_trial_type_number` | Number trial types `set_number * 256 + index`. |
| `seed` | RNG seed. Generated and recorded when null, so every session replays. |

### `TrialTypeSet` — a set and its switch rule

`PUT /api/sets/{name}`. A set is a named list of trial types plus **its own**
switch rule, because the rule travels with the set: through the store, through
"save as", and onto another rig.

```jsonc
{
  "name": "fixation",
  "trial_types": [
    { "name": "fix_only", "trials_per_round": 4, "statemachine_graph": "fixation",
      "reward_ms": 120, "params": {} }
  ],
  "switch_rule": { "enabled": true, "criterion": "hits",
                   "count": 20, "target": "one_line" }
}
```

`params` is paradigm data — a contrast, a coherence, a target position. **triald
never interprets it**, and it is recorded verbatim with every trial. It exists
because adaptive procedures work in a continuous *intensity* while trial types
are discrete *conditions*, and the intensity has to live somewhere.

`target` is a set **name**, not a 1-based index into a fixed array. An
index-based rule points somewhere else the moment sets are reordered.

`statemachine_graph` is the state graph the executor runs for this condition, and it is a
**name** for the same reason — VStim's `iTimeSequence` was an index into a fixed
store, so editing sequence 3 silently changed the meaning of every trial type
pointing at it. Empty means "leave whatever the executor has loaded". triald
holds no graphs and does not check the name against a store: the executor owns
them and refuses one it does not have. It is the only field of the trial type
that crosses to an executor, and it is still not the trial type — several
conditions routinely share one graph.

The name is spelled out because a bare `graph` says nothing about whose it is —
triald holds none of its own. On statemachined's `POST /api/trial/configure` the
same value is the field `graph`, where the namespace supplies the rest; a client
maps the one field.

---

## Coming out

### `SessionState` — the whole snapshot

The payload of `GET /api/state`, of every WebSocket frame, and of the reply to
every mutating call, so there is one description of what is happening rather than
several that drift.

| Group | Fields |
|---|---|
| status | `running`, `armed`, `recording`, `paused`, `stop_reason` |
| the trial | `current` (in flight, or null), `last`, `recent[]` |
| the set | `set_name`, `set_progress`, `rounds_completed`, `rounds_configured`, `trials_per_round`, `trials_remaining` |
| the numbers | `totals`, `counters[]` |
| provenance | `seed`, `config`, `policy`, `policy_errors[]`, `trials_started` |

`counters[]` is one row per trial type of the active set, with the trial type's
definition already joined onto its tallies — the columns VStim's Trial Type
Manager shows, so a client does not have to match the two up itself:

```
index · trial_type_number · name · trials_per_round · statemachine_graph · reward_ms
remaining · p_next · total · accepted · frame_loss · by_outcome{} · hits · hit_rate
```

`p_next` is the chance of that type being drawn next — VStim's
`GetProbabilityOfNextTrialType`. It is **advisory**: it describes the declarative
ordering, and a policy whose `select_trial` returns a type decides for itself.

`trial_type_number` is what the *record* will carry, extended by the set number
when that is on, so the column can be used to look a trial up afterwards.

### `TrialSpec` — the selection, published the moment it is made

Everything about a trial is latched here and stable for the whole trial —
including `recording`, so a trial that began recording finishes recording even if
somebody pauses in the middle of it.

```
trial_number · trial_type_index · trial_type_number · trial_type_name
set_name · statemachine_graph · reward_ms · recording · paused · started_at
```

### `TrialRecord` — one finished trial

The reply to `ReportOutcome`, and **byte-for-byte the line written to
`trials.jsonl`**. A test asserts it. Anything that can read a session directory
can read the stream, and a divergence is a failing test rather than a discovery
six months later.

```jsonc
{
  "trial":   { /* TrialSpec */ },
  "outcome": { "code": 1, "name": "HIT", /* …every modifier… */ },
  "accepted": false,
  "refusal_reason": "frame loss, and frame-loss trials are not accepted",
  "ended_at": "2026-09-01T13:39:59.718969+00:00",
  "policy_state": { "level": 3 }
}
```

**`accepted` is the field to read first.** Every reported outcome is *counted*.
Only an *accepted* one consumes from the bag, advances the round, and moves a set
towards its switch rule. Three independent things decide it and **any of them can
veto**: the outcome's own accept flag, frame loss, and imprecise fixation. A hit
that lost a frame is still a hit — it counts, it moves the set's hit criterion,
and it does not consume from the bag.

`refusal_reason` says *which* of the three turned the trial away, because an
experimenter watching a session stall at 40 accepted trials needs to know.

### Errors

A refusal is a 4xx and an `ErrorModel`; `detail` is written to be read by a
person, because it usually is.

```jsonc
{ "error": "session", "detail": "trial 12 is still in flight; report its outcome before selecting another" }
```

| Status | When |
|---|---|
| 400 | The request was understood and is wrong — a bad set, an unusable switch chain, an arm-time setting changed mid-session. |
| 404 | No such set. |
| 409 | Right request, wrong moment — not armed, already running, a trial in flight. |
| 422 | The body did not validate. Unknown fields are refused by name, never ignored. |
| 500 | A write failed. A recording that silently misses the disk is worse than an aborted one. |

---

## The calls

### Session — `/api/session`

| | |
|---|---|
| `POST /arm` | Validate everything and start. **Builds a new session**: counters, rounds, history, the RNG and the simulated subject all start again. Refuses rather than failing later — a missing set, an empty set, an unusable switch chain three hops away. |
| `POST /stop` | End the session. Closes the record. |
| `POST /recording/start` | Record from the next trial. Opens a session directory when `--results-dir` is set; without one the flags still move and nothing reaches the disk. |
| `POST /recording/pause` | Keep running, stop recording. A pausing trial runs, but scores nothing and is never recorded. |
| `POST /recording/resume` | |
| `POST /recording/stop` | Close the record. The session keeps running. |

### Trial loop — `/api/trial`

| | |
|---|---|
| `POST /next` | → `TrialSpec`. Refused while a trial is in flight, which is what stops one trial's result being attributed to another. |
| `POST /outcome` | `OutcomeReport` → `TrialRecord`. |
| `POST /cancel` | `{reason}` → `TrialRecord` with outcome `CANCELLED`. Recorded rather than dropped, so a gap in the numbering never has to be explained. |

**Pull, not push.** The caller asks for a trial when it is ready, which keeps
triald reactive and stops it becoming the session's clock. See dev/PLAN.md,
*Open questions*.

### State — `/api/state`, `/api/stream`

`GET /api/state` returns the snapshot. `WS /api/stream` pushes a `StreamMessage`
on connect and on every change:

```jsonc
{ "kind": "state", "sequence": 42, "at": "…", "state": { /* SessionState */ } }
```

Frames are **coalesced, not queued**, for a subscriber that falls behind: this is
a state stream, so the newest snapshot is the only one worth having, and a slow
browser tab must not be able to hold up a session. A gap in `sequence` means
frames were dropped, which is not an error.

### Sets — `/api/sets`

| | |
|---|---|
| `GET /` | Every set, each with its rule, weights, `set_number` and whether it is active — plus `chain_problem`, which is the check `arm` refuses on, run continuously so the UI shows a broken chain before anybody starts. |
| `PUT /{name}` | Add or replace. Replacing the active set rebuilds the bag and restarts the round; the counters are banked by name and survive it. Renaming is a delete and a put. |
| `DELETE /{name}` | Refused for the set that is loaded. |
| `POST /{name}/load` | Make it active. Its block starts from nothing — exactly what an automatic switch does, so loading by hand and switching by rule cannot disagree about what loading means. |

**A sequence is what a chain of rules makes**; there is no separate type for one.
Two sets pointing at each other alternate, three walk in order, and a set with no
rule ends the walk.

### Config — `/api/config`

`GET`, `PATCH`, plus `POST /reset-rounds` and `POST /reset-counters`. A patch
answers with what the change actually cost:

```jsonc
{ "changed": ["ordering"], "bag_rebuilt": true, "config": { /* … */ } }
```

The settings split three ways, and the split is the whole content of the call:

| | Fields | Cost |
|---|---|---|
| **live** | the accept flags, the stop rules | Read fresh every trial; takes effect on the next one. |
| **bag-shaped** | `ordering`, `rounds`, `avoid_repeat` | Rebuilds the bag, so the round starts again. Counters untouched. |
| **arm-time** | `initial_set`, `extend_trial_type_number`, `seed` | **Refused while running.** Each decides something that has already happened, so changing one would leave a record whose first half means something different from its second. |

`reset-counters` clears **every bank, not only the loaded set's** — a half-cleared
session is worse than either state. The bag and the round are left alone;
`reset-rounds` is the other half.

### Policy — `/api/policy`

| | |
|---|---|
| `GET /` | Name, class, `sha256`, origin, and the last `snapshot()`. `?source=true` for the text. |
| `POST /check` | `{name, source}` → diagnostics with **line numbers**, so an editor can mark the offending line rather than printing a traceback underneath it. Imports it and smoke-runs it over a throwaway copy of the experiment, so a check never touches counters somebody is watching. |
| `PUT /` | Store and load. **Checked first, always** — a syntax error must never reach a session. Refused while a session runs; arming is the swap boundary. |
| `DELETE /` | Back to the declarative behaviour. |

**Source text, never a path.** The rig is not your laptop, a path means nothing
to a browser on another machine, and "which version of the staircase ran on
Tuesday" has to be answerable from the session directory alone — which a filename
cannot answer, because the file changes. Same argument as recording the seed.

A policy exception never ends a session: every hook is wrapped, the traceback is
logged and recorded against the trial, and the declarative behaviour stands.
Failures appear in `state.policy_errors`.

### Events — `/api/events`

`POST /note` appends an experimenter's note to the event stream. Refused when
nothing is recording, rather than silently dropped: a note that goes nowhere is
worse than one that could not be written, because the person who typed it
believes it was kept.

Events are the custom-message channel. **Corrections are appended, never applied
in place**: realising at trial 50 that the subject ID was typed wrong writes a new
event, so the record shows both what was believed and when it changed.

### Debug — `/api/debug`

Drives a **simulated subject** so the whole daemon can be exercised with no rig
attached. It is the same loop: a step goes through `runner.run_trial`, the same
four calls a rig makes, with the microcontroller replaced.

| | |
|---|---|
| `GET`/`PUT /sim` | The subject's outcome probabilities, including per trial type. The RNG keeps its place, so a session stays reproducible up to the point somebody moved a slider. |
| `POST /step` | `{trials}` → runs that many whole trials, or fewer if the session stops. Refused with a trial in flight. |
| `GET`/`PUT /free-run` | `{running, interval_ms}` — step on a timer until stopped or the session ends. |

---

## The five orderings

A round is a bag: each trial type contributes as many tokens as its
`trials_per_round` weight, and trials are drawn **without replacement** until the
bag is empty. Only *accepted* trials consume from it, so a refused trial is made
up later in the round.

| `ordering` | The bag holds | The draw |
|---|---|---|
| `random_in_round` | one round | weighted over what is left |
| `random_in_experiment` | every round at once | weighted over what is left |
| `ascending` | one round | the lowest index with anything left |
| `descending` | one round | the highest index with anything left |
| `random_with_replacement` | one round's worth of quota | weighted over the **configured** weights |

`random_in_round` keeps every round exactly balanced, which is what you want when
a block has to be. `random_in_experiment` balances the whole experiment instead,
so a run of one condition is possible and expected.

`ascending` and `descending` are mirrors — a ladder of difficulties runs easy to
hard under one and hard to easy under the other, without anybody renumbering the
trial types. Both ignore `avoid_repeat`: a deterministic ordering has nothing to
avoid a repeat with, and honouring the flag would mean not running the weights.

`random_with_replacement` puts the token back, so each trial is an independent
draw and a round is balanced only in expectation. Runs of one condition are
longer than people expect, which is the point when a subject can learn that a
condition is used up. The round is still `trials_per_round` accepted trials long —
it has to be, or the rounds and the stop rules would mean nothing — so a type's
`remaining` reads as the quota still owed and can sit at zero while the round runs
on. `trials_remaining` on the state is the authority for the round.

The RNG is a seeded `random.Random` recorded with the session. VStim's
`rand() % n` is biased towards low indices and unseedable in practice, so a VStim
session cannot be reproduced; this is what makes replay possible.

---

## Automatic set switching

Each set carries its own rule: `{enabled, criterion, count, target}`. When the
loaded set has reached `count` trials of `criterion` **since it was loaded**, the
target is loaded and its block starts from nothing. Session totals keep climbing
across the switch.

`criterion` is a `TrialCountCriterion` — `accepted_trials`, `hits` or
`all_trials` — and is **the same enum the stop rule uses**. The question is the
same one in both places, and two enums would drift.

Four things are refused rather than followed, because a switch happens between
trials with nobody watching:

- **no target**, or a target that is this same set — it would restart the block for ever;
- a target **not in the store**;
- a target with **no trials in it** — `trials_per_round` would be zero and the round arithmetic divides by it.

The **whole chain** is validated when the session is armed, so a set three hops
away that nobody filled in is caught before a session is left alone with it
overnight. An `A → B → A` loop is fine and ends the walk. `GET /api/sets` runs the
same check continuously and reports it as `chain_problem`.

**Stopping wins over switching.** There is nothing to switch to once the
experiment is ending.

Faithful to VStim: **only `HIT` counts towards the hit criterion**, not
`EARLY_HIT`. Worth revisiting with the lab, since it changes how long a training
block runs.

### Counters are banked per set

With `extend_trial_type_number` on, the sets are separate experiments whose trial
type 3 have nothing to do with each other, so each keeps its own counters.
Without it, trial type 3 means the same thing in every set and they share one
bank.

Banking rather than clearing on load is what stops a session that alternates
between two sets losing a set's counts every time it comes back to it.

---

## Not in this build

Specified in dev/PLAN.md, and deliberately not here yet. They are named so the
absence is a decision rather than an oversight.

| Group | Calls |
|---|---|
| Environment | `ListPackages`, `InstallPackages`, `GetEnvironment` |
| Records | `ListSessions`, `GetSession`, `ReplaySession` |
| Sets | `SaveSet` to a file, and the VStim configuration importer |

The web UI's policy editor is likewise still a plan: `/api/policy` is complete,
but the page shows the running policy rather than editing it. When it arrives it
is **CodeMirror, read-only by default, and Check-before-Load is not skippable** —
a tweak between blocks, not a place to author policies, or they stop being
version-controlled, which is one of the things triald exists to fix.
