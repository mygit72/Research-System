/** Knowledge views: labels, colours, links and the graph layout. */
import {
  Building2,
  Cpu,
  Database,
  FileText,
  Gauge,
  Lightbulb,
  Tag,
  Target,
  User,
  type LucideIcon,
} from 'lucide-react'
import type { EntityRelation, EntityType, GraphEdge, GraphNode, NodeType } from '@/types/api'

export const NODE_TYPES: NodeType[] = [
  'paper',
  'topic',
  'method',
  'model',
  'dataset',
  'task',
  'metric',
  'author',
  'institution',
]

export const DEFAULT_GRAPH_TYPES: NodeType[] = ['paper', 'topic', 'method', 'model', 'dataset', 'task', 'author']

export const NODE_META: Record<NodeType, { label: string; plural: string; icon: LucideIcon; color: string }> = {
  paper: { label: 'Paper', plural: 'Papers', icon: FileText, color: 'var(--kg-paper)' },
  topic: { label: 'Topic', plural: 'Topics', icon: Tag, color: 'var(--kg-topic)' },
  method: { label: 'Method', plural: 'Methods', icon: Lightbulb, color: 'var(--kg-method)' },
  model: { label: 'Model', plural: 'Models', icon: Cpu, color: 'var(--kg-model)' },
  dataset: { label: 'Dataset', plural: 'Datasets', icon: Database, color: 'var(--kg-dataset)' },
  task: { label: 'Task', plural: 'Tasks', icon: Target, color: 'var(--kg-task)' },
  metric: { label: 'Metric', plural: 'Metrics', icon: Gauge, color: 'var(--kg-metric)' },
  author: { label: 'Author', plural: 'Authors', icon: User, color: 'var(--kg-author)' },
  institution: { label: 'Institution', plural: 'Institutions', icon: Building2, color: 'var(--kg-institution)' },
}

export const ENTITY_TYPES: EntityType[] = ['dataset', 'model', 'method', 'task', 'metric']

export const RELATION_LABELS: Record<string, string> = {
  authored_by: 'written by',
  affiliated_with: 'affiliated with',
  cites: 'cites',
  proposes: 'proposes',
  uses_dataset: 'uses dataset',
  uses_model: 'uses model',
  uses_method: 'uses method',
  evaluates_on: 'evaluates on',
  reports_metric: 'reports',
  mentions: 'mentions',
  in_topic: 'in topic',
}

/** The same relations read from the other end ("LoRA — used by → paper"). */
export const REVERSE_RELATION_LABELS: Record<string, string> = {
  authored_by: 'author of',
  affiliated_with: 'affiliation of',
  cites: 'cited by',
  proposes: 'proposed by',
  uses_dataset: 'used by',
  uses_model: 'used by',
  uses_method: 'used by',
  evaluates_on: 'evaluated in',
  reports_metric: 'reported by',
  mentions: 'mentioned by',
  in_topic: 'topic of',
}

export const ENTITY_RELATION_LABELS: Record<EntityRelation, string> = {
  proposes: 'Proposes',
  uses: 'Uses',
  mentions: 'Mentions',
}

export const ENTITY_RELATION_HELP: Record<EntityRelation, string> = {
  proposes: 'Introduced by the paper (its title, or “we propose …” in the abstract or introduction)',
  uses: 'Used in the method, experiments, results or tables, or in a sentence like “we evaluate on …”',
  mentions: 'Only mentioned in passing (introduction, related work)',
}

export const SECTION_LABELS: Record<string, string> = {
  title: 'Title',
  abstract: 'Abstract',
  introduction: 'Introduction',
  related_work: 'Related work',
  method: 'Method',
  experiments: 'Experiments',
  results: 'Results',
  discussion: 'Discussion',
  conclusion: 'Conclusion',
  caption: 'Caption',
  appendix: 'Appendix',
  references: 'Appendix',
  other: 'Body',
}

export const CLUSTER_METHODS = {
  auto: { label: 'Automatic (K-Means)', help: 'K-Means, trying 2–8 topics and keeping the number with the best silhouette score.' },
  kmeans: { label: 'K-Means', help: 'Splits the papers into exactly k groups around k centres.' },
  agglomerative: {
    label: 'Hierarchical',
    help: 'Average-linkage agglomerative clustering: repeatedly merges the two closest groups until k remain.',
  },
  hdbscan: {
    label: 'HDBSCAN',
    help: 'Finds dense groups and leaves papers that fit no group unclustered, instead of forcing them into one.',
  },
} as const

/** Ten categorical colours for topic clusters (index = cluster id). */
export const CLUSTER_COLORS = [
  'var(--kg-paper)',
  'var(--kg-topic)',
  'var(--kg-author)',
  'var(--kg-model)',
  'var(--kg-dataset)',
  'var(--kg-method)',
  'var(--kg-task)',
  'var(--kg-metric)',
  'var(--kg-institution)',
  'var(--primary)',
]

export const clusterColor = (id: number) => (id < 0 ? 'var(--text-subtle)' : CLUSTER_COLORS[id % CLUSTER_COLORS.length])

export const entityLink = (id: string) => `/entities/${id}`
export const authorLink = (key: string) => `/authors/${encodeURIComponent(key)}`
export const graphFocusLink = (nodeId: string) => `/graph?focus=${encodeURIComponent(nodeId)}`

/** Where clicking a graph node takes you (null: nothing to open). */
export function nodeLink(node: Pick<GraphNode, 'id' | 'type' | 'data'>): string | null {
  const ref = node.data.ref
  if (!ref) return null
  if (node.type === 'paper') return `/papers/${ref}`
  if (node.type === 'author') return authorLink(ref)
  if (node.type === 'topic') return `/graph?view=topics&topic=${ref}`
  if (node.type === 'institution') return null
  return entityLink(ref)
}

/** Reader deep link for an evidence sentence. */
export const evidenceLink = (documentId: string, page: number) => `/papers/${documentId}?tab=paper&page=${page}`

export function yearsLabel(first: number | null, last: number | null) {
  if (!first) return ''
  return first === last || !last ? String(first) : `${first}–${last}`
}

// --- layout --------------------------------------------------------------------------------------

export interface Point {
  x: number
  y: number
}

/** Stable pseudo-random number in [0, 1) from a string (same id → same start position). */
export function hash01(text: string) {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return ((h >>> 0) % 100000) / 100000
}

/**
 * Force-directed layout (Fruchterman–Reingold style): nodes repel each other, edges pull
 * their ends together, a weak pull keeps everything near the centre. Deterministic: start
 * positions come from the node ids (or `previous`, so expanding the graph doesn't reshuffle
 * what's already on screen). O(n²) per step, fine for the ≤ 200 nodes shown at once.
 */
export function forceLayout(
  nodes: Pick<GraphNode, 'id' | 'type' | 'degree'>[],
  edges: Pick<GraphEdge, 'source' | 'target'>[],
  options: { iterations?: number; previous?: Map<string, Point>; spread?: number } = {},
): Map<string, Point> {
  const n = nodes.length
  const spread = options.spread ?? 90
  const iterations = options.iterations ?? 300
  const index = new Map(nodes.map((node, i) => [node.id, i]))
  const xs = new Float64Array(n)
  const ys = new Float64Array(n)
  const radius = spread * Math.sqrt(Math.max(n, 1))
  const anchors = new Map<string, Point>()
  for (const e of edges) {
    const prev = options.previous
    if (!prev) break
    for (const [a, b] of [
      [e.source, e.target],
      [e.target, e.source],
    ]) {
      const p = prev.get(a)
      if (p && !prev.has(b) && !anchors.has(b)) anchors.set(b, p)
    }
  }
  nodes.forEach((node, i) => {
    const prev = options.previous?.get(node.id) ?? anchors.get(node.id)
    const angle = hash01(node.id) * Math.PI * 2
    const r = (0.3 + 0.7 * hash01(`${node.id}#r`)) * (prev ? spread * 0.6 : radius)
    xs[i] = (prev?.x ?? 0) + Math.cos(angle) * (options.previous?.has(node.id) ? 0 : r)
    ys[i] = (prev?.y ?? 0) + Math.sin(angle) * (options.previous?.has(node.id) ? 0 : r)
  })
  const links = edges
    .map((e) => [index.get(e.source), index.get(e.target)] as const)
    .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined)
  const k = spread
  const mass = Float64Array.from(nodes, (node) => (node.type === 'paper' || node.type === 'topic' ? 1.8 : 1))
  let temperature = options.previous ? spread * 0.5 : radius * 0.25
  const cooling = Math.pow(0.02, 1 / iterations)
  const dx = new Float64Array(n)
  const dy = new Float64Array(n)
  for (let step = 0; step < iterations; step++) {
    dx.fill(0)
    dy.fill(0)
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let ddx = xs[i] - xs[j]
        let ddy = ys[i] - ys[j]
        let dist2 = ddx * ddx + ddy * ddy
        if (dist2 < 0.01) {
          ddx = 0.1 * (hash01(`${i}:${j}`) - 0.5)
          ddy = 0.1
          dist2 = 0.02
        }
        // Repulsion k²/d along the unit vector; papers and topics (big, labelled) push harder so
        // their labels don't pile up in the middle.
        const force = (mass[i] * mass[j] * k * k) / dist2
        dx[i] += ddx * force
        dy[i] += ddy * force
        dx[j] -= ddx * force
        dy[j] -= ddy * force
      }
    }
    for (const [a, b] of links) {
      const ddx = xs[a] - xs[b]
      const ddy = ys[a] - ys[b]
      const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 0.01
      const force = dist / k // attraction d²/k along the unit vector
      dx[a] -= ddx * force
      dy[a] -= ddy * force
      dx[b] += ddx * force
      dy[b] += ddy * force
    }
    for (let i = 0; i < n; i++) {
      dx[i] -= xs[i] * 0.02 // gravity: disconnected parts stay on screen
      dy[i] -= ys[i] * 0.02
      const length = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1
      const move = Math.min(length, temperature)
      xs[i] += (dx[i] / length) * move
      ys[i] += (dy[i] / length) * move
    }
    temperature *= cooling
  }
  return new Map(nodes.map((node, i) => [node.id, { x: xs[i], y: ys[i] }]))
}

/** Bounding box of laid-out points, padded. */
export function bounds(points: Iterable<Point>, pad = 60) {
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }
  if (!Number.isFinite(minX)) return { x: -200, y: -150, width: 400, height: 300 }
  return { x: minX - pad, y: minY - pad, width: maxX - minX + 2 * pad, height: maxY - minY + 2 * pad }
}

/** Node radius from importance (PageRank × node count, ~1 on average). */
export const nodeRadius = (node: Pick<GraphNode, 'importance' | 'type'>) =>
  Math.max(5, Math.min(22, 6 + Math.sqrt(node.importance) * 5)) + (node.type === 'topic' ? 3 : 0)

export function truncate(text: string, length: number) {
  return text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text
}

