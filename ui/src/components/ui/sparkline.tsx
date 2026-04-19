import { useState } from "react";
import type { ChartPoint } from "../../lib/page-models";

type SparklineProps = {
  points: ChartPoint[];
  height?: number;
};

const MAX_LABELS = 4;

const formatPrice = (value: number) => {
  if (!Number.isFinite(value)) return "--";
  if (Math.abs(value) >= 1000) return value.toFixed(1);
  return value.toFixed(2);
};

const formatSigned = (value: number) => {
  if (!Number.isFinite(value)) return "--";
  const text = formatPrice(Math.abs(value));
  return value >= 0 ? `+${text}` : `-${text}`;
};

const formatPct = (value: number) => {
  if (!Number.isFinite(value)) return "--";
  const text = Math.abs(value).toFixed(2);
  return value >= 0 ? `+${text}%` : `-${text}%`;
};

const formatLabel = (label: string) => {
  const text = label.trim();
  if (!text) return "";
  const isoDateMatch = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoDateMatch) {
    return `${isoDateMatch[2]}-${isoDateMatch[3]}`;
  }
  if (text.length > 8) {
    return text.slice(0, 8);
  }
  return text;
};

const buildVisibleLabels = (points: ChartPoint[]) => {
  if (points.length <= MAX_LABELS) {
    return points.map((point, index) => ({ index, label: formatLabel(point.label) }));
  }

  const lastIndex = points.length - 1;
  const labels = new Map<number, string>();
  for (let slot = 0; slot < MAX_LABELS; slot += 1) {
    const ratio = slot / (MAX_LABELS - 1);
    const index = Math.round(lastIndex * ratio);
    labels.set(index, points[index].label);
  }
  return Array.from(labels.entries()).map(([index, label]) => ({ index, label: formatLabel(label) }));
};

export function Sparkline({ points, height = 88 }: SparklineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (points.length < 2) {
    return (
      <div className="empty-note" style={{ minHeight: height }}>
        暂无曲线数据
      </div>
    );
  }

  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const latest = values[values.length - 1];
  const padding = 8;
  const width = Math.max(240, (points.length - 1) * 24);
  const range = max - min || 1;
  const step = width / (points.length - 1);
  const visibleLabels = buildVisibleLabels(points);
  const pointCoords = points.map((point, index) => {
      const x = index * step;
      const y = padding + (1 - (point.value - min) / range) * (height - padding * 2);
      return { x, y };
    });
  const coords = pointCoords.map((point) => `${point.x},${point.y}`).join(" ");
  const latestX = pointCoords[pointCoords.length - 1].x;
  const latestY = pointCoords[pointCoords.length - 1].y;
  const activeIndex = hoveredIndex ?? points.length - 1;
  const activePoint = points[activeIndex] ?? points[points.length - 1];
  const activeCoord = pointCoords[activeIndex] ?? pointCoords[pointCoords.length - 1];
  const firstValue = values[0];
  const activePnl = activePoint.value - firstValue;
  const activePnlPct = firstValue !== 0 ? (activePnl / firstValue) * 100 : 0;
  const topGridY = padding;
  const midGridY = padding + (height - padding * 2) * 0.5;
  const bottomGridY = height - padding;

  return (
    <div className="sparkline">
      <div className="sparkline__meta" aria-live="polite">
        <span>{`时间 ${activePoint.label || "--"}`}</span>
        <span>{`权益 ${formatPrice(activePoint.value)}`}</span>
        <span>{`区间盈亏 ${formatSigned(activePnl)} (${formatPct(activePnlPct)})`}</span>
        <span>{`最高 ${formatPrice(max)} / 最低 ${formatPrice(min)}`}</span>
      </div>
      <div className="sparkline__chart" style={{ height }} onMouseLeave={() => setHoveredIndex(null)}>
        <svg
          className="sparkline__svg"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="曲线"
        >
          <line x1={0} y1={topGridY} x2={width} y2={topGridY} className="sparkline__grid" />
          <line x1={0} y1={midGridY} x2={width} y2={midGridY} className="sparkline__grid" />
          <line x1={0} y1={bottomGridY} x2={width} y2={bottomGridY} className="sparkline__grid" />
          <polyline points={coords} className="sparkline__line" vectorEffect="non-scaling-stroke" />
          <line x1={activeCoord.x} y1={topGridY} x2={activeCoord.x} y2={bottomGridY} className="sparkline__crosshair" />
          {pointCoords.map((point, index) => {
            const pointValue = points[index].value;
            const pointPnl = pointValue - firstValue;
            const pointPnlPct = firstValue !== 0 ? (pointPnl / firstValue) * 100 : 0;
            return (
              <circle
                key={`${points[index].label}-${index}`}
                cx={point.x}
                cy={point.y}
                r={6}
                className="sparkline__point-hit"
                onMouseEnter={() => setHoveredIndex(index)}
                onFocus={() => setHoveredIndex(index)}
                onBlur={() => setHoveredIndex(null)}
              >
                <title>{`${points[index].label} | 权益 ${formatPrice(pointValue)} | 区间盈亏 ${formatSigned(pointPnl)} (${formatPct(pointPnlPct)})`}</title>
              </circle>
            );
          })}
          <circle cx={latestX} cy={latestY} r={3} className="sparkline__dot" />
          <circle cx={activeCoord.x} cy={activeCoord.y} r={3.5} className="sparkline__point-active" />
          <text x={width - 2} y={Math.max(padding + 10, latestY - 6)} textAnchor="end" className="sparkline__value-tag">
            {formatPrice(latest)}
          </text>
        </svg>
      </div>
      <div className="sparkline__labels">
        {visibleLabels.map((point) => (
          <span key={`${point.index}-${point.label}`}>{point.label}</span>
        ))}
      </div>
    </div>
  );
}
