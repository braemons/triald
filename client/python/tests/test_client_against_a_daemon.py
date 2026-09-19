# SPDX-License-Identifier: AGPL-3.0-or-later
"""The client against a real triald, over a real gRPC channel.

**Not a mock.** A mock of the daemon would assert that this client agrees with
a second description of triald, written by the same hand on the same day, and
would keep passing the day the daemon changed. These run the daemon.

What they are for is the half the seam tests cannot reach: that the rpcs are
wired to the methods that claim them, that a refusal arrives as the right class
with the right `error`, and that the stream yields.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest
from triald_client import (
    ConfigPatch,
    DaemonRefusedTheRequest,
    Ordering,
    OutcomeReport,
    SimSettings,
    TheOutcomeIsForAnotherTrial,
    TrialOutcome,
    TrialType,
    TrialTypeSet,
)

# -- reading ---------------------------------------------------------------------


def test_the_state_reads_before_anything_is_armed(idle):
    state = idle.read_state()
    assert state.running is False
    assert state.set_name  # the demo experiment has a set loaded
    assert state.config is not None


def test_the_config_reads_and_is_the_same_one_the_state_carries(idle):
    assert idle.read_config() == idle.read_state().config


def test_the_sets_read_with_their_rules(idle):
    sets = idle.read_sets()
    assert sets.sets
    assert sets.active is not None
    by_name = {each.name: each for each in sets.sets}
    assert by_name[sets.active].active is True


# -- the trial loop --------------------------------------------------------------


def test_a_whole_trial_goes_round(running):
    trial = running.next_trial()
    assert trial.trial_number >= 1
    assert trial.set_name

    record = running.report_outcome(
        trial.trial_number,
        OutcomeReport(outcome=TrialOutcome.HIT, reaction_time_ms=212.0, reward_ms=120),
    )
    assert record.trial is not None
    assert record.trial.trial_number == trial.trial_number
    assert record.outcome is not None
    assert record.outcome.code is TrialOutcome.HIT
    assert record.outcome.reaction_time_ms == 212.0
    assert record.accepted is True


def test_a_trial_that_lost_a_frame_is_counted_and_not_accepted(running):
    """The distinction the whole daemon is built around, seen from a client.

    Every outcome is *counted*; only an accepted one consumes from the round.
    Frame loss can veto a hit on its own — but only if the config says so, and
    the shipped default is to accept them, which is why this turns the flag off
    first rather than assuming.
    """
    from triald_client import Acceptance, FrameLoss

    config = running.read_config()
    running.update_config(ConfigPatch(acceptance=replace(config.acceptance, frame_loss=False)))
    try:
        before = running.read_state().totals
        trial = running.next_trial()
        record = running.report_outcome(
            trial.trial_number,
            OutcomeReport(outcome=TrialOutcome.HIT, frame_loss=FrameLoss(interval=1, frame=3)),
        )
        assert record.accepted is False
        assert record.refusal_reason  # it says which of the three turned it away
        assert record.outcome.code is TrialOutcome.HIT  # still a hit; just not accepted

        after = running.read_state().totals
        assert after.total == (before.total if before else 0) + 1
        assert after.accepted == (before.accepted if before else 0)
    finally:
        running.update_config(ConfigPatch(acceptance=config.acceptance))
    assert Acceptance().frame_loss is True  # the default this test had to turn off


def test_asking_for_a_second_trial_without_reporting_is_refused(running):
    running.next_trial()
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        running.next_trial()
    assert refusal.value.status == "failed_precondition"
    assert refusal.value.retryable is False


def test_an_outcome_for_another_trial_is_refused_by_name(running):
    """The refusal a correct rig loop can hit, and the one worth catching.

    A report that crossed the network twice, or arrived after the watchdog gave
    up: the answer is to drop it, never to retry it against whatever is in
    flight now.
    """
    trial = running.next_trial()
    with pytest.raises(TheOutcomeIsForAnotherTrial) as refusal:
        running.report_outcome(trial.trial_number - 1, OutcomeReport(outcome=TrialOutcome.HIT))
    assert refusal.value.error == "trial_mismatch"

    # And the refused report changed nothing: the trial is still in flight.
    assert running.read_state().current.trial_number == trial.trial_number
    running.report_outcome(trial.trial_number, OutcomeReport(outcome=TrialOutcome.HIT))


def test_a_cancelled_trial_is_recorded_rather_than_dropped(running):
    trial = running.next_trial()
    record = running.cancel_trial("the animal left")
    assert record.outcome is not None
    assert record.outcome.code is TrialOutcome.CANCELLED
    assert record.trial.trial_number == trial.trial_number


# -- refusals --------------------------------------------------------------------


def test_arming_twice_is_refused(running):
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        running.arm()
    assert refusal.value.error == "session"
    assert "already running" in refusal.value.detail


def test_a_trial_without_a_session_is_refused(idle):
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        idle.next_trial()
    assert refusal.value.status == "failed_precondition"


def test_a_set_that_is_not_there_is_not_found(running):
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        running.load_set("no_such_set_exists")
    assert refusal.value.status == "not_found"
    assert refusal.value.error == "sets"


def test_loading_a_set_with_no_session_is_refused_as_the_wrong_moment(idle):
    # A different refusal from the one above, and the difference matters: the
    # set may well exist, and the answer is to arm rather than to fix a name.
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        idle.load_set("no_such_set_exists")
    assert refusal.value.status == "failed_precondition"


def test_an_arm_time_setting_is_refused_mid_session(running):
    # `seed` decides something that has already happened, so changing it would
    # leave a record whose first half means something different from its second.
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        running.update_config(ConfigPatch(seed=7))
    assert refusal.value.status == "invalid_argument"


def test_a_refusal_prints_as_its_kind_and_its_sentence(idle):
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        idle.next_trial()
    assert str(refusal.value).startswith(f"{refusal.value.error}: ")


# -- config ----------------------------------------------------------------------


def test_a_patch_says_what_it_changed_and_what_it_cost(idle):
    was = idle.read_config().rounds
    result = idle.update_config(ConfigPatch(rounds=was + 1))
    assert "rounds" in result.changed
    assert result.config.rounds == was + 1
    idle.update_config(ConfigPatch(rounds=was))


def test_changing_the_ordering_rebuilds_the_bag(idle):
    was = idle.read_config().ordering
    other = (
        Ordering.RANDOM_IN_EXPERIMENT
        if was is Ordering.RANDOM_IN_ROUND
        else Ordering.RANDOM_IN_ROUND
    )
    result = idle.update_config(ConfigPatch(ordering=other))
    assert result.bag_rebuilt is True
    idle.update_config(ConfigPatch(ordering=was))


def test_an_empty_patch_changes_nothing(idle):
    assert idle.update_config(ConfigPatch()).changed == ()


# -- sets ------------------------------------------------------------------------


def test_a_set_can_be_written_read_back_and_deleted(idle):
    written = TrialTypeSet(
        name="from_the_client",
        trial_types=(
            TrialType(name="a", trials_per_round=2, reward_ms=100, params={"contrast": 0.25}),
        ),
    )
    sets = idle.write_set(written)
    stored = {each.name: each for each in sets.sets}["from_the_client"]
    assert stored.trial_types[0].params == {"contrast": 0.25}
    assert stored.trials_per_round == 2  # the daemon's own view, summed

    after = idle.delete_set("from_the_client")
    assert "from_the_client" not in {each.name for each in after.sets}


# -- the stream ------------------------------------------------------------------


def test_the_stream_yields_the_current_state_at_once(idle):
    # It does not wait for something to happen: a client that connected to a
    # quiet rig and saw nothing would have no way to tell that from a rig that
    # is not there.
    first = next(itertools.islice(idle.watch_states(), 1))
    assert first.set_name == idle.read_state().set_name


def test_the_stream_pushes_a_frame_when_something_changes(running):
    frames = running.watch_states()
    next(frames)  # the state on connect

    running.next_trial()
    for state in itertools.islice(frames, 5):
        if state.current is not None:
            break
    else:  # pragma: no cover - only on a daemon that stopped publishing
        pytest.fail("no frame arrived carrying the trial in flight")


# -- the simulated subject -------------------------------------------------------


def test_stepping_runs_whole_trials_through_the_real_loop(running):
    before = running.read_state().trials_started
    result = running.step(5)
    assert result.trials == 5
    assert result.state.trials_started == before + 5


def test_the_sim_dials_can_be_read_and_set(idle):
    was = idle.read_sim()
    set_to = idle.write_sim(SimSettings(hit_rate=0.5, hit_rate_by_type={"a": 0.1}))
    assert set_to.hit_rate == 0.5
    assert set_to.hit_rate_by_type == {"a": 0.1}
    idle.write_sim(was)


def test_free_run_can_be_started_and_stopped(running):
    assert running.write_free_run(True, interval_ms=10).running is True
    assert running.read_free_run().running is True
    assert running.write_free_run(False).running is False


# -- policies --------------------------------------------------------------------


GOOD_POLICY = """
from triald.policy import Policy


class Staircase(Policy):
    def snapshot(self):
        return {"level": 3}
"""

BROKEN_POLICY = "this is not python(\n"


def test_a_policy_is_checked_before_it_is_loaded(idle):
    result = idle.check_policy("staircase", GOOD_POLICY)
    assert result.ok is True
    assert result.sha256


def test_a_broken_policy_is_refused_with_a_line_number(idle):
    result = idle.check_policy("broken", BROKEN_POLICY)
    assert result.ok is False
    assert result.diagnostics
    assert result.diagnostics[0].line is not None


def test_loading_a_broken_policy_is_refused_rather_than_stored(idle):
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        idle.load_policy("broken", BROKEN_POLICY)
    assert refusal.value.error == "policy"


def test_a_policy_loads_and_clears(idle):
    loaded = idle.load_policy("staircase", GOOD_POLICY)
    assert loaded.class_name == "Staircase"
    assert loaded.sha256

    with_source = idle.read_policy(with_source=True)
    assert with_source.source is not None and "class Staircase" in with_source.source

    cleared = idle.clear_policy()
    assert cleared.class_name != "Staircase"


# -- events ----------------------------------------------------------------------


def test_a_note_with_nothing_recording_is_refused(idle):
    # Refused rather than dropped: the person who typed it believes it was kept.
    with pytest.raises(DaemonRefusedTheRequest) as refusal:
        idle.note("a note nobody can keep")
    assert refusal.value.error == "recording"


def test_a_note_is_taken_while_recording(running):
    running.start_recording()
    try:
        running.note("the animal settled")
    finally:
        running.stop_recording()
