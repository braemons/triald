# SPDX-License-Identifier: AGPL-3.0-or-later
"""The policy a session is running, and what went wrong in one."""

from __future__ import annotations

import datetime as dt
from typing import Any

from google.protobuf.struct_pb2 import (
    Struct,  # ty: ignore[unresolved-import]  (built at runtime by protobuf's builder)
)

from triald.v1 import (
    policy_pb2,  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
)

_ORIGINS = {
    "default": policy_pb2.POLICY_ORIGIN_DEFAULT,
    "file": policy_pb2.POLICY_ORIGIN_FILE,
    "uploaded": policy_pb2.POLICY_ORIGIN_UPLOADED,
}


def policy_info_to_wire(info: dict[str, Any]) -> policy_pb2.PolicyInfo:
    """What the session service reports about its policy.

    A dict rather than a type, because that is what the service hands over
    today; the shape is `PolicyInfo` above and this is where it becomes one.
    """
    message = policy_pb2.PolicyInfo(
        name=info["name"],
        class_name=info["class_name"],
        origin=_ORIGINS.get(info.get("origin", ""), policy_pb2.POLICY_ORIGIN_UNSPECIFIED),
    )
    if info.get("sha256") is not None:
        message.sha256 = info["sha256"]
    if info.get("source") is not None:
        message.source = info["source"]
    if info.get("state") is not None:
        state = Struct()
        state.update(info["state"])
        message.state.CopyFrom(state)
    return message


def policy_error_to_wire(error: dict[str, Any]) -> policy_pb2.PolicyError:
    message = policy_pb2.PolicyError(
        hook=error["hook"],
        trial_number=error["trial_number"],
        error=error["error"],
        traceback=error["traceback"],
    )
    at = error["at"]
    message.at.FromDatetime(
        at if isinstance(at, dt.datetime) else dt.datetime.fromisoformat(at)
    )
    return message


def policy_check_to_wire(check) -> policy_pb2.PolicyCheckResult:
    """What checking a policy found.

    A diagnostic's line and column are absent when there is nothing to point at
    — the policy imported and then misbehaved — rather than zero, which an
    editor would happily jump to.
    """
    message = policy_pb2.PolicyCheckResult(
        ok=check.ok, sha256=check.sha256, trials_run=check.trials_run
    )
    if check.class_name is not None:
        message.class_name = check.class_name
    for line, column, text in check.diagnostics:
        diagnostic = message.diagnostics.add(message=text)
        if line is not None:
            diagnostic.line = line
        if column is not None:
            diagnostic.column = column
    return message
