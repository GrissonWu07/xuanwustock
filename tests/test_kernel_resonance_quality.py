from app.quant_kernel.config import QuantKernelConfig


def test_resonance_quality_defaults_are_profile_specific():
    cfg = QuantKernelConfig.default()
    policy = cfg.dual_track.resonance_quality_policy

    assert policy["aggressive"]["weights"] == {
        "tech_edge": 0.22,
        "context_edge": 0.18,
        "trend_structure": 0.28,
        "confirmation": 0.16,
        "volume": 0.16,
    }
    assert policy["stable"]["weights"]["context_edge"] == 0.20
    assert policy["conservative"]["weights"]["confirmation"] == 0.20

    assert policy["aggressive"]["position_ranges"]["resonance_full"] == {"min": 0.45, "max": 0.60}
    assert policy["stable"]["position_ranges"]["resonance_full"] == {"min": 0.36, "max": 0.50}
    assert policy["conservative"]["position_ranges"]["resonance_full"] == {"min": 0.28, "max": 0.40}
    assert policy["aggressive"]["position_ranges"]["resonance_standard"] == {"min": 0.12, "max": 0.45}

