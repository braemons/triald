# SPDX-License-Identifier: AGPL-3.0-or-later
"""The translation between triald's vocabulary and statemachined's.

Everything here is about the seam and nothing about the far end: what a
`TrialConfiguration` becomes as a call, what a published trace entry becomes as
the flat dict triald's rules read, and what a refusal becomes as the one
exception the session loop acts on.

**No rig and no daemon**, which is the point of testing a translation rather
than a round trip: the round trip is `statemachined`'s own suite's job, and it
runs there against the daemon that serves the interface. What could go wrong
*here* is that triald reads somebody else's record wrongly, and that is
reproducible with a dict.
"""

from __future__ import annotations

import pytest
from statemachined_client import (
    KIND_STATE_VISIT,
    KIND_TRIAL_RESULT,
    DaemonIsUnavailable,
    NoBoardIsAttached,
    NoSuchDocument,
    TraceEntry,
)

from triald.api.statemachine_executor import (
    OBSERVER_NAME,
    StateMachineExecutor,
    flattened,
)
from triald.executor import ExecutorError, TrialConfiguration
from triald.outcomes import TrialOutcome


class FakeRig:
    """A `StatemachinedClient`'s surface, recording what it was asked.

    Not a mock of the protocol -- the protocol is exercised where it is
    implemented. This records calls so that "triald sent the graph under the
    right name" is an assertion rather than a reading of the source.
    """

    def __init__(self, *, refusal: Exception | None = None, entries=()) -> None:
        self.calls: list[tuple] = []
        self.refusal = refusal
        self.entries = list(entries)
        self.closed = False

    def _note(self, *call):
        self.calls.append(call)
        if self.refusal is not None:
            raise self.refusal

    def configure_trial(self, trial_id, *, graph="", cap_milliseconds=0, **rest):
        self._note("configure", trial_id, graph, cap_milliseconds)

    def start_trial(self, trial_id):
        self._note("start", trial_id)

    def cancel_trial(self, trial_id):
        self._note("cancel", trial_id)

    def read_trial_trace(self, trial_id):
        self._note("trace", trial_id)
        return [entry for entry in self.entries if entry.trial_id == trial_id]

    def watch_trace(self, since_entry_number=0, *, observer=""):
        self._note("watch", since_entry_number, observer)
        return iter(self.entries)

    def close(self):
        self.closed = True


def an_executor(**kwargs) -> tuple[StateMachineExecutor, FakeRig]:
    rig = FakeRig(**kwargs)
    return StateMachineExecutor("rig-3.local", client=rig), rig


def a_visit(trial_id=1, entry_number=1, **payload):
    return TraceEntry(
        entry_number=entry_number,
        kind=KIND_STATE_VISIT,
        trial_id=trial_id,
        payload={"state_name": "Cue", "exit_cause": "transition", **payload},
    )


def a_result(trial_id=1, entry_number=2, outcome="HIT", **payload):
    return TraceEntry(
        entry_number=entry_number,
        kind=KIND_TRIAL_RESULT,
        trial_id=trial_id,
        payload={"outcome": outcome, **payload},
    )


# -- outwards -------------------------------------------------------------------


def test_the_graph_crosses_under_the_far_ends_name_for_it():
    """triald says `statemachine_graph` because a bare "graph" says nothing
    about whose it is. There, the namespace supplies the rest."""
    executor, rig = an_executor()
    executor.configure(
        TrialConfiguration(trial_id=7, statemachine_graph="go-nogo", cap_milliseconds=30_000)
    )
    assert rig.calls == [("configure", 7, "go-nogo", 30_000)]


def test_starting_and_cancelling_carry_the_trial_id_and_nothing_else():
    executor, rig = an_executor()
    executor.start(7)
    executor.cancel(7, reason="the operator asked")
    assert rig.calls == [("start", 7), ("cancel", 7)]


def test_a_cancel_reason_is_triald_s_and_does_not_cross():
    """The far end records *its* reason for a cancellation -- host, link lost,
    abort line. triald's sentence about why it asked is triald's record."""
    executor, rig = an_executor()
    executor.cancel(7, reason="a very specific explanation")
    assert "a very specific explanation" not in str(rig.calls)


# -- refusals -------------------------------------------------------------------


@pytest.mark.parametrize(
    "refusal",
    [
        NoSuchDocument("not_found", "no_such_graph", "no graph called 'go-nogo'", "graph"),
        NoBoardIsAttached("unavailable", "not_connected", "no board is connected", "device"),
        DaemonIsUnavailable("unavailable", "unavailable", "nothing answered"),
    ],
)
def test_every_refusal_becomes_the_one_exception_the_session_loop_acts_on(refusal):
    """The session loop acts on exactly one thing: this call did not happen."""
    executor, _ = an_executor(refusal=refusal)
    with pytest.raises(ExecutorError):
        executor.start(7)


def test_nothing_is_thrown_away_in_the_folding():
    """The refusal's own words survive, and `__cause__` keeps the original.

    A loop that flattened `no_such_graph: no graph called 'go-nogo'` into
    "the executor refused" would leave the person reading the log with nothing.
    """
    refusal = NoSuchDocument("not_found", "no_such_graph", "no graph called 'go-nogo'", "graph")
    executor, _ = an_executor(refusal=refusal)
    with pytest.raises(ExecutorError) as failure:
        executor.start(7)
    assert "no_such_graph" in str(failure.value)
    assert "no graph called 'go-nogo'" in str(failure.value)
    assert failure.value.__cause__ is refusal


# -- reading somebody else's record ---------------------------------------------


def test_a_published_entry_becomes_the_flat_dict_triald_s_rules_read():
    """statemachined's ring holds flat records; its wire type names four
    fields and carries the rest in `payload` because the set differs per
    kind. Putting them back together is the whole of `flattened`."""
    record = flattened(a_visit(measured_duration_microseconds=183_044))
    assert record["kind"] == "visit", "the far end's word, asserted as a literal on purpose"
    assert record["trial_id"] == 1
    assert record["exit_cause"] == "transition"
    assert record["measured_duration_microseconds"] == 183_044


def test_the_named_fields_win_over_the_payload():
    """A payload that happened to carry a `trial_id` of its own would
    otherwise decide which trial an entry belonged to."""
    entry = TraceEntry(entry_number=3, kind="trial_result", trial_id=7, payload={"trial_id": 9})
    assert flattened(entry)["trial_id"] == 7


def test_an_outcome_is_read_out_of_what_was_published():
    executor, _ = an_executor(entries=[a_visit(), a_result(outcome="LATE")])
    assert executor.outcome_of(1).outcome is TrialOutcome.LATE


def test_a_reaction_time_is_the_last_state_a_transition_left():
    """triald's rule, applied to the far end's record, and it stays triald's:
    changing it must not mean changing firmware."""
    entries = [
        a_visit(entry_number=1, measured_duration_microseconds=500_000, exit_cause="timeout"),
        a_visit(entry_number=2, measured_duration_microseconds=183_044),
        a_result(entry_number=3),
    ]
    executor, _ = an_executor(entries=entries)
    assert executor.outcome_of(1).reaction_time_ms == pytest.approx(183.044)


def test_another_trials_entries_are_not_merged_in():
    """A mixed batch is a bug upstream, and averaging two trials together is
    worse than dropping one."""
    executor, _ = an_executor(entries=[a_visit(trial_id=2), a_result(trial_id=1)])
    assert executor.outcome_of(1).terminating_interval is None


def test_a_trial_with_no_published_result_is_an_executor_error():
    executor, _ = an_executor(entries=[a_visit()])
    with pytest.raises(ExecutorError):
        executor.outcome_of(1)


# -- the subscription -----------------------------------------------------------


def test_subscribing_names_triald_and_starts_where_it_is_asked():
    """The name is a label and nothing is granted by it -- it is what lets a
    person see triald is listening without reaching for a packet capture."""
    executor, rig = an_executor()
    executor.subscribe(since_entry_number=41)
    assert rig.calls == [("watch", 41, OBSERVER_NAME)]


def test_finished_trials_yields_a_trial_once_it_has_ended():
    executor, _ = an_executor()
    entries = [a_visit(trial_id=1), a_result(trial_id=1), a_visit(trial_id=2)]
    assert list(executor.finished_trials(entries)) == [1]


def test_finished_trials_takes_the_flat_dicts_too():
    """So the rule stays testable with a list of dicts, and a replay of a log
    file is as good an input as a live stream."""
    executor, _ = an_executor()
    events = [{"kind": "trial_result", "trial_id": 4}, {"kind": "visit", "trial_id": 4}]
    assert list(executor.finished_trials(events)) == [4]


def test_an_entry_with_no_trial_is_not_a_finished_trial():
    """The ring carries entries that belong to no trial -- a setting saved, a
    link coming back. Yielding `None` as a trial id would be a trial."""
    executor, _ = an_executor()
    assert list(executor.finished_trials([{"kind": "trial_result", "trial_id": None}])) == []


def test_closing_the_executor_closes_the_connection():
    executor, rig = an_executor()
    executor.close()
    assert rig.closed
