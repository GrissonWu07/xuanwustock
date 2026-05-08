# Capital Slot Sizing Protocol

## Goal

Replace fixed BUY sizing with a configurable capital-slot allocator. BUY decisions still come from the dual-track fusion gates, but BUY quantity is capped by portfolio slots, signal strength, A-share lot rules, and cash-settlement policy.

## Requirements

1. All capital-slot parameters must have defaults and must be configurable from the UI.
2. A slot is a portfolio budget unit. A lot is still the actual trading and T+1 sellability unit.
3. `capital_slot_min_cash` is the minimum account readiness threshold, not a hard guarantee that every computed slot budget is at least 20,000 CNY. Current implementation uses dynamic equity tiers: accounts up to 100,000 CNY use 2 slots; 100,000-1,000,000 CNY use roughly 100,000 CNY per slot; accounts above 1,000,000 CNY use roughly 200,000 CNY per slot.
4. The effective pool is capped by a configurable max pool value. Current default cap is intentionally very high (`1,000,000,000,000`) so live/replay cash is not artificially capped unless the user configures it.
5. Accounts below the configurable min pool value do not auto-open new positions.
6. A normal BUY can use at most 1 slot. For stocks priced above the high-price threshold, a strong BUY may use up to 2 slots to satisfy one A-share lot.
7. At each live cycle or replay checkpoint, all BUY signals must be ranked by signal strength before execution. Funds are allocated to stronger signals first.
8. SELL proceeds must not be reused by a later BUY in the same execution batch by default. They move into slot settling cash first, then become slot-available at the next execution batch.
9. Slot ledgers must be persisted and synchronized whenever trades occur.
10. Signal details must include sizing evidence: slot budget, slot units, buy budget, quantity, priority, and skip reason when applicable.

## Default Configuration

| Field | Default | Meaning |
|---|---:|---|
| `capital_slot_enabled` | `true` | Enable slot-based sizing for auto execution. |
| `capital_pool_min_cash` | `20000` | Minimum account equity required to auto-open new positions. |
| `capital_pool_max_cash` | `1000000000000` | Maximum equity considered by the allocator. |
| `capital_slot_min_cash` | `20000` | Minimum pool readiness threshold used together with `capital_pool_min_cash`. |
| `capital_max_slots` | `25` | Hard cap on slot count to avoid too many tiny bookkeeping units. |
| `capital_min_buy_slot_fraction` | `0.25` | Weak BUY minimum budget, as a fraction of one slot. |
| `capital_full_buy_edge` | `0.25` | Fusion score edge needed to reach a full 1-slot BUY. |
| `capital_confidence_weight` | `0.35` | Weight of fusion confidence in slot fraction. |
| `capital_high_price_threshold` | `100` | Price threshold for allowing high-price special handling. |
| `capital_high_price_max_slot_units` | `2.0` | Max slot units for strong high-price BUY. |
| `capital_sell_cash_reuse_policy` | `next_batch` | SELL proceeds become slot-available at the next batch. |

## Slot Count

```text
effective_pool_cash = min(total_equity, capital_pool_max_cash)
required_pool_cash = max(capital_pool_min_cash, capital_slot_min_cash)

if effective_pool_cash < required_pool_cash:
  auto BUY is blocked

if effective_pool_cash <= 100000:
  raw_slot_count = 2
else if effective_pool_cash > 1000000:
  raw_slot_count = ceil(effective_pool_cash / 200000)
else:
  raw_slot_count = ceil(effective_pool_cash / 100000)

slot_count = min(max(raw_slot_count, 1), capital_max_slots)
slot_budget = effective_pool_cash / slot_count
```

Examples:

```text
20,000 -> 2 slots, 10,000 each
50,000 -> 2 slots, 25,000 each
80,000 -> 2 slots, 40,000 each
452,000 -> 5 slots, 90,400 each
1,000,000 -> 10 slots, 100,000 each
1,200,000 -> 6 slots, 200,000 each
```

## BUY Slot Units

The dual-track decision only decides whether the signal is BUY. Sizing then uses fusion strength.

```text
score_edge = fusion_score - buy_threshold
edge_strength = clamp(score_edge / capital_full_buy_edge, 0, 1)
confidence_strength = clamp((fusion_confidence - min_fusion_confidence) / (1 - min_fusion_confidence), 0, 1)
size_strength = (1 - capital_confidence_weight) * edge_strength
              + capital_confidence_weight * confidence_strength

base_slot_units = capital_min_buy_slot_fraction
                + (1 - capital_min_buy_slot_fraction) * size_strength
```

High-price exception:

```text
if price > capital_high_price_threshold
   and one_lot_cost > slot_budget
   and strong BUY:
  slot_units = min(capital_high_price_max_slot_units, max(base_slot_units, one_lot_cost / slot_budget))
else:
  slot_units = min(base_slot_units, 1.0)
```

Strong BUY means `edge_strength >= 0.6` and `fusion_confidence >= min_fusion_confidence`.

Final quantity:

```text
buy_budget = min(slot_budget * slot_units, available_account_cash, available_slot_cash)
quantity = floor(buy_budget / one_lot_cost_with_fee) * 100
```

## BUY Priority

At each execution batch:

1. Execute SELL signals first to reduce risk.
2. Mark SELL proceeds as slot settling cash.
3. Rank BUY signals by priority.
4. Execute stronger BUY signals first.
5. Skip weaker BUY signals when account cash or slot availability is insufficient.

Priority:

```text
priority = 0.50 * edge_strength
         + 0.25 * fusion_confidence
         + 0.15 * track_alignment
         + 0.10 * liquidity_score
         - risk_penalty
```

Fallback when structured fusion data is missing:

```text
priority = confidence / 100
```

## Slot-Lot Ledger

`sim_position_lots` remains the authoritative position ledger. Each buy creates one lot with its own entry date and unlock date.

New slot ledger:

```text
sim_capital_slots:
  slot_index
  budget_cash
  available_cash
  occupied_cash
  settling_cash

sim_lot_slot_allocations:
  position_lot_db_id
  slot_index
  stock_code
  allocated_cash
  allocated_quantity
  released_cash
  status
```

On BUY:

1. Reserve slot budget.
2. Create position lot.
3. Attach the lot to one or more slots.
4. Decrease slot available cash and increase occupied cash.

On SELL:

1. Consume sellable lots under A-share T+1 rules.
2. Release the related slot allocations proportionally.
3. Move proceeds into `settling_cash`.
4. At the next batch, move settling cash to available cash.

## UI

The live simulation configuration card must expose all slot settings with defaults:

- Slot sizing enabled
- Pool min cash
- Pool max cash
- Slot min cash
- Max slots
- Min BUY slot fraction
- Full BUY score edge
- Confidence weight
- High-price threshold
- High-price max slot units
- SELL cash reuse policy

History replay uses the same persisted config unless overridden by run payload in the future.

## Review Protocol

Each implementation stage must run three reviews:

1. Requirement review: compare code against the ten requirements above.
2. Spec/code review: verify config names, default values, DB fields, API payloads, and UI fields match this document.
3. Behavior review: run focused tests for slot count, high-price handling, BUY ranking, slot-lot allocation, and sell settlement.
