import { useState } from 'react'
import { SERIES } from '@/lib/evaluation'

const BAR = 12
const GAP = 2
const LABEL_W = 132
const WIDTH = 560
const ROW_PAD = 14

/** Path of a horizontal bar: square at the baseline, 4px rounded at the data end. */
function barPath(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h / 2)
  if (w <= 0) return ''
  return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`
}

/**
 * Grouped bars for 0–1 metrics: one row per metric, one bar per run (≤ 4, fixed colors).
 * Values are in the hover tooltip and in the table that always accompanies this chart.
 */
export function MetricBars({
  metrics,
  runs,
}: {
  metrics: { key: string; label: string }[]
  runs: { id: string; name: string; values: Record<string, number | null | undefined> }[]
}) {
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null)
  const shown = runs.slice(0, SERIES.length)
  const rowH = shown.length * (BAR + GAP) - GAP + ROW_PAD * 2
  const plotW = WIDTH - LABEL_W - 16
  const height = metrics.length * rowH + 24
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  return (
    <figure className="w-full max-w-[640px]">
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted" aria-label="Legend">
        {shown.map((run, i) => (
          <li key={run.id} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-2.5 rounded-sm" style={{ background: SERIES[i] }} />
            {run.name}
          </li>
        ))}
      </ul>
      {/* Positioned box the size of the plot, so the tooltip can be placed in viewBox percentages. */}
      <div className="relative">
        <svg
          viewBox={`0 0 ${WIDTH} ${height}`}
          className="w-full"
          role="img"
          aria-label={`Metrics for ${shown.map((r) => r.name).join(', ')}; values are in the table below`}
          onPointerLeave={() => setHover(null)}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={LABEL_W + t * plotW} x2={LABEL_W + t * plotW} y1={0} y2={height - 20} stroke="var(--viz-grid)" strokeWidth={1} />
              <text x={LABEL_W + t * plotW} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--text-subtle)">
                {t.toFixed(2).replace(/0$/, '')}
              </text>
            </g>
          ))}
          {metrics.map((metric, m) => {
            const top = m * rowH
            return (
              <g key={metric.key}>
                <text x={LABEL_W - 10} y={top + rowH / 2 + 4} textAnchor="end" fontSize={12} fill="var(--text-muted)">
                  {metric.label}
                </text>
                {shown.map((run, i) => {
                  const value = run.values[metric.key]
                  const y = top + ROW_PAD + i * (BAR + GAP)
                  if (value === null || value === undefined)
                    return (
                      <text key={run.id} x={LABEL_W + 4} y={y + BAR - 2} fontSize={10} fill="var(--text-subtle)">
                        n/a
                      </text>
                    )
                  const w = Math.max(0, Math.min(1, value)) * plotW
                  return (
                    <g key={run.id}>
                      <path d={barPath(LABEL_W, y, w, BAR)} fill={SERIES[i]} />
                      {/* Hit target taller and wider than the mark. */}
                      <rect
                        x={LABEL_W}
                        y={y - GAP}
                        width={Math.max(w, 24)}
                        height={BAR + GAP * 2}
                        fill="transparent"
                        onPointerEnter={() =>
                          setHover({ x: LABEL_W + Math.max(w, 24), y, text: `${run.name} · ${metric.label}: ${value.toFixed(3)}` })
                        }
                      />
                    </g>
                  )
                })}
              </g>
            )
          })}
        </svg>
        {hover && (
          <div
            role="tooltip"
            className="pointer-events-none absolute z-10 ml-2 -translate-y-1/4 whitespace-nowrap rounded-md border border-border bg-surface-elevated px-2 py-1 text-caption text-text shadow-md"
            style={{ left: `${(hover.x / WIDTH) * 100}%`, top: `${(hover.y / height) * 100}%` }}
          >
            {hover.text}
          </div>
        )}
      </div>
    </figure>
  )
}
