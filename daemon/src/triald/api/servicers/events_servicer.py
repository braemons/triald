# SPDX-License-Identifier: AGPL-3.0-or-later
"""Things that happened that nothing else records."""

from __future__ import annotations

import grpc

from triald.api.service import SessionService
from triald.api.servicers.refusals import answering
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    common_pb2,
    service_pb2_grpc,
)


class EventsServicer(service_pb2_grpc.EventsServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def Note(self, request, context) -> common_pb2.Ok:
        """Append an experimenter's note to the session's event stream.

        Not inside `publishing()`: a note changes nothing a panel draws, and a
        frame pushed to every watcher for a line of text is noise.
        """

        async def run():
            self.service.note(request.text)
            return common_pb2.Ok(ok=True)

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_EventsServicer_to_server(EventsServicer(service), server)
