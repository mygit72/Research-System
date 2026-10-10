import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from 'react'
import { Maximize2, Minus, Plus } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/lib/cn'
import { NODE_META, RELATION_LABELS, bounds, forceLayout, nodeRadius, truncate, type Point } from '@/lib/knowledge'
import type { GraphEdge, GraphNode } from '@/types/api'

interface View {
  x: number
  y: number
  width: number
  height: number
}

const LABELLED = 10 // most important nodes always show their label (others on hover or selection)

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  highlight,
  onSelect,
  onExpand,
  className,
}: {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  /** Nodes to emphasise (a found path, search hits); everything else is dimmed. */
  highlight?: Set<string> | null
  onSelect: (node: GraphNode | null) => void
  onExpand?: (node: GraphNode) => void
  className?: string
}) {
  // Layout is recomputed when the graph changes (adjusting state while rendering, as React
  // recommends for derived state): what's already placed stays put, new nodes start next to
  // their neighbours, and the view re-fits.
  const [placed, setPlaced] = useState(() => ({ nodes, edges, layout: forceLayout(nodes, edges) }))
  if (placed.nodes !== nodes || placed.edges !== edges) {
    const ids = new Set(nodes.map((n) => n.id))
    const known = new Map([...placed.layout].filter(([id]) => ids.has(id)))
    const next = forceLayout(nodes, edges, {
      previous: known.size ? known : undefined,
      iterations: known.size ? 160 : 300,
    })
    setPlaced({ nodes, edges, layout: next })
  }

  // The canvas's size on screen: text and strokes are sized in pixels, and the (roughly
  // round) layout is stretched to the canvas's aspect ratio so wide screens are used.
  const container = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 900, height: 560 })
  useEffect(() => {
    const element = container.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) setSize({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const stretch = Math.min(Math.max(size.width / size.height, 1), 2)
  const layout = useMemo(
    () => new Map([...placed.layout].map(([id, p]) => [id, { x: p.x * stretch, y: p.y }])),
    [placed.layout, stretch],
  )
  const fit = useMemo(() => {
    const box = bounds(layout.values())
    // Centres are padded by 60 units; labels run wider, so add room left and right.
    return { ...box, x: box.x - box.width * 0.1, width: box.width * 1.2 }
  }, [layout])
  const [view, setView] = useState<View>(fit)
  const [fitted, setFitted] = useState(fit)
  if (fitted !== fit) {
    setFitted(fit) // new layout or canvas shape: re-fit
    setView(fit)
  }

  const [hovered, setHovered] = useState<string | null>(null)
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null)

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const neighbors = useMemo(() => {
    const map = new Map<string, Set<string>>()
    for (const e of edges) {
      if (!map.has(e.source)) map.set(e.source, new Set())
      if (!map.has(e.target)) map.set(e.target, new Set())
      map.get(e.source)!.add(e.target)
      map.get(e.target)!.add(e.source)
    }
    return map
  }, [edges])
  const byImportance = useMemo(() => [...nodes].sort((a, b) => b.importance - a.importance), [nodes])

  const active = hovered ?? selectedId
  const focusSet = highlight ?? (active ? new Set([active, ...(neighbors.get(active) ?? [])]) : null)
  // Drawing units per screen pixel (the viewBox is fitted inside the canvas, keeping its aspect).
  const scale = Math.max(view.width / size.width, view.height / size.height)

  // Labels, placed greedily by priority (active/selected, highlighted, topics, most important)
  // and skipped when they'd overlap one already placed: densely connected papers otherwise
  // stack their titles on top of each other.
  const labels = new Set<string>()
  const taken: { x: number; y: number; w: number; h: number }[] = []
  const candidates = [
    ...[active, selectedId].filter((id): id is string => !!id),
    ...byImportance.filter((n) => focusSet?.has(n.id)).map((n) => n.id),
    ...byImportance.filter((n) => n.type === 'topic').map((n) => n.id),
    ...byImportance.slice(0, LABELLED).map((n) => n.id),
  ]
  for (const id of candidates) {
    const node = byId.get(id)
    const p = layout.get(id)
    if (!node || !p || labels.has(id)) continue
    const chars = Math.min(node.label.length, node.type === 'paper' ? 42 : 28)
    const box = { x: p.x - (chars * 6.2 * scale) / 2, y: p.y + nodeRadius(node) + 2 * scale, w: chars * 6.2 * scale, h: 14 * scale }
    const forced = id === active || id === selectedId
    if (!forced && taken.some((t) => t.x < box.x + box.w && box.x < t.x + t.w && t.y < box.y + box.h && box.y < t.y + t.h)) continue
    labels.add(id)
    taken.push(box)
  }

  const toSvg = (clientX: number, clientY: number) => {
    const rect = svg.current!.getBoundingClientRect()
    return {
      x: view.x + ((clientX - rect.left) / rect.width) * view.width,
      y: view.y + ((clientY - rect.top) / rect.height) * view.height,
    }
  }

  const zoom = (factor: number, center?: Point) => {
    setView((v) => {
      const c = center ?? { x: v.x + v.width / 2, y: v.y + v.height / 2 }
      const width = Math.min(Math.max(v.width * factor, 80), fit.width * 6)
      const height = (v.height / v.width) * width
      return {
        x: c.x - ((c.x - v.x) / v.width) * width,
        y: c.y - ((c.y - v.y) / v.height) * height,
        width,
        height,
      }
    })
  }

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    zoom(event.deltaY > 0 ? 1.15 : 1 / 1.15, toSvg(event.clientX, event.clientY))
  }
  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest('[data-node]')) return
    drag.current = { x: event.clientX, y: event.clientY, view, moved: false }
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
  }
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const start = drag.current
    if (!start || !svg.current) return
    const rect = svg.current.getBoundingClientRect()
    const dx = ((event.clientX - start.x) / rect.width) * start.view.width
    const dy = ((event.clientY - start.y) / rect.height) * start.view.height
    if (Math.abs(event.clientX - start.x) + Math.abs(event.clientY - start.y) > 3) start.moved = true
    setView({ ...start.view, x: start.view.x - dx, y: start.view.y - dy })
  }
  const onPointerUp = () => {
    if (drag.current && !drag.current.moved) onSelect(null) // a click on the background
    drag.current = null
  }

  return (
    <div ref={container} className={cn('relative overflow-hidden rounded-lg border border-border bg-surface', className)}>
      <svg
        ref={svg}
        role="group"
        aria-label={`Knowledge graph with ${nodes.length} nodes and ${edges.length} connections`}
        viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
        preserveAspectRatio="xMidYMid meet"
        className="size-full cursor-grab touch-none select-none active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <defs>
          <marker id="kg-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-subtle)" />
          </marker>
        </defs>
        <g>
          {edges.map((e) => {
            const a = layout.get(e.source)
            const b = layout.get(e.target)
            const target = byId.get(e.target)
            if (!a || !b || !target) return null
            const on = focusSet ? focusSet.has(e.source) && focusSet.has(e.target) : true
            // Stop arrows at the target's edge.
            const r = nodeRadius(target) + 2
            const len = Math.hypot(b.x - a.x, b.y - a.y) || 1
            const end = { x: b.x - ((b.x - a.x) / len) * r, y: b.y - ((b.y - a.y) / len) * r }
            return (
              <line
                key={`${e.source}-${e.target}-${e.relation}`}
                x1={a.x}
                y1={a.y}
                x2={e.relation === 'cites' ? end.x : b.x}
                y2={e.relation === 'cites' ? end.y : b.y}
                stroke={on && focusSet ? 'var(--text-muted)' : 'var(--kg-edge)'}
                strokeWidth={(e.relation === 'cites' ? 1.6 : 1) * Math.max(scale, 0.6)}
                strokeDasharray={e.relation === 'mentions' ? `${4 * scale} ${3 * scale}` : undefined}
                markerEnd={e.relation === 'cites' ? 'url(#kg-arrow)' : undefined}
                opacity={on ? 1 : 0.25}
              >
                <title>{RELATION_LABELS[e.relation] ?? e.relation}</title>
              </line>
            )
          })}
        </g>
        <g>
          {nodes.map((node) => {
            const p = layout.get(node.id)
            if (!p) return null
            const r = nodeRadius(node)
            const dim = focusSet ? !focusSet.has(node.id) : false
            const showLabel = labels.has(node.id)
            const meta = NODE_META[node.type]
            return (
              <g
                key={node.id}
                data-node
                transform={`translate(${p.x} ${p.y})`}
                role="button"
                tabIndex={0}
                aria-label={`${meta.label}: ${node.label}${node.hidden_neighbors ? `, ${node.hidden_neighbors} more connections` : ''}`}
                aria-pressed={node.id === selectedId}
                className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-[var(--ring)]"
                opacity={dim ? 0.3 : 1}
                onClick={(event) => {
                  event.stopPropagation()
                  onSelect(node)
                }}
                onDoubleClick={() => onExpand?.(node)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelect(node)
                  }
                }}
                onPointerEnter={() => setHovered(node.id)}
                onPointerLeave={() => setHovered(null)}
                onFocus={() => setHovered(node.id)}
                onBlur={() => setHovered(null)}
              >
                <circle
                  r={r}
                  fill={meta.color}
                  stroke={node.id === selectedId ? 'var(--text)' : 'var(--surface)'}
                  strokeWidth={(node.id === selectedId ? 3 : 1.5) * Math.max(scale, 0.6)}
                />
                {node.hidden_neighbors > 0 && (
                  <circle r={r + 3 * scale} fill="none" stroke={meta.color} strokeWidth={scale} strokeDasharray={`${2 * scale} ${2 * scale}`} />
                )}
                {showLabel && (
                  <text
                    y={r + 12 * scale}
                    textAnchor="middle"
                    fontSize={11 * scale}
                    fontWeight={node.id === selectedId ? 600 : 500}
                    fill="var(--text)"
                    stroke="var(--surface)"
                    strokeWidth={3 * scale}
                    paintOrder="stroke"
                  >
                    {truncate(node.label, node.type === 'paper' ? 42 : 28)}
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>
      <div className="absolute right-3 bottom-3 flex flex-col gap-1">
        <Tooltip content="Zoom in">
          <Button variant="secondary" size="icon-sm" aria-label="Zoom in" onClick={() => zoom(1 / 1.3)}>
            <Plus className="size-4" aria-hidden />
          </Button>
        </Tooltip>
        <Tooltip content="Zoom out">
          <Button variant="secondary" size="icon-sm" aria-label="Zoom out" onClick={() => zoom(1.3)}>
            <Minus className="size-4" aria-hidden />
          </Button>
        </Tooltip>
        <Tooltip content="Fit to screen">
          <Button variant="secondary" size="icon-sm" aria-label="Fit to screen" onClick={() => setView(fit)}>
            <Maximize2 className="size-4" aria-hidden />
          </Button>
        </Tooltip>
      </div>
    </div>
  )
}
