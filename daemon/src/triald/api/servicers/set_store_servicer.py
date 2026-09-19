# SPDX-License-Identifier: AGPL-3.0-or-later
"""The trial types, in named sets."""

from __future__ import annotations

import grpc

from triald.api import convert
from triald.api.service import Refusal, ServiceError, SessionService
from triald.api.servicers import state_message
from triald.api.servicers.refusals import answering
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    service_pb2_grpc,
    session_pb2,
    sets_pb2,
)


class SetStoreServicer(service_pb2_grpc.SetStoreServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    def _sets(self) -> sets_pb2.Sets:
        snapshot = self.service.sets()
        return convert.sets_to_wire(
            snapshot.sets, active=snapshot.active, chain_problem=snapshot.chain_problem
        )

    async def ReadSets(self, request, context) -> sets_pb2.Sets:
        """Every set, plus whether the switch chain from the active one holds up."""
        return self._sets()

    async def WriteSet(self, request, context) -> sets_pb2.Sets:
        """Add or replace a set, with its trial types and its switch rule."""

        async def run():
            if request.set.name != request.name:
                # The request names the set twice, and they have to agree:
                # renaming is a delete and a write, because a rename that
                # happened by accident would leave the old set behind.
                raise ServiceError(
                    f"the request says {request.name!r} and the set says "
                    f"{request.set.name!r}; renaming a set is a delete and a write",
                    kind="sets",
                    refusal=Refusal.BAD_REQUEST,
                )
            async with self.service.publishing():
                self.service.put_set(convert.trial_type_set_from_wire(request.set))
            return self._sets()

        return await answering(context, run)

    async def DeleteSet(self, request, context) -> sets_pb2.Sets:
        async def run():
            async with self.service.publishing():
                self.service.delete_set(request.name)
            return self._sets()

        return await answering(context, run)

    async def LoadSet(self, request, context) -> session_pb2.SessionState:
        """Make a set active. Its block starts from nothing; counters are banked."""

        async def run():
            async with self.service.publishing():
                self.service.load_set(request.name)
            return state_message(self.service)

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_SetStoreServicer_to_server(SetStoreServicer(service), server)
