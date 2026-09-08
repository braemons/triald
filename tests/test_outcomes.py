"""Acceptance: the counted-versus-accepted distinction, and the two vetoes."""

from __future__ import annotations

import pytest

from triald.outcomes import AcceptancePolicy, FrameLoss, OutcomeReport, TrialOutcome


def report(outcome: TrialOutcome, **kwargs: object) -> OutcomeReport:
    return OutcomeReport(outcome=outcome, **kwargs)  # type: ignore[arg-type]


def test_outcome_codes_are_the_tdr_wire_contract():
    # These values are in every .tdr file the lab has written. Renumbering them
    # silently relabels historical data.
    assert TrialOutcome.UNDETERMINED == -1
    assert TrialOutcome.NOT_STARTED == 0
    assert TrialOutcome.HIT == 1
    assert TrialOutcome.WRONG_RESPONSE == 2
    assert TrialOutcome.EARLY_HIT == 3
    assert TrialOutcome.EARLY_WRONG_RESPONSE == 4
    assert TrialOutcome.EARLY == 5
    assert TrialOutcome.LATE == 6
    assert TrialOutcome.EYE_ERROR == 7
    assert TrialOutcome.UNEXPECTED_START_SIGNAL == 8
    assert TrialOutcome.WRONG_START_SIGNAL == 9
    assert TrialOutcome.CANCELLED == 10


def test_vstim_defaults():
    policy = AcceptancePolicy()
    assert policy.accepts(report(TrialOutcome.HIT))
    assert policy.accepts(report(TrialOutcome.EYE_ERROR))
    assert policy.accepts(report(TrialOutcome.LATE))
    # Off by default in VStim, and deliberately so.
    assert not policy.accepts(report(TrialOutcome.NOT_STARTED))
    assert not policy.accepts(report(TrialOutcome.UNEXPECTED_START_SIGNAL))
    assert not policy.accepts(report(TrialOutcome.WRONG_START_SIGNAL))
    assert not policy.accepts(report(TrialOutcome.CANCELLED))


def test_frame_loss_vetoes_an_otherwise_accepted_outcome():
    policy = AcceptancePolicy(frame_loss=False)
    hit = report(TrialOutcome.HIT)
    lossy = report(TrialOutcome.HIT, frame_loss=FrameLoss(interval=2, frame=17))

    assert policy.accepts(hit)
    assert not policy.accepts(lossy)
    assert "frame loss" in (policy.refusal_reason(lossy) or "")


def test_imprecise_fixation_vetoes_independently():
    policy = AcceptancePolicy(imprecise_fixation=False)
    sloppy = report(TrialOutcome.HIT, precise_fixation=False)

    assert not policy.accepts(sloppy)
    assert "fixation" in (policy.refusal_reason(sloppy) or "")


def test_the_two_vetoes_are_independent_of_each_other():
    # Accepting frame loss must not accidentally accept imprecise fixation.
    policy = AcceptancePolicy(frame_loss=True, imprecise_fixation=False)
    both = report(
        TrialOutcome.HIT,
        precise_fixation=False,
        frame_loss=FrameLoss(interval=0, frame=3),
    )
    assert not policy.accepts(both)


def test_refusal_reason_is_none_when_accepted():
    assert AcceptancePolicy().refusal_reason(report(TrialOutcome.HIT)) is None


@pytest.mark.parametrize("outcome", list(TrialOutcome))
def test_every_outcome_has_an_accept_flag(outcome: TrialOutcome):
    # UNDETERMINED has no flag and must never be accepted: a trial still in
    # flight has not produced a result to accept.
    policy = AcceptancePolicy()
    accepted = policy.accepts_outcome(outcome)
    if outcome is TrialOutcome.UNDETERMINED:
        assert accepted is False
    else:
        assert isinstance(accepted, bool)
