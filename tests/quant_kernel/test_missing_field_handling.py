from __future__ import annotations

from app.quant_kernel.scoring import score_track


def test_missing_dimension_sets_unavailable_and_reason_code() -> None:
    track_config = {
        "group_weights": {"g1": 1.0},
        "dimension_groups": {"g1": ["a", "b"]},
        "dimension_weights": {"a": 1.0, "b": 1.0},
    }
    scored = score_track(
        track_name="context",
        track_config=track_config,
        raw_dimensions={"a": {"score": 0.5, "available": True, "reason": "ok"}},
    )
    dim_by_id = {row["id"]: row for row in scored["dimensions"]}
    assert dim_by_id["b"]["available"] is False
    assert dim_by_id["b"]["reason"] == "missing_field"


def test_invalid_score_sets_invalid_value_reason_and_zero_score() -> None:
    track_config = {
        "group_weights": {"g1": 1.0},
        "dimension_groups": {"g1": ["a"]},
        "dimension_weights": {"a": 1.0},
    }
    scored = score_track(
        track_name="context",
        track_config=track_config,
        raw_dimensions={"a": {"score": "NaN", "available": True, "reason": "ok"}},
    )
    row = scored["dimensions"][0]
    assert row["available"] is False
    assert row["score"] == 0.0
    assert row["reason"] == "invalid_value"


def test_group_and_track_marked_unavailable_when_all_dimensions_missing() -> None:
    track_config = {
        "group_weights": {"g1": 1.0},
        "dimension_groups": {"g1": ["a"]},
        "dimension_weights": {"a": 1.0},
    }
    scored = score_track(track_name="context", track_config=track_config, raw_dimensions={})
    assert scored["groups"][0]["available"] is False
    assert scored["groups"][0]["coverage"] == 0.0
    assert scored["track"]["track_unavailable"] is True
    assert scored["track"]["score"] == 0.0
    assert scored["track"]["confidence"] == 0.0

