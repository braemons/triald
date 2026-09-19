# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Python that decides what happens next, when the settings are not enough."""

from __future__ import annotations

import grpc

from triald.api import convert
from triald.api.service import SessionService
from triald.api.servicers.refusals import answering, reject_unknown_fields
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    policy_pb2,
    service_pb2_grpc,
)


class PolicyServicer(service_pb2_grpc.PolicyServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def ReadPolicy(self, request, context) -> policy_pb2.PolicyInfo:
        """The running policy, its content hash, and its last snapshot().

        `source` is asked for rather than always sent: the text is large and a
        panel polling once a second does not want it.
        """
        return convert.policy_info_to_wire(self.service.policy_info(with_source=request.source))

    async def CheckPolicy(self, request, context) -> policy_pb2.PolicyCheckResult:
        """Import and smoke-run source text without touching the session.

        A policy that raises on trial 200 is worth finding out about before
        there is an animal in the rig. Diagnostics carry line numbers so an
        editor can mark the offending line.
        """

        async def run():
            reject_unknown_fields(request, "the policy")
            return convert.policy_check_to_wire(
                self.service.check_policy(request.name, request.source)
            )

        return await answering(context, run)

    async def LoadPolicy(self, request, context) -> policy_pb2.PolicyInfo:
        """Store source text and run it from the next arm onwards.

        Checked first, always: a syntax error must never reach a session.
        """

        async def run():
            reject_unknown_fields(request, "the policy")
            async with self.service.publishing():
                info = self.service.load_policy_source(request.name, request.source)
            return convert.policy_info_to_wire(info)

        return await answering(context, run)

    async def ClearPolicy(self, request, context) -> policy_pb2.PolicyInfo:
        """Go back to the declarative ordering."""

        async def run():
            async with self.service.publishing():
                return convert.policy_info_to_wire(self.service.clear_policy())

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_PolicyServicer_to_server(PolicyServicer(service), server)
