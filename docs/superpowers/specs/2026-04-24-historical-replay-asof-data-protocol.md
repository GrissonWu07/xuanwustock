# Historical Replay As-Of Data Protocol

**Date:** 2026-04-24

**Goal**

Ensure every historical replay decision is generated only from data that was available at the replay checkpoint, with explicit audit records for every dynamic environment component that was used or omitted.

## Problem

Historical replay currently uses checkpoint-bounded market bars for technical indicators, but AI dynamic strategy evaluation can read current market/news/AI context. This creates look-ahead bias: a replay checkpoint in 2025 can be affected by data generated in 2026.

## Definitions

- `checkpoint`: the historical decision time being replayed.
- `as_of`: the maximum timestamp visible to a replay decision. In replay, `as_of == checkpoint`.
- `lookback_window`: `[as_of - lookback_hours, as_of]`.
- `point_in_time_safe`: data with an event/publish/decision timestamp inside `lookback_window`.
- `current_fallback`: any data fetched by "latest", `datetime.now()`, realtime quote, or current cache TTL when no historical as-of query exists.

## Non-Negotiable Rules

1. Replay decisions must not use data with timestamp greater than `checkpoint`.
2. Replay decisions must not use current fallback data for market, news, AI, sector, or sentiment context.
3. Replay technical indicators must be calculated from bars where `bar_time <= checkpoint`.
4. Replay dynamic strategy components must use `as_of=checkpoint`.
5. If an environment component cannot provide point-in-time data, it must be omitted, not approximated with current data.
6. Every used or omitted dynamic component must be persisted in `strategy_profile.dynamic_strategy`.
7. Signal detail must display `as_of`, used components, and omitted components so the replay can be audited.
8. Strict daily replay must not default to current `qfq`-adjusted history. Execution prices use unadjusted prices; adjusted indicators require an explicit mode.

## Component Visibility Matrix

| Component | Live/Realtime | Historical Replay |
| --- | --- | --- |
| Stock OHLCV / technical indicators | Latest or cached current bars allowed | Only bars `<= checkpoint` |
| Index / market overview | Latest allowed | Only historical record with timestamp `<= checkpoint` |
| Sector news | Latest allowed | Only `news_date/created_at <= checkpoint` |
| News flow sentiment / AI analysis | Latest allowed | Only `fetch_time/created_at <= checkpoint` |
| AI monitor decisions | Latest allowed | Only `decision_time/created_at <= checkpoint` |
| Missing timestamp | Allowed only in live fallback | Omit in replay |
| No historical query support | Fallback allowed in live | Omit in replay and audit |

## Required Audit Shape

`strategy_profile.dynamic_strategy` must include:

```json
{
  "mode": "hybrid",
  "enabled": true,
  "as_of": "2025-08-29 13:30:00",
  "lookback_hours": 48,
  "score": 0.0,
  "confidence": 0.0,
  "overlay_regime": "neutral",
  "components": [
    {
      "key": "ai",
      "score": 0.25,
      "confidence": 0.8,
      "as_of": "2025-08-29 13:00:00",
      "reason": "ai_decisions(3)"
    }
  ],
  "omitted_components": [
    {
      "key": "news",
      "reason": "no_historical_asof_data",
      "as_of": "2025-08-29 13:30:00"
    }
  ],
  "adjustments": []
}
```

## Implementation Requirements

### Dynamic Strategy

- `DynamicStrategyController.resolve_binding(...)` must accept `as_of: datetime | str | None`.
- `as_of=None` keeps live/realtime behavior.
- `as_of != None` enables replay-safe mode.
- All component builders must evaluate records against `lookback_window`.
- In replay-safe mode, component builders must prefer local as-of queries over latest queries:
  - `SectorStrategyDatabase.get_raw_data_as_of(...)` for market overview.
  - `SectorStrategyDatabase.get_news_data_as_of(...)` for sector news.
  - `NewsFlowDatabase.get_snapshot_as_of(...)` for flow snapshots.
  - `NewsFlowDatabase.get_sentiment_as_of(...)` for sentiment records.
  - `NewsFlowDatabase.get_ai_analysis_as_of(...)` for AI news analysis.
- Records without timestamps are invalid in replay-safe mode.
- Records after `as_of` are invalid in replay-safe mode.
- Current fallback sources must be omitted in replay-safe mode.

### Replay Service

- `_run_checkpoint(...)` must pass `as_of=checkpoint` to dynamic strategy resolution for candidates and positions.
- Each replay signal must persist the actual market snapshot used for the decision.
- Replay detail enrichment is display-only and must not mutate historical decisions.

### Signal Detail

- Decision parameter details must include:
  - `AI动态as_of`
  - `AI动态使用组件.<component>`
  - `AI动态省略组件.<component>`
- Used component rows show `score/confidence/as_of`.
- Omitted component rows show reason and replay `as_of`.

### Daily Adjustment Mode

- Replay history loading must support a strict adjustment mode.
- Default strict mode for replay daily bars is unadjusted prices.
- Current `qfq` may remain available only as an explicit non-strict mode and must be labeled in run metadata.

## Acceptance Tests

1. A replay checkpoint in 2025 with only 2026 AI decisions must produce zero AI dynamic component contribution and include `omitted_components=[{"key":"ai","reason":"no_historical_asof_data"}]`.
2. A replay checkpoint must persist `dynamic_strategy.as_of == checkpoint`.
3. A replay checkpoint with a historical AI decision inside the lookback window may use it and must not use decisions after checkpoint.
4. Signal detail must expose used/omitted dynamic components.
5. Daily replay strict mode must call the daily history source with no adjustment by default.
6. Existing live dynamic strategy behavior must remain unchanged when `as_of` is omitted.
7. Replay-safe dynamic strategy must not call latest market/news/sentiment APIs when matching as-of APIs exist.
8. Local as-of DB queries must return records inside the replay window and ignore records after checkpoint.

## Out Of Scope

- Building a full historical news ingestion pipeline in this change.
- Recomputing past news sentiment with an LLM during replay.
- Broker/live execution.
