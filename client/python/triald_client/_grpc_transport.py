# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gRPC channel, and the one place a transport failure becomes a refusal.

Nothing above this imports grpc, and nothing below it knows what a trial is.
The refusals themselves are `daemon_refusals.py`, because those are public and
this is not.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import grpc

from ._proto.triald.v1 import common_pb2
from .daemon_refusals import (
    DaemonIsUnavailable,
    DaemonRefusedTheRequest,
    TheOutcomeIsForAnotherTrial,
)

#: Where the daemon puts the refusal as itself. See
#: `daemon/src/triald/api/servicers/refusals.py`.
REFUSAL_METADATA_KEY = "triald-error-bin"

#: The refusal kinds that have a class of their own. Everything else is a
#: `DaemonRefusedTheRequest` with its `error` set — a kind this client has
#: never heard of is still catchable, still readable, and still says what to
#: change, which is what makes the vocabulary safe to extend.
_CLASS_FOR_KIND = {"trial_mismatch": TheOutcomeIsForAnotherTrial}


def refusal_of(error: grpc.RpcError) -> DaemonRefusedTheRequest:
    """A gRPC failure, as this package's refusal.

    A call that never landed — no daemon, a closed channel, a deadline — has no
    `triald.v1.Error` to carry, because nothing refused anything. It keeps the
    gRPC code and whatever the transport said.
    """
    status = error.code().name.lower()  # ty: ignore[unresolved-attribute]
    detail = error.details() or status  # ty: ignore[unresolved-attribute]
    body = _typed_refusal(error)
    if body is None:
        body = common_pb2.Error(error=status, detail=detail)
    if status == "unavailable":
        return DaemonIsUnavailable(status, body.error, body.detail)
    kind = _CLASS_FOR_KIND.get(body.error, DaemonRefusedTheRequest)
    return kind(status, body.error, body.detail)


def _typed_refusal(error: grpc.RpcError) -> common_pb2.Error | None:
    for key, value in error.trailing_metadata() or ():  # ty: ignore[unresolved-attribute]
        if key == REFUSAL_METADATA_KEY:
            try:
                return common_pb2.Error.FromString(value)
            except Exception:
                return None  # a refusal we cannot read is still a refusal
    return None


def call[T](action: Callable[[], T]) -> T:
    """One rpc, with a gRPC failure turned into a refusal."""
    try:
        return action()
    except grpc.RpcError as error:
        raise refusal_of(error) from None


def stream[T](action: Callable[[], Iterator[T]]) -> Iterator[T]:
    """One server-streaming rpc.

    The refusal has to be raised from inside the iteration, because that is
    where gRPC raises it: a stream that fails after a thousand frames fails on
    the thousand-and-first `next`, not on the call that opened it.
    """
    try:
        yield from action()
    except grpc.RpcError as error:
        if error.code() is grpc.StatusCode.CANCELLED:  # ty: ignore[unresolved-attribute]
            return  # our own close, not a failure
        raise refusal_of(error) from None
