# SPDX-License-Identifier: AGPL-3.0-or-later
"""The session's declarative settings."""

from __future__ import annotations

import grpc

from triald.api import convert
from triald.api.service import ServiceError, SessionService
from triald.api.servicers import state_message
from triald.api.servicers.refusals import answering
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    config_pb2,
    service_pb2_grpc,
    session_pb2,
)


class ConfigServicer(service_pb2_grpc.ConfigServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def ReadConfig(self, request, context) -> config_pb2.SessionConfig:
        return convert.session_config_to_wire(self.service.config)

    async def PatchConfig(self, request, context) -> config_pb2.ConfigUpdateResult:
        """Change part of the config, and hear what the change cost.

        The accept flags and the stop rules take effect on the next trial. The
        ordering, the round count and avoid-repeat rebuild the bag, which
        restarts the round. The rest is refused while a session runs — and the
        answer says what actually changed rather than assuming it all did.
        """

        async def run():
            try:
                changes = convert.config_patch_from_wire(request)
            except convert.config.Refused as problem:
                raise ServiceError(str(problem), kind="config", status=400) from problem
            async with self.service.publishing():
                return convert.config_update_to_wire(self.service.update_config(changes))

        return await answering(context, run)

    async def ResetRounds(self, request, context) -> session_pb2.SessionState:
        """Refill the bag and clear the round and set-progress counters."""
        return await self._reset(context, self.service.reset_rounds)

    async def ResetCounters(self, request, context) -> session_pb2.SessionState:
        """Clear every outcome tally, in every set. The bag and round are left alone."""
        return await self._reset(context, self.service.reset_counters)

    async def _reset(self, context, clear) -> session_pb2.SessionState:
        async def run():
            async with self.service.publishing():
                clear()
            return state_message(self.service)

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_ConfigServicer_to_server(ConfigServicer(service), server)
