# Trial Control Daemon — triald

> **Status:** early alpha — the domain logic and the scripting API work and are
> tested. The RPC surface, the web UI, the clients and the packaging are not
> built yet.

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
uv sync --group dev
uv run triald sim --trials 200            # a demo experiment, simulated subject
uv run triald sim --trials 200 --trace    # every trial
uv run triald policy check my_policy.py   # import and smoke-run before arming
```

`triald sim` runs a whole session against a synthetic subject with no hardware
and no vstimd. It is the fastest way to find out that a policy does something
stupid on trial 300.

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

A web UI served by the daemon: live counters, a small CodeMirror policy editor for
tweaks between blocks, and performance charts you configure rather than accept —
running hit rate, psychometric curves against a trial type's parameters, staircase
traces, reaction times. Anything a policy returns from `snapshot()` is plottable
without extra work.

Clients for **Python**, **MATLAB** (over HTTP and JSON, so no toolbox and no
MATLAB-to-Python version matching) and **Bonsai** (a NuGet package whose source
and sink operators map onto the state stream directly).

## Documentation

- [`dev/PLAN.md`](dev/PLAN.md) — the functional scope: what came from
  `TrialTypeManager`, what is new, what is deliberately out, and the open
  questions.
- [`CLAUDE.md`](CLAUDE.md) — build, test and layout notes.

## License

GNU AGPLv3. Copyright © 2026 Joscha Schmiedt, University of Bremen.
