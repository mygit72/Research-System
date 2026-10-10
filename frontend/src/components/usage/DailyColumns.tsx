import { useState } from 'react'

const WIDTH = 640
const HEIGHT = 180
const LEFT = 36
const BOTTOM = 22
const TOP = 8

/** Path of a column: square at the baseline, 4px rounded at the top (the data end). */
function columnPath(x: number, y: number, w: number, h: number) {
  if (h <= 0) return ''
  const r = Math.min(4, w / 2, h)
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
}

function niceMax(value: number) {
  if (value <= 4) return 4
  const step = 10 ** Math.floor(Math.log10(value))
  return Math.ceil(value / step) * step
}

/**
 * One series over days (no legend: the heading names it). Every value is also in the table
 * that accompanies the chart; hover shows the exact number.
 */
export function DailyColumns({
  days,
  label,
  format = (v) => String(v),
}: {
  days: { day: string; value: number }[]
  label: string
  format?: (value: number) => string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const max = niceMax(Math.max(0, ...days.map((d) => d.value)))
  const plotW = WIDTH - LEFT - 8
  const plotH = HEIGHT - TOP - BOTTOM
  const slot = plotW / Math.max(days.length, 1)
  const barW = Math.max(2, Math.min(28, slot - 2)) // ≥ 2px surface gap between columns
  const ticks = [0, max / 2, max]
  const labelEvery = Math.ceil(days.length / 8)
  const y = (v: number) => TOP + plotH - (v / max) * plotH
  return (
    <div className="relative w-full">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full"
        role="img"
        aria-label={`${label} per day; the numbers are in the table below`}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={LEFT} x2={WIDTH - 8} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
            <text x={LEFT - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-subtle)">
              {format(t)}
            </text>
          </g>
        ))}
        {days.map((d, i) => {
          const x = LEFT + i * slot + (slot - barW) / 2
          return (
            <g key={d.day}>
              <path d={columnPath(x, y(d.value), barW, TOP + plotH - y(d.value))} fill="var(--viz-1)" opacity={hover === null || hover === i ? 1 : 0.55} />
              {/* Hit target: the whole slot, full height. */}
              <rect x={LEFT + i * slot} y={TOP} width={slot} height={plotH} fill="transparent" onPointerEnter={() => setHover(i)} />
              {i % labelEvery === 0 && (
                <text x={x + barW / 2} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill="var(--text-subtle)">
                  {d.day.slice(5)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {hover !== null && days[hover] && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md border border-border bg-surface-elevated px-2 py-1 text-caption text-text shadow-md"
          style={{
            left: `${((LEFT + (hover + 0.5) * slot) / WIDTH) * 100}%`,
            top: `${(y(days[hover].value) / HEIGHT) * 100}%`,
          }}
        >
          {days[hover].day}: {format(days[hover].value)}
        </div>
      )}
    </div>
  )
}
