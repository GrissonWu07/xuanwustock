import { t } from "../../lib/i18n";

const DECISION_KEY_MAP: Record<string, string> = {
  auto: "Decision:auto",
  buy: "Action:BUY",
  sell: "Action:SELL",
  hold: "Action:HOLD",
  context: "Action:CONTEXT",
  dual_track_hold: "Decision:dual_track_hold",
  dual_track_convergence: "Decision:dual_track_convergence",
  dual_track_divergence: "Decision:dual_track_divergence",
  dual_track_buy: "Decision:dual_track_buy",
  dual_track_sell: "Decision:dual_track_sell",
  neutral_hold: "Decision:neutral_hold",
  sell_divergence: "Decision:sell_divergence",
  buy_divergence: "Decision:buy_divergence",
  resonance_full: "Decision:resonance_full",
  resonance_heavy: "Decision:resonance_heavy",
  resonance_moderate: "Decision:resonance_moderate",
  resonance_standard: "Decision:resonance_standard",
  full: "Decision:full",
  heavy: "Decision:heavy",
  moderate: "Decision:moderate",
  light: "Decision:light",
};

const STRATEGY_MODE_MAP: Record<string, string> = {
  auto: "Strategy mode:auto",
  aggressive: "Strategy mode:aggressive",
  neutral: "Strategy mode:neutral",
  defensive: "Strategy mode:defensive",
};

function humanizeCode(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
}

export function localizeDecisionCode(rawValue: string) {
  const value = String(rawValue || "").trim();
  if (!value) {
    return "--";
  }
  const normalized = value.toLowerCase();
  const translationKey = DECISION_KEY_MAP[normalized];
  if (translationKey) {
    return t(translationKey);
  }
  return humanizeCode(value);
}

export function localizeStrategyMode(rawValue: string) {
  const value = String(rawValue || "").trim();
  if (!value) {
    return "--";
  }
  const normalized = value.toLowerCase();
  const translationKey = STRATEGY_MODE_MAP[normalized];
  if (translationKey) {
    return t(translationKey);
  }
  return humanizeCode(value);
}
