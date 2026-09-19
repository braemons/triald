# SPDX-License-Identifier: AGPL-3.0-or-later
"""triald_client — Python client for the trial control daemon.

Speaks gRPC to a daemon that decides what trial runs next, and hands back
types::

    from triald_client import TrialdClient, OutcomeReport, TrialOutcome

    with TrialdClient("rig.local") as rig:
        rig.arm()
        trial = rig.next_trial()
        record = rig.report_outcome(
            trial.trial_number,
            OutcomeReport(outcome=TrialOutcome.HIT, reaction_time_ms=212.0),
        )
        print(record.accepted, record.refusal_reason)

**No protobuf type is exported from this package, and none is accepted.** The
generated code is private, in `triald_client._proto`; `triald_client.api_types`
is the public vocabulary and `_wire_conversions` is the seam between them. A
caller writing an experiment should never have to learn a generated API to read
a reaction time — and this package can keep a name the day the interface adds a
field.

**Why `triald_client` and not `triald`.** vstimd's and mousewheeld's clients
take their daemon's own name, because those daemons are Rust and nothing else
claims it. triald is Python: `triald` is the daemon's package, and a client
distribution that installed a second top-level `triald` would overwrite it on
any machine that had both — an analysis box, or a rig where somebody imports
`triald.policy` to write a policy and this to talk to the rig.

The interface these types come from is `proto/triald/v1/` in the daemon's
repository, authored by hand — types *and* rpcs. `docs/reference/api.md` there
says what each rpc is for.
"""

from .api_types import (
    Acceptance,
    ConfigPatch,
    ConfigUpdateResult,
    CounterRow,
    FrameLoss,
    FreeRunStatus,
    Manipulandum,
    Ordering,
    Outcome,
    OutcomeReport,
    PolicyCheckResult,
    PolicyDiagnostic,
    PolicyError,
    PolicyInfo,
    PolicyOrigin,
    ResultCount,
    SessionConfig,
    SessionState,
    SetProgress,
    Sets,
    SimSettings,
    StepResult,
    StreamFrame,
    SwitchRule,
    TrialCountCriterion,
    TrialOutcome,
    TrialRecord,
    TrialSpec,
    TrialType,
    TrialTypeSet,
)
from .daemon_client import DEFAULT_PORT, TrialdClient
from .daemon_refusals import (
    DaemonIsUnavailable,
    DaemonRefusedTheRequest,
    TheOutcomeIsForAnotherTrial,
)

__all__ = [
    "DEFAULT_PORT",
    "Acceptance",
    "ConfigPatch",
    "ConfigUpdateResult",
    "CounterRow",
    "DaemonIsUnavailable",
    "DaemonRefusedTheRequest",
    "FrameLoss",
    "FreeRunStatus",
    "Manipulandum",
    "Ordering",
    "Outcome",
    "OutcomeReport",
    "PolicyCheckResult",
    "PolicyDiagnostic",
    "PolicyError",
    "PolicyInfo",
    "PolicyOrigin",
    "ResultCount",
    "SessionConfig",
    "SessionState",
    "SetProgress",
    "Sets",
    "SimSettings",
    "StepResult",
    "StreamFrame",
    "SwitchRule",
    "TheOutcomeIsForAnotherTrial",
    "TrialCountCriterion",
    "TrialOutcome",
    "TrialRecord",
    "TrialSpec",
    "TrialType",
    "TrialTypeSet",
    "TrialdClient",
]
