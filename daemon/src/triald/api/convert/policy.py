# SPDX-License-Identifier: AGPL-3.0-or-later
"""The policy a session is running, and what went wrong in one."""

from __future__ import annotations

import datetime as dt
from typing import Any

from google.protobuf.struct_pb2 import Struct

from triald.v1 import policy_pb2

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
