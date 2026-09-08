# CLAUDE.md

## What triald is

A scriptable trial control daemon: it decides what trial runs next, records what
happened, and lets an experimenter write the decision in Python. Sibling of
[vstimd](https://github.com/braemons/vstimd).

**The split with vstimd is the design.** The rig is an hourglass with the virtual
trigger lines at its waist: below them the things that *do* something on a
trigger (render, sound, valves, TTL bridging), above it the thing that decides
what a trial *is*. There is no central state machine between them: vstimd's armed
animations chain inside the server, the microcontroller names the outcome, and
they agree through trigger edges. triald sits on the slow bus and decides and
remembers in the gap between trials.

*Nothing in triald's loop may become timing-critical* — that is the assumption
the whole language choice rests on. If something here starts needing
sub-millisecond timing, it belongs below the waist: in an armed animation, in a
stimulator, or in the microcontroller. Never here.

The logic is ported from VStim's `TrialTypeManager` (1,961 lines). See
`dev/PLAN.md` for what came over, what is new, and what is deliberately out.

## Build & test

```sh
uv sync --group dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check

uv run triald sim --trials 200            # whole session, simulated subject
uv run triald sim --trials 200 --trace    # every trial
uv run triald policy check my_policy.py   # import + smoke run

uv sync --group dev --extra serve         # the daemon needs the serve extra
uv run triald serve                       # API + web UI on 127.0.0.1:8420
```

`triald serve` puts the same simulator behind a web UI whose debug panel steps
it, free-runs it, or drives one trial by hand. Everything it does goes through
the API in `dev/API.md`; nothing reaches into `triald.Session` by a private
route.

`triald sim` is the fastest feedback loop in the repo — a session of 500 trials
runs in well under a second, with no hardware and no vstimd. Use it before
reaching for anything else.

## Key decisions

- **Counted is not accepted.** Every reported outcome is *counted*. Only an
  *accepted* one consumes from the bag, advances the round, and moves a set
  towards its switch rule. Three independent things decide acceptance: the
  outcome's own flag, frame loss, and precise fixation — any of them can veto.
  This distinction is the single easiest thing to break in this codebase.
- **A policy exception never ends a session.** Every hook goes through
  `policy.safe_call`, which catches everything, logs a traceback, records it
  against the trial, and falls back to the declarative behaviour. There is an
  animal in the rig; a stopped experiment is worse than a fallback trial.
- **Two levels, no DSL.** Settings are declarative data the web UI can edit;
  logic is real Python. Nothing in between. Every DSL grows until it is a bad
  programming language with no debugger.
- **`.tdr` outcome codes are a wire contract.** `TrialOutcome`'s numeric values
  are in every `.tdr` file the lab has written and every analysis script that
  reads one. Never renumber them.
- **Five orderings, and only one puts the token back.** Four draw *without*
  replacement from a per-type remaining count, so a round is balanced by
  construction; `random_with_replacement` draws on the configured weights and is
  balanced only in expectation. Its round is still `trials_per_round` accepted
  trials long, or rounds and the stop rules would mean nothing — so per-type
  `remaining` becomes the quota still owed, and `TrialBag.total_remaining` is
  the authority for the round. `ascending`/`descending` ignore `avoid_repeat`: a
  deterministic ordering has nothing to avoid a repeat with.
- **Seeded RNG, recorded with the session.** VStim uses `rand() % n` — biased and
  unreproducible. Replay depends on this being an explicit `random.Random`.
- **`>=`, not `==`, for stop conditions.** VStim compares `nDone ==
  TrialsBeforeStop`, which silently never fires again if a counter jumps.
- **Sets are addressed by name**, not by a 1-based index into a fixed array. An
  index-based rule points somewhere else the moment sets are reordered.
- **The state graph is named, not indexed.** `TrialType.graph` is the one field
  of a condition that crosses to an executor, and it carries a name because an
  index points at a different machine the moment the executor's store is
  edited — the disease sets were cured of. It also means the record says which
  graph ran rather than a number into a file since changed. triald holds no
  graphs and validates nothing; the executor refuses a name it does not have.
- **A sequence is a chain of per-set rules**, not a separate type. Two sets
  pointing at each other alternate; three walk in order; a set with no rule ends
  the walk.
- **One `TrialCountCriterion`** for both the switch rule and the stop rule —
  accepted trials, hits, or all completed trials. The question is the same one in
  both places, and two enums would drift.
- **Stopping wins over switching.** There is nothing to switch to once the
  experiment is ending.
- **Counters are banked per set** when trial type numbers are extended, shared
  when they are not. Banking rather than clearing on load is what stops a session
  that alternates between two sets losing a set's counts each time it returns.
- **An executor never learns the trial type.** It is configured from it — correct
  channel, windows, reward — so firmware stays stable while paradigms change.
  Whoever executes a trial is the *timing* authority; triald is the *decision*
  authority, and decides only whether the outcome was accepted.
- **triald holds no hardware link, and there is no central state machine.**
  vstimd's armed animations chain inside the server; the microcontroller names the
  outcome; they agree through trigger edges. triald configures both from the trial
  type and hears the result. `BehaviourSource` is what keeps `triald sim` and the
  debug stepper on the real loop, not a serial abstraction. See dev/PLAN.md, *The
  shape of the rig*.
- **`trial_id` on every behaviour-source message.** It is what stops a late
  result being attributed to the next trial, which is how a rig quietly
  mislabels a dataset.
- **Records are evidence; the manifest is a header.** Trials and events are
  append-only and never rewritten — a correction is a new event, so the record
  shows both what was believed and when it changed. Custom payloads are checked
  strictly (no `default=str`): stringifying a `set` into `"{1, 2, 3}"` is silent
  corruption of something nobody re-checks for years.
- **The wire schema is the contract, not the Python API.** `api/schemas.py` is
  what the UI and the clients are written against. A `TrialRecordModel`
  serialises byte-for-byte to the `trials.jsonl` line, and a test asserts it, so
  the record format and the API cannot drift. That is why the timestamp fields
  carry a serialiser: pydantic spells UTC `Z` and `datetime.isoformat()` spells
  it `+00:00`, and the record has years of files behind it.
- **The web UI has no build step, no framework and no CDN.** A rig box may have
  no route to the internet. Three files in `web/`, served by the daemon.
- **The debug controls are not a second code path.** `/api/debug/step` goes
  through `runner.run_trial`, the same four calls a rig makes, with
  `SimulatedBehaviourSource` in place of the microcontroller. A simulator that
  had its own loop would stop testing the real one.
- **Custom metadata is never interpreted.** `SessionMetadata.extra`,
  `Device.info`, `SessionEvent.data` and `TrialType.params` are stored and
  returned verbatim. triald has no business knowing what an electrode depth is.

## Module layout (`src/triald/`)

Roughly in dependency order — nothing later is imported by anything earlier.

| Module | Owns |
|---|---|
| `outcomes.py` | The 11-code taxonomy, its modifiers, and `AcceptancePolicy` |
| `trialtypes.py` | `TrialType`, `TrialTypeSet`, `SwitchRule`, the store, chain validation |
| `counters.py` | `ResultCount` — per type and total |
| `selection.py` | `TrialBag`: the five orderings, draw-without-replacement, avoid-repeat, `P(next)` |
| `state.py` | `TrialSpec`, `TrialRecord`, `SessionState` — everything published, all frozen |
| `policy.py` | The `Policy` base class, `safe_call`, `load_policy` |
| `adaptive.py` | Up/down staircases (no dependencies; PsychoPy is optional and external) |
| `behaviour.py` | `BehaviourSource`: the simulator seam, and the synthetic subject |
| `session.py` | The trial loop — the state machine everything hangs off |
| `metadata.py` | `SessionMetadata`, `Subject`, `Device`, `SessionEvent` — NWB-aligned names |
| `recording.py` | The session directory: manifest, trials, events, summary |
| `runner.py` | Drives a session against a behaviour source |
| `cli.py` | `triald sim`, `triald policy check`, `triald replay`, `triald serve` |
| `api/schemas.py` | The wire contract: Pydantic models for everything crossing the API |
| `api/service.py` | One rig's session — the rules about *when* something may be done |
| `api/app.py` | FastAPI routes, deliberately thin, plus the static UI mount |
| `web/` | The session view: `index.html`, `app.js`, `style.css`. No build step |

`api/` and `web/` need the `serve` extra; everything above them imports nothing
at all, which is why they are a subpackage rather than mixed in. The API is
specified in `dev/API.md`.

Not built yet: `client/{python,matlab,bonsai}`, the `Environment` and `Records`
API groups, the CodeMirror policy editor and the configurable uPlot performance
charts. All specified in `dev/PLAN.md`.

**No protobuf and no ZeroMQ**, unlike vstimd. Its wire efficiency buys nothing
against ~1 KB once per trial, and MATLAB's protobuf support is poor enough that
one of the three clients was going over HTTP/JSON regardless — leaving a `protoc`
step in every client build and a protocol nobody can `curl`. Two daemons speaking
different protocols is a knowing trade, not an oversight.

**The schema comes before the clients.** `api/schemas.py` covers the wire and the
record shape, with OpenAPI generated from it. The clients and the web UI are
written against that, never against `triald.Session`. Still outstanding: the
config-file shapes, and retiring `state.py`'s hand-written `as_dict()` methods in
favour of the models — a real refactor of working, tested code, and the drift
test is what holds the two together until it happens.

## Testing

Test the wiring, not just the class. `tests/test_adaptive.py` ends with a policy
driven through `Session` and `run_session` against the simulated subject — that
test catches integration breaks the unit tests miss. `SimulatedBehaviourSource`
and the `clock` argument to `Session` are the injection seams.

## Packaging

`.deb` and `.rpm` from one `nfpm` config, with a vendored CPython at
`/opt/braemons/triald` so the artifact does not care what Python the distribution
ships. The systemd/sysusers/logrotate layout and the tag-derived versioning are
lifted from vstimd. Config at `/etc/braemons/triald.toml`, state in
`/var/lib/triald`.

numpy and scipy *are* in the package — without numpy, "scriptable in Python" is
a hollow promise. **PsychoPy is not**, and must not be: it drags pyglet, wx and a
GUI stack onto a headless rig box. Anything beyond numpy/scipy is installed into
the daemon's own vendored interpreter via `trialctl env install`, and listed in
the rig config's `extra_packages` so a rebuilt rig is reproducible. Never a
separate virtualenv on `sys.path` — a venv built against a different Python fails
with an ABI error nobody enjoys reading.
