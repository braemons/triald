# triald-client — the Python client for triald

Talks to a [triald](https://github.com/braemons/triald) daemon over gRPC and
hands back types.

```python
from triald_client import TrialdClient

with TrialdClient("rig.local") as rig:
    rig.arm()
    while True:
        trial = rig.next_trial()
        outcome = run_it(trial)  # your rig does this part
        record = rig.report_outcome(trial.trial_number, outcome)
        if not record.accepted:
            print(record.refusal_reason)
```

**No protobuf type crosses this package's edge.** The generated code is private,
in `triald_client._proto`; `triald_client.api_types` is the public vocabulary.
You should not have to learn a generated API to read a reaction time.

The interface those types come from is `proto/triald/v1/` in the daemon's
repository, authored by hand — types *and* rpcs. `docs/reference/api.md` there
says what each rpc is for.

## Install

```console
$ pip install git+https://github.com/braemons/triald.git#subdirectory=client/python
```

Two runtime dependencies, `grpcio` and `protobuf`. Not the daemon: talking to a
rig should not mean installing one.

## `trialctl`

The same client as a command line. `--rig` takes `host` or `host:port`.

```console
$ trialctl --rig rig.local state
$ trialctl --rig rig.local watch
$ trialctl --rig rig.local sets
$ trialctl --rig rig.local policy check my_staircase.py
```

## Licence

AGPL-3.0-or-later, the same as the daemon.
