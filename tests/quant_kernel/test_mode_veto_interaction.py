from __future__ import annotations

from app.quant_kernel.decision_engine import resolve_v23_final_action


def test_hard_veto_applies_first_for_all_modes() -> None:
    vetoes = [{"id": "risk_stop", "priority": 1, "action": "SELL", "reason": "stop_loss"}]
    for mode in ("rule_only", "weighted_only", "hybrid"):
        resolved = resolve_v23_final_action(
            mode=mode,
            core_rule_action="BUY",
            weighted_action_raw="BUY",
            fusion_score=0.9,
            sell_precedence_gate=-0.5,
            vetoes=vetoes,
            legacy_rule_action="BUY",
        )
        assert resolved["final_action"] == "SELL"
        assert resolved["matched_branch"] == "veto_first"
        assert resolved["veto_id"] == "risk_stop"
        assert resolved["veto_trigger_type"] == "risk_stop"


def test_rule_only_uses_legacy_action_when_no_veto() -> None:
    resolved = resolve_v23_final_action(
        mode="rule_only",
        core_rule_action="SELL",
        weighted_action_raw="BUY",
        fusion_score=0.7,
        sell_precedence_gate=-0.5,
        vetoes=[],
        legacy_rule_action="HOLD",
    )
    assert resolved["final_action"] == "HOLD"
    assert resolved["matched_branch"] == "rule_only"
