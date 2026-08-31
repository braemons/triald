"""A 2-down-1-up staircase over a ladder of named trial types.

Run it against a simulated subject before it goes near a rig:

    uv run triald policy check examples/staircase.py \
        --trial-types contrast_0,contrast_1,contrast_2,contrast_3

    uv run triald sim --policy examples/staircase.py --trials 300 --trace

A policy that selects by name can only be checked against a set that has those
names in it, which is what --trial-types builds. Without it the check runs
against the built-in demo experiment and reports every name as unknown - which
is the check doing its job, not a bug.

The subject in ``triald sim`` has one hit rate for every condition, so this will
climb to the top of the ladder and sit there. That is the simulator being simple,
not the staircase being wrong - point ``hit_rate_by_type`` at a psychometric
function when you want it to converge somewhere interesting.
"""

from triald import Policy, Staircase, TrialOutcome

LEVELS = [f"contrast_{i}" for i in range(6)]


class TwoDownOneUp(Policy):
    def on_session_start(self, state):
        self.stair = Staircase(n_levels=len(LEVELS), level=0, n_down=2)

    def select_trial(self, state):
        return LEVELS[self.stair.level]

    def on_outcome(self, record, state):
        # Only accepted trials move the staircase. Stepping on refused ones -
        # eye errors, frame losses - makes it drift in ways that are very hard
        # to see afterwards.
        if record.accepted:
            self.stair.update(record.report.outcome is TrialOutcome.HIT)

    def should_stop(self, state):
        return self.stair.reversals >= 12

    def snapshot(self):
        # Goes into every trial record, so the level that actually ran is never
        # in doubt when the session is analysed.
        return self.stair.snapshot()
