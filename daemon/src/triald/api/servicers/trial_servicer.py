# SPDX-License-Identifier: AGPL-3.0-or-later
"""The trial loop: select, report, cancel.

This is the service in the critical path of every trial, and the one whose
refusals matter most — `contracts/INTERACTIONS.md` §5.1 is what leaving the
`trial_id` check out of it cost once.
"""

from __future__ import annotations

import grpc

from triald._proto.triald.v1 import (
    service_pb2_grpc,
    trial_pb2,
)
from triald.api import convert
from triald.api.service import Refusal, ServiceError, SessionService
from triald.api.servicers.refusals import answering


class TrialServicer(service_pb2_grpc.TrialServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def Next(self, request, context) -> trial_pb2.TrialSpec:
        """Select the next trial type and publish it.

        Everything about the trial is latched here, `recording` included.
        Refused while a trial is already in flight — report or cancel it first,
        which is what stops one result being attributed to another trial.
        """

        async def run():
            async with self.service.publishing():
                return convert.trial_spec_to_wire(self.service.next_trial())

        return await answering(context, run)

    async def ReportOutcome(self, request, context) -> trial_pb2.TrialRecord:
        """Report how the trial in flight ended. The primary inbound message.

        The reply says whether it was *accepted* as well as counted, and why
        not when it was not.
        """

        async def run():
            if not request.HasField("trial_id"):
                # `optional` although it is required: proto3 has no required
                # fields and a plain int64 cannot tell "trial 0" from "no trial
                # named". Absent is a bad request rather than a conflict, which
                # is what defaulting it to 0 silently made it.
                raise ServiceError(
                    "trial_id says which trial this is the outcome of, and is required: "
                    "a report that arrives late or twice must be refusable rather than "
                    "attributed to the trial after the one it belongs to",
                    kind="request",
                    refusal=Refusal.BAD_REQUEST,
                )
            # An open enum carries any number on the binary wire, including
            # ones this build has never heard of. Refused by name here rather
            # than left to crash the conversion below.
            for field in ("outcome", "manipulandum"):
                enum = request.DESCRIPTOR.fields_by_name[field].enum_type
                value = getattr(request, field)
                if value not in enum.values_by_number:
                    raise ServiceError(
                        f"{field} {value} is not a value of {enum.full_name}",
                        kind="request",
                        refusal=Refusal.BAD_REQUEST,
                    )
            async with self.service.publishing():
                record = self.service.report_outcome(
                    convert.outcome_report_from_wire(request), trial_id=request.trial_id
                )
            return convert.trial_record_to_wire(record)

        return await answering(context, run)

    async def Cancel(self, request, context) -> trial_pb2.TrialRecord:
        """End the trial in flight as CANCELLED.

        Recorded rather than dropped, so a gap in the trial numbering never has
        to be explained afterwards.
        """

        async def run():
            async with self.service.publishing():
                return convert.trial_record_to_wire(self.service.cancel_trial(request.reason))

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_TrialServicer_to_server(TrialServicer(service), server)
