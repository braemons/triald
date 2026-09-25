# SPDX-License-Identifier: AGPL-3.0-or-later
"""The session config file: what it reads, what it refuses, and where it says so."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from triald.cli import demo_experiment
from triald.counters import TrialCountCriterion
from triald.outcomes import AcceptancePolicy
from triald.selection import Ordering
from triald.session import SessionConfig
from triald.session_config_file import (
    SessionConfigFileError,
    read_session_config_file,
    session_config_from_document,
    session_config_to_document,
    write_session_config_file,
)
from triald.trialtypes import SwitchRule, TrialType

REPOSITORY = Path(__file__).resolve().parents[2]
EXAMPLE = REPOSITORY / "examples" / "session-config.json"
SCHEMA = REPOSITORY / "docs" / "reference" / "session-config.schema.json"


def smallest() -> dict:
    return {
        "settings": {"initial_set": "a"},
        "sets": [{"name": "a", "trial_types": [{"name": "t", "trials_per_round": 1}]}],
    }


def refusal(document) -> str:
    with pytest.raises(SessionConfigFileError) as caught:
        session_config_from_document(document)
    return str(caught.value)


def test_the_example_is_the_demo_experiment():
    # The committed example is what the daemon runs with no session config, so
    # a person has a file to start from that is known to work.
    store, config = read_session_config_file(EXAMPLE)
    demo_store, demo_config = demo_experiment()
    assert config == demo_config
    assert store.sets() == demo_store.sets()


def test_a_file_says_only_what_differs():
    store, config = session_config_from_document(smallest())
    assert config == SessionConfig(initial_set="a")
    assert store.get("a").trial_types == [TrialType(name="t", trials_per_round=1)]
    assert store.get("a").switch_rule == SwitchRule()


def test_what_is_written_reads_back_the_same(tmp_path):
    store, config = demo_experiment()
    config.ordering = Ordering.ASCENDING
    config.stop_after_trials = 300
    config.stop_criterion = TrialCountCriterion.HITS
    config.acceptance = AcceptancePolicy(late=False)
    store.get("fixation").trial_types[0].params = {"contrast": 0.25, "side": "left"}
    path = tmp_path / "experiment.json"

    write_session_config_file(path, store, config)
    read_store, read_config = read_session_config_file(path)

    assert read_config == config
    assert read_store.sets() == store.sets()


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (
            lambda d: d["sets"][0]["trial_types"][0].update(reward_msec=100),
            "sets[0].trial_types[0]: unknown key 'reward_msec'",
        ),
        (lambda d: d["settings"].update(rounds=-1), "settings.rounds: an integer, at least 0"),
        (lambda d: d["settings"].update(rounds=True), "settings.rounds: an integer"),
        (lambda d: d["settings"].update(ordering="shuffled"), "settings.ordering: one of"),
        (
            lambda d: d["settings"].update(initial_set="b"),
            "settings.initial_set: no set named 'b'",
        ),
        (
            lambda d: d["settings"].update(acceptance={"late": "no"}),
            "settings.acceptance.late: true or false",
        ),
        (
            lambda d: d["sets"].append({"name": "a", "trial_types": []}),
            "sets[1].name: 'a' is the name of an earlier set too",
        ),
        (
            lambda d: d["sets"][0]["trial_types"].append({"name": "t"}),
            "sets[0].trial_types[1].name: 't' appears twice",
        ),
        (
            lambda d: d["sets"][0].update(
                switch_rule={"enabled": True, "count": 3, "target": "z"}
            ),
            "sets: ",
        ),
        (lambda d: d.pop("sets"), "the document: missing 'sets'"),
        (lambda d: d.update(sets=[]), "sets: a list of at least one"),
    ],
)
def test_a_refusal_names_the_path_to_what_it_is_about(change, says):
    document = smallest()
    change(document)
    assert says in refusal(document)


def test_a_file_that_is_not_json_says_where(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"settings": {"initial_set": "a",}}')
    with pytest.raises(SessionConfigFileError, match=r"broken.json: not JSON: .* line 1"):
        read_session_config_file(path)


def test_a_missing_file_is_a_refusal_not_a_traceback(tmp_path):
    with pytest.raises(SessionConfigFileError, match=r"nowhere\.json"):
        read_session_config_file(tmp_path / "nowhere.json")


def test_the_schema_knows_exactly_the_keys_the_reader_does():
    # The schema is for an editor and the reader is the authority; this is what
    # stops the two drifting apart.
    schema = json.loads(SCHEMA.read_text())
    settings = schema["properties"]["settings"]["properties"]
    set_item = schema["properties"]["sets"]["items"]["properties"]
    trial_type = set_item["trial_types"]["items"]["properties"]

    assert set(settings) == {f.name for f in dataclasses.fields(SessionConfig)}
    assert set(settings["acceptance"]["properties"]) == {
        f.name for f in dataclasses.fields(AcceptancePolicy)
    }
    assert set(trial_type) == {f.name for f in dataclasses.fields(TrialType)}
    assert set(set_item["switch_rule"]["properties"]) == {
        f.name for f in dataclasses.fields(SwitchRule)
    }
    assert set(settings["ordering"]["enum"]) == {m.value for m in Ordering}


def test_the_document_is_plain_json():
    store, config = demo_experiment()
    json.dumps(session_config_to_document(store, config))
