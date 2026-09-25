# Trial Control Daemon — triald

> **Status:** early alpha (`v0.3.0-alpha2`) — the domain logic, the scripting
> API, the gRPC API, the web UI, the Python client and the `.deb` work and are
> tested, and `contracts/e2e-tests/` runs sessions against statemachined and
> vstimd with it. A session config is a JSON file
> ([`examples/session-config.json`](examples/session-config.json), checked by
> [`docs/reference/session-config.schema.json`](docs/reference/session-config.schema.json));
> sets and settings changed over the API are not yet written back to it.

**triald** decides what trial runs next, records what happened, and lets you write
the decision in Python. It is the part of a behavioural rig that owns trial
types, sequencing, outcome accounting, rounds and blocks, automatic set
switching, and the session record.

It is a sibling of [vstimd](https://github.com/braemons/vstimd), and the split
between them is the whole design: **vstimd keeps everything with a frame
deadline** — the render loop, Virtual Trigger Lines, the DAQ. **triald decides
and remembers**, in the gap between trials. Nothing in triald's loop is allowed
to become timing-critical, which is why it can be Python.

The logic is carved out of the `TrialTypeManager` in Andreas Kreiter's **VStim**,
which has run experiments at the Cognitive Neurophysiology Lab in Bremen for
years. The rules here are its rules; what changes is that they are scriptable,
reachable over the network, and testable without a rig.

## Why a separate daemon

In VStim this logic lives inside one Windows process behind an MFC dialog. Moving
it out buys three things:

- **Scriptable.** A trial-selection rule is a Python class, debuggable with
  `pdb`, testable with `pytest`, free to `import numpy` — or a PsychoPy
  staircase, if that is what your experiment already uses.
- **Reachable.** Counters and current state over RPC and a web UI, from any
  machine on the rig network rather than from the one keyboard in the booth.
- **Reproducible.** A seeded RNG recorded with the session, an append-only trial
  record, and replay of a recorded session through a modified policy.

## Try it without a rig

```sh
cd daemon                                 # the Python project; `make sync` from the root
uv sync --group dev
uv run triald sim --trials 200            # a demo experiment, simulated subject
uv run triald sim --trials 200 --trace    # every trial
uv run triald policy check my_policy.py   # import and smoke-run before arming
```

`triald sim` runs a whole session against a synthetic subject with no hardware
and no vstimd. It is the fastest way to find out that a policy does something
stupid on trial 300.

For the same thing with a face on it:

```sh
uv sync --group dev --extra serve
uv run triald serve                       # panels on http://127.0.0.1:8420, gRPC on 8421
```

The session view shows the counters, the round, the sets and how far the loaded
one has got towards its switch rule, and follows the state stream as the session
runs. Its debug panel drives a **simulated subject** through the real trial loop —
step a trial, step five hundred, free-run on a timer, or select a trial and report
any of the eleven outcomes by hand with the frame-loss and fixation modifiers, to
watch a trial be counted but not accepted.

The UI has no build step, no framework and no CDN: a rig box may have no route to
the internet, and a browser in a booth should not be waiting on unpkg.

## Writing a policy

Every hook is optional. Omit one and the declarative config decides.

```python
from triald import Policy, Staircase, TrialOutcome

LEVELS = [f"contrast_{i}" for i in range(6)]


class TwoDownOneUp(Policy):
    def on_session_start(self, state):
        self.stair = Staircase(n_levels=len(LEVELS), level=0, n_down=2)

    def select_trial(self, state):
        return LEVELS[self.stair.level]

    def on_outcome(self, record, state):
        if record.accepted:  # never step on a refused trial
            self.stair.update(record.report.outcome is TrialOutcome.HIT)

    def snapshot(self):
        return self.stair.snapshot()  # lands in the trial record
```

**A policy exception never ends a session.** It is logged with a full traceback,
surfaced against the trial that raised it, and the daemon falls back to the
declarative behaviour and carries on. There is an animal in the rig.

## The two levels, and no DSL

Settings stay settings; logic is real Python. There is deliberately nothing in
between.

| Declarative config | A policy |
|---|---|
| Ordering, weights, avoid-repeat | Staircases, QUEST, curricula |
| Accept flags per outcome | Adaptive stopping criteria |
| Round counts and stop rules | Anything conditional on history |
| Set switch rules | Switching on something the rule cannot express |

## Planned

Performance charts you configure rather than accept — running hit rate,
psychometric curves against a trial type's parameters, staircase traces, reaction
times. Anything a policy returns from `snapshot()` is plottable without extra
work. And a small CodeMirror policy editor for tweaks between blocks: read-only
by default, with Check-before-Load not skippable.

Clients for **MATLAB** and **Bonsai** (the Python one is built —
[`client/python/`](client/python/)). The API is gRPC now, so a MATLAB client
is no longer `webread` and JSON; how it reaches a rig is open. **Bonsai** (a NuGet package whose source
and sink operators map onto the state stream directly).

## Documentation

- [`proto/triald/v1/`](proto/triald/v1/) — **the API itself**: every type and
  every rpc, with what each one refuses and why, authored by hand.
  [`proto/braemons/v1/`](proto/braemons/v1/) beside it holds the one thing the
  family shares: the `.tdr` outcome taxonomy.
- [`docs/reference/api.md`](docs/reference/api.md) — the API for a person: what
  an rpc is for, when to use one rather than another, and what a refusal means.
- [`client/python/`](client/python/) — the Python client and `trialctl`. Two
  runtime dependencies, and not the daemon: talking to a rig should not mean
  installing one.
- [`dev/PLAN.md`](dev/PLAN.md) — the functional scope: what came from
  `TrialTypeManager`, what is new, what is deliberately out, and the open
  questions.
- [`CLAUDE.md`](CLAUDE.md) — build, test and layout notes.

## License

GNU AGPLv3-or-later. Copyright © 2026 Joscha Schmiedt, University of Bremen.
