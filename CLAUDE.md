# CLAUDE.md

## What triald is

A scriptable trial control daemon: it decides what trial runs next, records what
happened, and lets an experimenter write the decision in Python. Sibling of
[vstimd](https://github.com/braemons/vstimd).

**The split with vstimd is the design.** vstimd owns everything with a frame
deadline — the render loop, VTLs, the DAQ. triald decides and remembers, in the
gap between trials. *Nothing in triald's loop may become timing-critical* — that
is the assumption the whole language choice rests on. If something here starts
needing sub-millisecond timing, it belongs in vstimd or in the microcontroller,
not here.

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
```

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
- **Seeded RNG, recorded with the session.** VStim uses `rand() % n` — biased and
  unreproducible. Replay depends on this being an explicit `random.Random`.
- **`>=`, not `==`, for stop conditions.** VStim compares `nDone ==
  TrialsBeforeStop`, which silently never fires again if a counter jumps.
- **Sets are addressed by name**, not by a 1-based index into a fixed array. An
  index-based rule points somewhere else the moment sets are reordered.
- **The microcontroller never learns the trial type.** It gets a
  `TrialParameters` block — correct channel, windows, reward — so firmware stays
  stable while paradigms change. It is the *timing* authority; triald is the
  *decision* authority.
- **`trial_id` on every behaviour-source message.** It is what stops a late
  result being attributed to the next trial, which is how a rig quietly
  mislabels a dataset.

## Module layout (`src/triald/`)

Roughly in dependency order — nothing later is imported by anything earlier.

| Module | Owns |
|---|---|
| `outcomes.py` | The 11-code taxonomy, its modifiers, and `AcceptancePolicy` |
| `trialtypes.py` | `TrialType`, `TrialTypeSet`, `SwitchRule`, the store, chain validation |
| `counters.py` | `ResultCount` — per type and total |
| `selection.py` | `TrialBag`: the three orderings, draw-without-replacement, avoid-repeat |
| `state.py` | `TrialSpec`, `TrialRecord`, `SessionState` — everything published, all frozen |
| `policy.py` | The `Policy` base class, `safe_call`, `load_policy` |
| `adaptive.py` | Up/down staircases (no dependencies; PsychoPy is optional and external) |
| `behaviour.py` | `BehaviourSource`: the microcontroller seam, and the simulated subject |
| `session.py` | The trial loop — the state machine everything hangs off |
| `recording.py` | Append-only JSONL session records |
| `runner.py` | Drives a session against a behaviour source |
| `cli.py` | `triald sim`, `triald policy check`, `triald replay` |

Not built yet: `rpc/` (ZMQ + protobuf) and `web/` (FastAPI + WebSocket). Both are
specified in `dev/PLAN.md`.

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

**Do not add PsychoPy to the package.** It drags a GUI stack onto a headless rig
box. Point `policy_path` at a virtualenv that has it instead.
