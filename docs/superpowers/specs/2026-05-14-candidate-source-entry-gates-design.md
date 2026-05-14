# Candidate Source Entry Gates

## Goal

Discovery and research outputs can create candidate events for the quant universe, but the source name itself must not increase a stock's score. This spec defines how source-specific recommendation events are scored, gated, persisted, and reused by live quant and live quant drill.

## Terms

- `source_type`: event origin such as `low_price`, `main_force`, `research`, `ai`, `growth`, `valuation`, `small_cap`, or `manual`. The source name is metadata only.
- `event_score`: the recommendation strength emitted by one discovery/research event. Existing DB field: `source_score`.
- `evidence_confidence`: the reliability of the event evidence. Existing DB field: `confidence`.
- `candidate_score`: lifecycle-level aggregate score used for trial promotion and reactivation.
- `entry_gate`: source-specific gate result persisted under candidate event payload/evidence.

## Non-Negotiable Rules

1. `source_type` does not add points.
2. Multiple sources do not add points.
3. `source_type` selects the scoring formula and entry gate.
4. AI/research cannot auto-enter quant without technical confirmation.
5. Low-price events must prove trend repair before auto-entry.
6. Cooling stocks cannot be restored to `trial` directly by a candidate event; they require cooling review.
7. Live quant drill and live quant use the same gate semantics.

## Common Gate

When market evidence is available, the common gate evaluates:

- valid price,
- liquidity amount against profile threshold,
- non-persistent downtrend,
- tradability evidence when present.

Default liquidity thresholds:

| Profile | Min amount |
| --- | ---: |
| aggressive | 30,000,000 |
| stable | 50,000,000 |
| conservative | 80,000,000 |

Missing market evidence is tolerated for legacy generic events, but strict source families such as `low_price` and `research/ai` must either provide enough evidence or remain non-auto-entry.

## Source Gates

### Low Price

Low-price events are high-noise. A high-score low-price event must pass:

- `event_score` and `evidence_confidence` thresholds by profile,
- price reclaimed MA20 with MA20 non-falling, or MA5 >= MA10 >= MA20,
- RSI not in a hot rebound tail,
- volume ratio not weak when provided,
- liquidity gate when amount is provided.

Thresholds:

| Profile | event_score | confidence |
| --- | ---: | ---: |
| aggressive | 0.72 | 0.68 |
| stable | 0.78 | 0.72 |
| conservative | 0.84 | 0.78 |

Primary reason codes:

- `low_price_below_falling_ma20`
- `low_price_trend_not_confirmed`
- `low_price_liquidity_weak`
- `low_price_rebound_tail_risk`

### Research / AI

Research and AI events are recommendations, not trading permission. High-score events require technical confirmation:

- MA5 >= MA10 >= MA20,
- price above MA20,
- MA20 rising,
- MACD positive,
- retest confirmation if supplied.

Thresholds:

| Profile | event_score | confidence | Min confirmations |
| --- | ---: | ---: | ---: |
| aggressive | 0.75 | 0.72 | 1 |
| stable | 0.80 | 0.76 | 2 |
| conservative | 0.86 | 0.82 | 3 |

Events without score/confidence or without enough confirmation become `recommended_only` with reason `ai_requires_technical_confirmation`.

### Main Force / Growth / Valuation

These sources use the common gate when evidence is available. Missing evidence is tolerated for legacy generic ingestion, but future source-specific implementations should add persistence, trend, and liquidity evidence.

### Small Cap

Small-cap source uses common gate with 1.5x liquidity threshold.

### Manual

Manual events represent user intent. They may enter `trial`, but BUY still depends on normal signal, lifecycle, and execution risk gates.

## Data Contract

Candidate event `payload_json` must persist:

```json
{
  "entry_gate": {
    "passed": false,
    "result": "eligible_blocked",
    "status": "blocked",
    "reason_code": "low_price_below_falling_ma20",
    "reason_codes": ["low_price_below_falling_ma20"],
    "common_gate": {"passed": true},
    "source_gate": {"passed": false}
  }
}
```

Live quant drill persists the same gate under `evidence_json.lifecycle_evaluation.entry_gate` for each `sim_run_candidate_events` row.

## UI Semantics

Discovery/research rows should show:

- `eligible`: ready for confirm/manual action,
- `already_in_quant`: already in active quant lifecycle,
- `recommended_only`: useful recommendation, no automatic quant entry,
- `blocked`: entry gate blocked,
- `rejected`: invalid data or untradable.

The UI should display the gate `reason_code` as the blocking reason.

## Validation

Required regression coverage:

- high-score low-price event below falling MA20 stays inactive and is stored as `blocked`,
- high-score research event without technical confirmation stays inactive and is stored as `recommended_only`,
- source identity and source count still do not change `candidate_score`,
- live quant drill candidate events persist entry-gate diagnostics,
- existing quant universe lifecycle and drill flows continue to pass.
