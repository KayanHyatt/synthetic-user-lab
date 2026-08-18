"""config_hash / content_hash: deterministic, order-independent hashing.

M6's reproducibility claims depend on `config_hash` being an honest fingerprint
of a study's configuration — including the research goal, since a study whose
only difference is its research question is a different study.
"""

from __future__ import annotations

from sul.hashing import config_hash, content_hash


def test_config_hash_changes_when_research_goal_changes() -> None:
    base = {"name": "Study 1", "research_goal": "Find pricing confusion", "seed": 42}
    changed = {**base, "research_goal": "Find signup friction"}

    assert config_hash(base) != config_hash(changed)


def test_config_hash_is_stable_for_identical_payloads() -> None:
    payload = {"name": "Study 1", "research_goal": "Find pricing confusion"}
    assert config_hash(payload) == config_hash(dict(payload))


def test_config_hash_is_order_independent() -> None:
    a = {"name": "Study 1", "research_goal": "goal", "seed": 42}
    b = {"seed": 42, "research_goal": "goal", "name": "Study 1"}
    assert config_hash(a) == config_hash(b)


def test_content_hash_changes_with_body() -> None:
    assert content_hash("<p>a</p>") != content_hash("<p>b</p>")


def test_content_hash_is_stable() -> None:
    assert content_hash("same body") == content_hash("same body")
