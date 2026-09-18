# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seam between what this daemon thinks in and what it says.

**Every conversion between `triald`'s own types and the generated wire types is
here, and nowhere else.** Not in a handler, not in `triald.state`, not beside
the code that happened to need it. A conversion that lives next to its caller is
a second, quieter description of the interface, and the point of authoring the
interface in one place is that there is no second one.

Names are `X_to_wire` and `X_from_wire`, in that direction and nothing else, so
the direction of a call is readable rather than looked up. mousewheeld's
`daemon/src/convert/` is the same arrangement in Rust, and reading one should
teach you the other.

**Why a seam at all**, when most of these are field-for-field:

* `triald.state` and its neighbours are frozen dataclasses with properties,
  defaults and invariants — `SetProgress.reached` is computed, `TrialSpec` is
  latched at selection. A protobuf message is a mutable bag of fields with no
  opinion, and making the daemon think in one would cost every one of those.
  That is the standing rule here: **proto messages are never internal data.**
* proto3 has no required fields, so a message arriving with nothing set is
  valid. Turning that into either a default or a refusal is work with exactly
  one right place to happen.
* An enum on the wire may hold a number this build has never heard of. Refusing
  it by name, rather than reading it as the first variant, is the same work.
"""

from .config import (
    acceptance_to_wire,
    config_patch_from_wire,
    session_config_to_wire,
)
from .policy import policy_error_to_wire, policy_info_to_wire
from .session import session_state_to_wire, set_progress_to_wire
from .sets import sets_to_wire, trial_type_set_from_wire, trial_type_set_to_wire
from .trial import (
    outcome_report_from_wire,
    trial_record_to_wire,
    trial_spec_to_wire,
)

__all__ = [
    "acceptance_to_wire",
    "config_patch_from_wire",
    "outcome_report_from_wire",
    "policy_error_to_wire",
    "policy_info_to_wire",
    "session_config_to_wire",
    "session_state_to_wire",
    "set_progress_to_wire",
    "sets_to_wire",
    "trial_record_to_wire",
    "trial_spec_to_wire",
    "trial_type_set_from_wire",
    "trial_type_set_to_wire",
]
