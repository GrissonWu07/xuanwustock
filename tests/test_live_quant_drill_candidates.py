from datetime import datetime

from app.quant_sim.live_quant_drill_candidates import (
    CandidateGenerationConfig,
    CandidateSourceAvailability,
    estimate_candidate_generation,
    should_generate_candidates,
    should_skip_candidate_event_due_to_dedup,
    source_availability_for_checkpoint,
)


def test_current_ai_and_current_discover_are_not_historical_sources():
    availability = source_availability_for_checkpoint(
        source_type="current_ai_analysis",
        checkpoint=datetime(2026, 1, 5, 9, 30),
        available_fields={"generated_at": "2026-05-09T00:00:00Z"},
    )
    assert availability == CandidateSourceAvailability.DISABLED

    availability = source_availability_for_checkpoint(
        source_type="current_discover_result",
        checkpoint=datetime(2026, 1, 5, 9, 30),
        available_fields={},
    )
    assert availability == CandidateSourceAvailability.DISABLED


def test_spec_candidate_source_matrix_is_enforced():
    checkpoint = datetime(2026, 1, 5, 9, 30)
    cases = [
        ("low_price", {"ohlcv": True, "price": True, "volume": True}, CandidateSourceAvailability.ENABLED),
        ("small_cap", {"as_of_fundamental": True}, CandidateSourceAvailability.ENABLED),
        ("low_valuation", {"as_of_fundamental": True}, CandidateSourceAvailability.ENABLED),
        ("profit_growth", {"as_of_financial_report": True}, CandidateSourceAvailability.ENABLED),
        ("main_force", {"historical_capital_flow": True}, CandidateSourceAvailability.ENABLED),
        ("historical_research", {"occurred_at": "2026-01-04T10:00:00Z"}, CandidateSourceAvailability.CONDITIONAL),
        ("manual_seed", {}, CandidateSourceAvailability.ENABLED),
        ("small_cap", {"as_of_fundamental": False}, CandidateSourceAvailability.DISABLED),
        ("main_force", {"historical_capital_flow": False}, CandidateSourceAvailability.DISABLED),
    ]

    for source_type, fields, expected in cases:
        assert source_availability_for_checkpoint(
            source_type=source_type,
            checkpoint=checkpoint,
            available_fields=fields,
        ) == expected


def test_daily_first_checkpoint_only_generates_once_per_trading_day():
    config = CandidateGenerationConfig(frequency="daily_first_checkpoint", checkpoint_interval=8)
    checkpoints = [
        datetime(2026, 1, 5, 9, 30),
        datetime(2026, 1, 5, 10, 0),
        datetime(2026, 1, 6, 9, 30),
    ]

    assert should_generate_candidates(config, checkpoints, 0) is True
    assert should_generate_candidates(config, checkpoints, 1) is False
    assert should_generate_candidates(config, checkpoints, 2) is True


def test_every_n_checkpoints_respects_min_interval():
    config = CandidateGenerationConfig(frequency="every_n_checkpoints", checkpoint_interval=3)
    checkpoints = [datetime(2026, 1, 5, 9, 30 + i) for i in range(6)]

    assert [should_generate_candidates(config, checkpoints, i) for i in range(6)] == [
        True,
        False,
        False,
        True,
        False,
        False,
    ]


def test_candidate_generation_estimate_counts_only_generation_checkpoints():
    config = CandidateGenerationConfig(frequency="daily_first_checkpoint", checkpoint_interval=8)
    checkpoints = [
        datetime(2026, 1, 5, 9, 30),
        datetime(2026, 1, 5, 10, 0),
        datetime(2026, 1, 6, 9, 30),
    ]

    estimate = estimate_candidate_generation(
        checkpoints=checkpoints,
        config=config,
        enabled_sources=["low_price", "main_force"],
    )

    assert estimate["estimated_candidate_generation_runs"] == 2
    assert estimate["estimated_strategy_invocations"] == 4
    assert estimate["enabled_candidate_sources"] == ["low_price", "main_force"]


def test_candidate_event_dedup_skips_recent_unconsumed_same_source_event():
    config = CandidateGenerationConfig(candidate_event_dedup_days=5)
    should_skip = should_skip_candidate_event_due_to_dedup(
        config=config,
        stock_code="600519",
        source_type="low_price",
        checkpoint=datetime(2026, 1, 6, 9, 30),
        previous_events=[
            {
                "stock_code": "600519",
                "source_type": "low_price",
                "checkpoint_at": "2026-01-03 09:30:00",
                "status": "new",
            }
        ],
    )
    assert should_skip is True


def test_candidate_event_dedup_allows_consumed_or_old_events():
    config = CandidateGenerationConfig(candidate_event_dedup_days=5)
    checkpoint = datetime(2026, 1, 10, 9, 30)

    assert not should_skip_candidate_event_due_to_dedup(
        config=config,
        stock_code="600519",
        source_type="low_price",
        checkpoint=checkpoint,
        previous_events=[
            {
                "stock_code": "600519",
                "source_type": "low_price",
                "checkpoint_at": "2026-01-08 09:30:00",
                "status": "consumed",
            },
            {
                "stock_code": "600519",
                "source_type": "low_price",
                "checkpoint_at": "2026-01-01 09:30:00",
                "status": "new",
            },
        ],
    )
