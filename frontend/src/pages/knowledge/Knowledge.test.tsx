import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PaperEntitiesCard, RelatedWork } from '@/components/knowledge/PaperKnowledge'
import { TooltipProvider } from '@/components/ui/Tooltip'
import { bounds, forceLayout, nodeLink } from '@/lib/knowledge'
import { knowledgeApi } from '@/services/api'
import type { DocumentEntity, GraphNode, KnowledgeGraph, TopicClustering } from '@/types/api'
import { EntityPage } from './EntityPage'
import { GraphView } from './GraphView'
import { TopicsView } from './TopicsView'

function wrap(children: ReactNode, path = '/', route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={children} />
            <Route path="/papers/:id" element={<p>Opened paper</p>} />
          </Routes>
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>
  )
}

afterEach(() => vi.restoreAllMocks())

const node = (id: string, type: GraphNode['type'], label: string, extra: Partial<GraphNode> = {}): GraphNode => ({
  id,
  type,
  label,
  importance: 1,
  degree: 1,
  hidden_neighbors: 0,
  data: { ref: id.split(':')[1] },
  ...extra,
})

describe('forceLayout', () => {
  const nodes = ['a', 'b', 'c', 'd'].map((id) => ({ id, type: 'paper' as const, degree: 1 }))
  const edges = [
    { source: 'a', target: 'b' },
    { source: 'c', target: 'd' },
  ]
  const dist = (p: Map<string, { x: number; y: number }>, a: string, b: string) =>
    Math.hypot(p.get(a)!.x - p.get(b)!.x, p.get(a)!.y - p.get(b)!.y)

  it('is deterministic and pulls connected nodes together', () => {
    const one = forceLayout(nodes, edges)
    const two = forceLayout(nodes, edges)
    expect([...one.values()]).toEqual([...two.values()])
    expect(dist(one, 'a', 'b')).toBeLessThan(dist(one, 'a', 'c'))
    expect(dist(one, 'c', 'd')).toBeLessThan(dist(one, 'b', 'd'))
  })

  it('keeps placed nodes close to where they were when the graph grows', () => {
    const before = forceLayout(nodes, edges)
    const after = forceLayout([...nodes, { id: 'e', type: 'dataset', degree: 1 }], [...edges, { source: 'a', target: 'e' }], {
      previous: before,
      iterations: 120,
    })
    const box = bounds(before.values())
    for (const id of ['a', 'b', 'c', 'd']) expect(dist(new Map([...before, ['x', after.get(id)!]]), id, 'x')).toBeLessThan(box.width / 2)
    expect(dist(after, 'a', 'e')).toBeLessThan(dist(after, 'c', 'e'))
  })

  it('links nodes to their pages', () => {
    expect(nodeLink(node('paper:p1', 'paper', 'P'))).toBe('/papers/p1')
    expect(nodeLink(node('entity:e1', 'dataset', 'GLUE'))).toBe('/entities/e1')
    expect(nodeLink(node('author:jane doe', 'author', 'Jane Doe'))).toBe('/authors/jane%20doe')
    expect(nodeLink(node('institution:x', 'institution', 'X'))).toBeNull()
  })
})

const entity = (name: string, relation: DocumentEntity['relation'], type: DocumentEntity['type'] = 'dataset'): DocumentEntity => ({
  id: name,
  type,
  name,
  relation,
  mentions: 3,
  variants: [],
  paper_count: 2,
  evidence: [{ quote: `We evaluate on ${name}.`, page: 4, section_kind: 'experiments', surface: name }],
})

describe('PaperEntitiesCard', () => {
  it('groups by relation and shows the evidence sentence with its page', async () => {
    vi.spyOn(knowledgeApi, 'documentEntities').mockResolvedValue([
      entity('RALA', 'proposes', 'method'),
      entity('SciQA-2400', 'uses'),
      entity('GLUE', 'mentions'),
    ])
    render(wrap(<PaperEntitiesCard documentId="d1" ready />))
    const proposes = await screen.findByRole('button', { name: 'RALA' })
    expect(screen.getByText('Also mentioned in passing: GLUE.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'SciQA-2400' }))
    expect(screen.getByText('We evaluate on SciQA-2400.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Experiments · page 4' })).toHaveAttribute('href', '/papers/d1?tab=paper&page=4')
    expect(proposes).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders nothing for a paper with no entities', async () => {
    const spy = vi.spyOn(knowledgeApi, 'documentEntities').mockResolvedValue([])
    const { container } = render(wrap(<PaperEntitiesCard documentId="d1" ready />))
    await vi.waitFor(() => expect(spy).toHaveBeenCalled())
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})

describe('RelatedWork', () => {
  it('lists citations in both directions with how they were matched', async () => {
    const paper = (id: string, title: string) => ({ id, title, year: 2024, venue: null, authors: 'A. B.', topic: null })
    vi.spyOn(knowledgeApi, 'related').mockResolvedValue({
      cites: [{ ...paper('p2', 'Hybrid retrieval'), match: 'arxiv', reference: '[1] Hybrid retrieval. arXiv:2403.01234' }],
      cited_by: [{ ...paper('p3', 'Later work'), match: 'title', reference: '[4] Our paper.' }],
      shared_entities: [{ ...paper('p2', 'Hybrid retrieval'), shared: { dataset: ['SciQA-2400'] }, score: 0.5 }],
      same_authors: [],
      topic: null,
    })
    render(wrap(<RelatedWork documentId="d1" ready />))
    expect(await screen.findByText('Cites')).toBeInTheDocument()
    expect(screen.getByText('Cited by')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Matched by arXiv id/ }))
    expect(screen.getByText('[1] Hybrid retrieval. arXiv:2403.01234')).toBeInTheDocument()
    expect(screen.getByText('datasets: SciQA-2400')).toBeInTheDocument()
  })
})

const graph = (nodes: GraphNode[], edges: KnowledgeGraph['edges'] = []): KnowledgeGraph => ({
  nodes,
  edges,
  hidden: { dataset: 3 },
  total_nodes: nodes.length + 3,
  total_edges: edges.length,
  paper_count: nodes.filter((n) => n.type === 'paper').length,
  entity_status: { entities: 4, authors: 2, citations: 1, topics: 0 },
})

describe('GraphView', () => {
  it('shows the graph, node details and expands a node', async () => {
    const p = node('paper:p1', 'paper', 'Hybrid retrieval', { hidden_neighbors: 2, degree: 3, data: { ref: 'p1', year: 2024 } })
    const d = node('entity:e1', 'dataset', 'SciQA-2400', { data: { ref: 'e1', papers: 3 } })
    vi.spyOn(knowledgeApi, 'graph').mockResolvedValue(graph([p, d], [{ source: p.id, target: d.id, relation: 'uses_dataset', weight: 1 }]))
    const neighbors = vi
      .spyOn(knowledgeApi, 'neighbors')
      .mockResolvedValue(graph([p, node('author:jane', 'author', 'Jane Doe')], [{ source: p.id, target: 'author:jane', relation: 'authored_by', weight: 1 }]))
    render(wrap(<GraphView />))
    const paperNode = await screen.findByRole('button', { name: /Paper: Hybrid retrieval/ })
    expect(screen.getByRole('group', { name: /2 nodes and 1 connections/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Datasets/ })).toHaveTextContent('+3')
    await userEvent.click(paperNode)
    const details = screen.getByRole('complementary', { name: 'Graph details' })
    expect(within(details).getByRole('heading', { name: 'Hybrid retrieval' })).toBeInTheDocument()
    expect(within(details).getByRole('link', { name: /Open/ })).toHaveAttribute('href', '/papers/p1')
    await userEvent.click(within(details).getByRole('button', { name: /Show 2 more/ }))
    expect(neighbors).toHaveBeenCalledWith('paper:p1', expect.objectContaining({ limit: 25 }))
    expect(await screen.findByRole('button', { name: /Author: Jane Doe/ })).toBeInTheDocument()
  })

  it('invites uploading when the library is empty', async () => {
    vi.spyOn(knowledgeApi, 'graph').mockResolvedValue(graph([]))
    render(wrap(<GraphView />))
    expect(await screen.findByText('No papers yet')).toBeInTheDocument()
  })
})

const clustering = (over: Partial<TopicClustering> = {}): TopicClustering => ({
  id: 'run1',
  method: 'auto',
  params: {},
  embedding_model: 'test',
  naming_status: 'done',
  naming_model: 'qwen2.5:3b',
  error_message: null,
  created_at: new Date().toISOString(),
  clusters: [
    { id: 0, name: 'Hybrid Retrieval', name_source: 'model', terms: ['retrieval', 'reranking'], entities: ['BM25'], document_ids: ['p1', 'p2'], size: 2 },
  ],
  points: [
    { document_id: 'p1', title: 'Hybrid retrieval', x: 0.5, y: 0.2, cluster: 0 },
    { document_id: 'p2', title: 'Dense retrieval', x: 0.4, y: 0.1, cluster: 0 },
    { document_id: 'p3', title: 'An outlier', x: -1, y: -1, cluster: -1 },
  ],
  quality: { silhouette: 0.31, noise: 1, chosen_k: 2, variance_2d: 0.62 },
  excluded: [{ document_id: 'p4', reason: 'not_indexed' }],
  paper_count: 3,
  stale: null,
  ...over,
})

describe('TopicsView', () => {
  it('explains the clustering and lists topics with their evidence', async () => {
    vi.spyOn(knowledgeApi, 'topics').mockResolvedValue({ clustering: clustering(), searchable_papers: 3 })
    render(wrap(<TopicsView />))
    expect(await screen.findByRole('heading', { name: 'Hybrid Retrieval' })).toBeInTheDocument()
    expect(screen.getByText('AI-named')).toBeInTheDocument()
    expect(screen.getByText('retrieval, reranking')).toBeInTheDocument()
    expect(screen.getByText('0.31 · reasonably separated')).toBeInTheDocument()
    expect(screen.getByText('In no topic')).toBeInTheDocument()
    expect(screen.getByText(/1 paper not included: not searchable yet/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Map of 3 papers coloured by topic' })).toBeInTheDocument()
  })

  it('starts a clustering with the chosen method', async () => {
    vi.spyOn(knowledgeApi, 'topics').mockResolvedValue({ clustering: null, searchable_papers: 5 })
    const cluster = vi.spyOn(knowledgeApi, 'cluster').mockResolvedValue(clustering())
    render(wrap(<TopicsView />))
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Method' }), 'kmeans')
    const k = screen.getByRole('spinbutton', { name: 'Topics (k)' })
    await userEvent.clear(k)
    await userEvent.type(k, '4')
    await userEvent.click(screen.getByRole('button', { name: /Find topics/ }))
    expect(cluster).toHaveBeenCalledWith({ method: 'kmeans', k: 4, min_cluster_size: undefined })
  })

  it('needs three searchable papers', async () => {
    vi.spyOn(knowledgeApi, 'topics').mockResolvedValue({ clustering: null, searchable_papers: 2 })
    render(wrap(<TopicsView />))
    expect(await screen.findByRole('button', { name: /Find topics/ })).toBeDisabled()
    expect(screen.getByText(/needs at least 3 searchable papers \(you have 2\)/)).toBeInTheDocument()
  })
})

describe('EntityPage', () => {
  it('separates catalog facts from what the papers say', async () => {
    vi.spyOn(knowledgeApi, 'entity').mockResolvedValue({
      id: 'e1',
      type: 'dataset',
      name: 'Natural Questions',
      aliases: ['NQ'],
      source: 'catalog',
      info: { task: 'Open-domain question answering', license: 'CC BY-SA 3.0' },
      papers: [
        {
          id: 'p1',
          title: 'Dense retrieval',
          year: 2020,
          venue: null,
          authors: '',
          topic: null,
          relation: 'uses',
          mentions: 5,
          variants: [],
          evidence: [{ quote: 'We evaluate on Natural Questions.', page: 6, section_kind: 'experiments', surface: 'NQ' }],
        },
      ],
      related: [{ id: 'e2', type: 'method', name: 'BM25', shared_papers: 1 }],
      years: [{ year: 2020, papers: 1 }],
    })
    render(wrap(<EntityPage />, '/entities/e1', '/entities/:id'))
    expect(await screen.findByRole('heading', { name: 'Natural Questions' })).toBeInTheDocument()
    expect(screen.getByText('Also written as NQ')).toBeInTheDocument()
    expect(screen.getByText('CC BY-SA 3.0')).toBeInTheDocument()
    expect(screen.getByText(/built-in catalog/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Uses it/ })).toBeInTheDocument()
    expect(screen.getByText('We evaluate on Natural Questions.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /BM25/ })).toHaveAttribute('href', '/entities/e2')
  })
})
