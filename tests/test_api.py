"""The API: the wire shape, the routes, and the debug controls.

Two things are worth stating about what is tested here.

**The record shape and the wire shape must not drift.** ``trials.jsonl`` and the
WebSocket stream carry the same trial, and one test asserts they carry it
identically. That is the whole reason the models were written to mirror
``as_dict()`` rather than to be nicer than it.

**The debug controls are not a second code path.** A ``/api/debug/step`` goes
through :func:`triald.runner.run_trial`, so the counted-versus-accepted
distinction has to survive it exactly as it does on a rig. It is tested here for
the same reason it is tested in ``test_session.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the API needs the 'serve' extra")

from fastapi.testclient import TestClient

from triald.api import SessionService, create_app
from triald.api import schemas as sc
from triald.counters import TrialCountCriterion
from triald.selection import Ordering
from triald.session import SessionConfig
from triald.trialtypes import SwitchRule, TrialType, TrialTypeSet, TrialTypeStore


def make_store() -> TrialTypeStore:
    """Two sets that hand over to each other, which is what a sequence is."""
    return TrialTypeStore(
        [
            TrialTypeSet(
                name="easy",
                trial_types=[
                    TrialType(name="easy_a", trials_per_round=2, reward_ms=100),
                    TrialType(name="easy_b", trials_per_round=2, reward_ms=110),
                ],
                switch_rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.HITS,
                    count=5,
                    target="hard",
                ),
            ),
            TrialTypeSet(
                name="hard",
                trial_types=[
                    TrialType(name="hard_a", trials_per_round=1, reward_ms=150),
                    TrialType(name="hard_b", trials_per_round=1, reward_ms=150),
                ],
            ),
        ]
    )


@pytest.fixture
def service() -> SessionService:
    return SessionService(
        make_store(),
        SessionConfig(initial_set="easy", rounds=4, seed=0),
    )


@pytest.fixture
def client(service: SessionService) -> TestClient:
    with TestClient(create_app(service)) as client:
        yield client


def next_trial(client: TestClient) -> int:
    """Select a trial and give its number, which its outcome has to carry."""
    response = client.post("/api/trial/next")
    assert response.status_code == 200, response.text
    return response.json()["trial_number"]


def arm(client: TestClient) -> dict:
    response = client.post("/api/session/arm")
    assert response.status_code == 200, response.text
    return response.json()


# -- the snapshot ---------------------------------------------------------------


def test_state_is_readable_before_anything_is_armed(client: TestClient):
    state = client.get("/api/state").json()
    assert state["armed"] is False
    assert state["running"] is False
    assert state["set_name"] == "easy"
    # The counters table has its rows before the first trial, so the UI is not
    # empty while somebody decides whether to start.
    assert [row["name"] for row in state["counters"]] == ["easy_a", "easy_b"]


def test_arming_publishes_a_full_snapshot(client: TestClient):
    state = arm(client)
    assert state["running"] is True
    assert state["armed"] is True
    assert state["trials_remaining"] == 4
    assert state["trials_per_round"] == 4
    assert sum(row["p_next"] for row in state["counters"]) == pytest.approx(1.0)


def test_arming_twice_is_refused_while_one_runs(client: TestClient):
    arm(client)
    response = client.post("/api/session/arm")
    assert response.status_code == 409
    assert response.json()["error"] == "session"
    assert "already running" in response.json()["detail"]


def test_the_trial_loop_refuses_to_run_unarmed(client: TestClient):
    response = client.post("/api/trial/next")
    assert response.status_code == 409
    assert "arm it first" in response.json()["detail"]


# -- one trial by hand ----------------------------------------------------------


def test_a_trial_can_be_selected_and_reported(client: TestClient):
    arm(client)
    spec = client.post("/api/trial/next").json()
    assert spec["trial_number"] == 1
    assert spec["set_name"] == "easy"

    record = client.post("/api/trial/outcome", json={"trial_id": 1, "outcome": "HIT"}).json()
    assert record["outcome"]["code"] == 1
    assert record["accepted"] is True
    assert record["refusal_reason"] is None


def test_an_outcome_may_be_given_by_code_or_by_name(client: TestClient):
    arm(client)
    trial = next_trial(client)
    by_name = client.post(
        "/api/trial/outcome", json={"trial_id": trial, "outcome": "EYE_ERROR"}
    ).json()
    trial = next_trial(client)
    by_code = client.post("/api/trial/outcome", json={"trial_id": trial, "outcome": 7}).json()
    assert by_name["outcome"]["code"] == by_code["outcome"]["code"] == 7


def test_an_outcome_for_another_trial_is_refused(client: TestClient):
    # The failure this exists to stop: a report that arrives late is attributed
    # to the trial *after* the one it belongs to, and the dataset is quietly
    # mislabelled. Refusing is the only safe answer - triald cannot know whether
    # the late one or the current one is the truth.
    arm(client)
    trial = next_trial(client)

    response = client.post("/api/trial/outcome", json={"trial_id": trial - 1, "outcome": "HIT"})
    assert response.status_code == 409
    assert f"trial {trial} is the one in flight" in response.json()["detail"]

    # And the refused report changed nothing: the trial is still in flight.
    state = client.get("/api/state").json()
    assert state["current"]["trial_number"] == trial
    assert state["totals"]["total"] == 0


def test_an_outcome_without_a_trial_id_is_refused(client: TestClient):
    # Required, not defaulted. A default would make the check silently optional
    # for exactly the caller that needs it - the one on the far end of a wire.
    arm(client)
    next_trial(client)

    response = client.post("/api/trial/outcome", json={"outcome": "HIT"})
    assert response.status_code == 422
    assert "trial_id" in response.text


def test_an_unknown_outcome_name_is_refused_with_the_alternatives(client: TestClient):
    arm(client)
    trial = next_trial(client)
    response = client.post(
        "/api/trial/outcome", json={"trial_id": trial, "outcome": "SPLENDID"}
    )
    assert response.status_code == 422
    assert "HIT" in response.text


def test_two_selections_without_a_result_are_refused(client: TestClient):
    # The rule that stops one trial's result being attributed to another.
    arm(client)
    client.post("/api/trial/next")
    response = client.post("/api/trial/next")
    assert response.status_code == 409
    assert "still in flight" in response.json()["detail"]


def test_a_cancelled_trial_is_recorded_rather_than_dropped(client: TestClient):
    arm(client)
    client.post("/api/trial/next")
    record = client.post("/api/trial/cancel", json={"reason": "the door opened"}).json()
    assert record["outcome"]["name"] == "CANCELLED"
    assert record["outcome"]["note"] == "the door opened"
    assert record["accepted"] is False


def test_frame_loss_vetoes_an_otherwise_accepted_hit(client: TestClient):
    """A hit that lost a frame is still a hit: counted, but not accepted."""
    arm(client)
    client.patch("/api/config", json={"acceptance": {"frame_loss": False}})
    trial = next_trial(client)
    record = client.post(
        "/api/trial/outcome",
        json={"trial_id": trial, "outcome": "HIT", "frame_loss": {"interval": 1, "frame": 6}},
    ).json()

    assert record["accepted"] is False
    assert "frame loss" in record["refusal_reason"]

    state = client.get("/api/state").json()
    assert state["totals"]["total"] == 1
    assert state["totals"]["accepted"] == 0
    assert state["totals"]["hits"] == 1  # counted, and it still moves the set on


def test_imprecise_fixation_vetoes_on_its_own(client: TestClient):
    arm(client)
    client.patch("/api/config", json={"acceptance": {"imprecise_fixation": False}})
    trial = next_trial(client)
    record = client.post(
        "/api/trial/outcome",
        json={"trial_id": trial, "outcome": "HIT", "precise_fixation": False},
    ).json()
    assert record["accepted"] is False
    assert "imprecise fixation" in record["refusal_reason"]


# -- the debug stepper ----------------------------------------------------------


def test_stepping_runs_whole_trials(client: TestClient):
    arm(client)
    result = client.post("/api/debug/step", json={"trials": 20}).json()
    assert result["trials"] == 20
    assert result["state"]["trials_started"] == 20
    assert result["state"]["totals"]["total"] == 20


def test_stepping_is_refused_with_a_trial_in_flight(client: TestClient):
    arm(client)
    client.post("/api/trial/next")
    response = client.post("/api/debug/step", json={"trials": 1})
    assert response.status_code == 409
    assert "in flight" in response.json()["detail"]


def test_the_simulated_subject_can_be_retuned(client: TestClient):
    arm(client)
    client.put(
        "/api/debug/sim",
        json={
            "hit_rate": 1.0,
            "not_started_rate": 0.0,
            "eye_error_rate": 0.0,
            "early_rate": 0.0,
        },
    )
    result = client.post("/api/debug/step", json={"trials": 30}).json()
    assert result["state"]["totals"]["hits"] == 30


def test_a_step_carries_the_session_into_the_next_set(client: TestClient):
    """The switch rule fires from the API exactly as it does from the CLI."""
    arm(client)
    client.put(
        "/api/debug/sim",
        json={
            "hit_rate": 1.0,
            "not_started_rate": 0.0,
            "eye_error_rate": 0.0,
            "early_rate": 0.0,
        },
    )
    result = client.post("/api/debug/step", json={"trials": 10}).json()
    assert result["state"]["set_name"] == "hard"
    # Session totals climb across a switch; the set's own progress starts again.
    assert result["state"]["totals"]["total"] == 10
    assert result["state"]["set_progress"]["hits"] < 10


# -- config ---------------------------------------------------------------------


def test_the_accept_flags_take_effect_on_the_next_trial(client: TestClient):
    arm(client)
    result = client.patch("/api/config", json={"acceptance": {"eye_error": False}}).json()
    assert result["changed"] == ["acceptance"]
    assert result["bag_rebuilt"] is False

    trial = next_trial(client)
    record = client.post(
        "/api/trial/outcome", json={"trial_id": trial, "outcome": "EYE_ERROR"}
    ).json()
    assert record["accepted"] is False


def test_changing_the_ordering_rebuilds_the_bag(client: TestClient):
    arm(client)
    result = client.patch("/api/config", json={"ordering": "descending"}).json()
    assert result["changed"] == ["ordering"]
    assert result["bag_rebuilt"] is True

    state = client.get("/api/state").json()
    # Descending is certain about what comes next, and it is the last type.
    assert [row["p_next"] for row in state["counters"]] == [0.0, 1.0]


def test_every_ordering_is_accepted_on_the_wire(client: TestClient):
    arm(client)
    for ordering in Ordering:
        response = client.patch("/api/config", json={"ordering": ordering.value})
        assert response.status_code == 200, ordering
        assert response.json()["config"]["ordering"] == ordering.value


def test_an_arm_time_setting_is_refused_while_running(client: TestClient):
    arm(client)
    response = client.patch("/api/config", json={"extend_trial_type_number": True})
    assert response.status_code == 400
    assert "cannot change while the session is running" in response.json()["detail"]


def test_an_arm_time_setting_is_allowed_before_arming(client: TestClient):
    result = client.patch("/api/config", json={"extend_trial_type_number": True}).json()
    assert result["changed"] == ["extend_trial_type_number"]
    state = arm(client)
    assert state["config"]["extend_trial_type_number"] is True


def test_stop_after_trials_is_cleared_with_a_zero(client: TestClient):
    client.patch("/api/config", json={"stop_after_trials": 10})
    assert client.get("/api/config").json()["stop_after_trials"] == 10
    client.patch("/api/config", json={"stop_after_trials": 0})
    assert client.get("/api/config").json()["stop_after_trials"] is None


def test_the_stop_rule_ends_the_session(client: TestClient):
    client.patch("/api/config", json={"stop_after_trials": 12, "stop_criterion": "all_trials"})
    arm(client)
    result = client.post("/api/debug/step", json={"trials": 100}).json()
    assert result["stopped"] is True
    assert result["trials"] == 12
    assert "12 all trials counted" in result["stop_reason"]


def test_an_unknown_config_field_is_refused_by_name(client: TestClient):
    response = client.patch("/api/config", json={"rounds_of_applause": 3})
    assert response.status_code == 422
    assert "rounds_of_applause" in response.text


def test_resetting_counters_clears_the_tallies_but_not_the_bag(client: TestClient):
    arm(client)
    client.post("/api/debug/step", json={"trials": 10})
    before = client.get("/api/state").json()
    state = client.post("/api/config/reset-counters").json()
    assert state["totals"]["total"] == 0
    assert state["trials_remaining"] == before["trials_remaining"]


# -- sets -----------------------------------------------------------------------


def test_the_sets_listing_shows_the_chain_and_which_is_active(client: TestClient):
    body = client.get("/api/sets").json()
    assert [s["name"] for s in body["sets"]] == ["easy", "hard"]
    assert body["active"] == "easy"
    assert body["chain_problem"] is None
    assert body["sets"][0]["switch_rule"]["target"] == "hard"
    assert body["sets"][0]["trials_per_round"] == 4


def test_a_broken_switch_chain_is_reported_before_anybody_starts(client: TestClient):
    body = client.put(
        "/api/sets/hard",
        json={
            "name": "hard",
            "trial_types": [{"name": "hard_a", "trials_per_round": 1}],
            "switch_rule": {"enabled": True, "criterion": "hits", "count": 3, "target": "gone"},
        },
    ).json()
    assert "not in the store" in body["chain_problem"]

    response = client.post("/api/session/arm")
    assert response.status_code == 400
    assert "unusable" in response.json()["detail"]


def test_a_set_can_be_loaded_by_hand(client: TestClient):
    arm(client)
    state = client.post("/api/sets/hard/load").json()
    assert state["set_name"] == "hard"
    assert [row["name"] for row in state["counters"]] == ["hard_a", "hard_b"]
    # A set that has just been loaded starts its block from nothing.
    assert state["set_progress"]["accepted_trials"] == 0


def test_the_loaded_set_cannot_be_deleted(client: TestClient):
    response = client.delete("/api/sets/easy")
    assert response.status_code == 409
    assert "load another first" in response.json()["detail"]


def test_a_set_is_replaced_in_place_keeping_its_number(client: TestClient):
    body = client.put(
        "/api/sets/easy",
        json={
            "name": "easy",
            "trial_types": [
                {"name": "easy_a", "trials_per_round": 5, "reward_ms": 200},
                {"name": "easy_b", "trials_per_round": 1},
            ],
            "switch_rule": {"enabled": False},
        },
    ).json()
    easy = next(s for s in body["sets"] if s["name"] == "easy")
    assert easy["set_number"] == 1
    assert easy["trials_per_round"] == 6


def test_a_graph_name_survives_the_round_trip(client: TestClient):
    # The graph is named on the wire, never indexed, and the counters table is
    # where the UI reads it back.
    arm(client)
    client.put(
        "/api/sets/easy",
        json={
            "name": "easy",
            "trial_types": [
                {"name": "easy_a", "trials_per_round": 1, "statemachine_graph": "detection"},
                {
                    "name": "easy_b",
                    "trials_per_round": 1,
                    "statemachine_graph": "discrimination",
                },
            ],
            "switch_rule": {"enabled": False},
        },
    )
    state = client.get("/api/state").json()
    assert [row["statemachine_graph"] for row in state["counters"]] == [
        "detection",
        "discrimination",
    ]

    spec = client.post("/api/trial/next").json()
    assert spec["statemachine_graph"] in {"detection", "discrimination"}


def test_the_path_and_the_body_have_to_agree_about_the_name(client: TestClient):
    response = client.put("/api/sets/easy", json={"name": "hard", "trial_types": []})
    assert response.status_code == 400
    assert "renaming a set is a delete and a put" in response.json()["detail"]


def test_the_active_set_may_not_be_emptied_mid_session(client: TestClient):
    arm(client)
    response = client.put(
        "/api/sets/easy",
        json={"name": "easy", "trial_types": [{"name": "easy_a", "trials_per_round": 0}]},
    )
    assert response.status_code == 400
    assert "a round would be empty" in response.json()["detail"]


# -- policy ---------------------------------------------------------------------


GOOD_POLICY = """
from triald import Policy


class AlwaysFirst(Policy):
    def select_trial(self, state):
        return 0

    def snapshot(self):
        return {"level": 3}
"""


def test_a_policy_is_checked_before_it_is_loaded(client: TestClient):
    result = client.post(
        "/api/policy/check", json={"name": "always_first", "source": GOOD_POLICY}
    ).json()
    assert result["ok"] is True
    assert result["class_name"] == "AlwaysFirst"
    assert len(result["sha256"]) == 64
    assert result["trials_run"] > 0


def test_a_syntax_error_comes_back_with_a_line_number(client: TestClient):
    result = client.post(
        "/api/policy/check", json={"name": "broken", "source": "def oops(:\n    pass\n"}
    ).json()
    assert result["ok"] is False
    assert result["diagnostics"][0]["line"] == 1


def test_a_policy_that_raises_is_reported_rather_than_loaded(client: TestClient):
    source = "from triald import Policy\n\n\nclass Boom(Policy):\n    def select_trial(self, s):\n        raise RuntimeError('no')\n"
    check = client.post("/api/policy/check", json={"name": "boom", "source": source}).json()
    assert check["ok"] is False
    assert "select_trial" in check["diagnostics"][0]["message"]

    response = client.put("/api/policy", json={"name": "boom", "source": source})
    assert response.status_code == 400
    assert client.get("/api/policy").json()["origin"] == "default"


def test_a_loaded_policy_drives_the_selection(client: TestClient, tmp_path):
    client.app.state.service.policy_dir = tmp_path
    info = client.put(
        "/api/policy", json={"name": "always_first", "source": GOOD_POLICY}
    ).json()
    assert info["class_name"] == "AlwaysFirst"
    assert info["origin"] == "uploaded"
    assert info["state"] == {"level": 3}

    arm(client)
    result = client.post("/api/debug/step", json={"trials": 12}).json()
    counters = result["state"]["counters"]
    assert counters[0]["total"] == 12
    assert counters[1]["total"] == 0


def test_a_policy_cannot_be_swapped_mid_session(client: TestClient):
    arm(client)
    response = client.put("/api/policy", json={"name": "p", "source": GOOD_POLICY})
    assert response.status_code == 409
    assert "stop it before loading" in response.json()["detail"]


# -- the stream -----------------------------------------------------------------


def test_the_stream_opens_with_the_current_state_and_pushes_changes(client: TestClient):
    with client.websocket_connect("/api/stream") as socket:
        first = socket.receive_json()
        assert first["kind"] == "state"
        assert first["sequence"] == 0
        assert first["state"]["running"] is False

        client.post("/api/session/arm")
        frame = socket.receive_json()
        assert frame["sequence"] >= 1
        assert frame["state"]["running"] is True


# -- the wire shape -------------------------------------------------------------


def test_the_wire_and_the_record_carry_the_trial_identically(service: SessionService):
    """A `TrialRecordModel` must serialise to the `trials.jsonl` line exactly.

    They are the same trial written twice, so if this ever fails it is a
    divergence between the record format and the API - not a test to relax.
    """
    service.arm()
    service.step(5)
    record = service.session.state().history[-1]

    from_wire = sc.TrialRecordModel.of(record).model_dump(mode="json")
    from_record = record.as_dict()

    # Pydantic writes an aware datetime as ...+00:00 and isoformat() agrees, so
    # the two are comparable without normalising anything.
    assert from_wire == from_record


def test_every_ordering_and_criterion_reaches_the_openapi_document(client: TestClient):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert set(schemas["Ordering"]["enum"]) == {o.value for o in Ordering}
    assert set(schemas["TrialCountCriterion"]["enum"]) == {c.value for c in TrialCountCriterion}


def test_the_web_ui_is_served_from_the_daemon(client: TestClient):
    page = client.get("/")
    assert page.status_code == 200
    assert "triald" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
