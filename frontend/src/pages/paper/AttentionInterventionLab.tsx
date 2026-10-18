import { useMemo, useState } from 'react'
import { SlidersHorizontal } from 'lucide-react'

type Mask = 'bidirectional' | 'causal'
type Matrix = number[][]

function toyVector(token: string, position: number, dimension: number, head: number, role: number) {
  let hash = 2_166_136_261
  for (const char of token) hash = Math.imul(hash ^ char.charCodeAt(0), 16_777_619)
  return Array.from({ length: dimension }, (_, index) => {
    const phase = hash * 0.000001 + (position + 1) * 12.9898 + (head + 1) * 78.233 + (index + 1) * 37.719 + role * 19.193
    return Math.sin(phase)
  })
}

function dot(a: number[], b: number[]) {
  return a.reduce((sum, value, index) => sum + value * b[index], 0)
}

function buildMatrix(queries: number[][], keys: number[][], mask: Mask, divisor: number) {
  return queries.map((query, row) => {
    const logits = keys.map((key, column) => mask === 'causal' && column > row ? Number.NEGATIVE_INFINITY : dot(query, key) / divisor)
    const max = Math.max(...logits)
    const exp = logits.map((value) => Number.isFinite(value) ? Math.exp(value - max) : 0)
    const total = exp.reduce((sum, value) => sum + value, 0)
    return exp.map((value) => value / total)
  })
}

function entropy(matrix: Matrix) {
  if (!matrix.length) return 0
  return matrix.reduce((sum, row) => sum + row.reduce((rowSum, p) => rowSum + (p > 0 ? -p * Math.log(p) : 0), 0), 0) / matrix.length
}

function saturationRate(matrix: Matrix) {
  if (!matrix.length) return 0
  return matrix.filter((row) => Math.max(...row) >= 0.95).length / matrix.length
}

function Heatmap({ title, formula, tokens, matrix, selectedRow, onSelectRow }: {
  title: string
  formula: string
  tokens: string[]
  matrix: Matrix
  selectedRow: number
  onSelectRow: (index: number) => void
}) {
  return (
    <figure aria-label={`${title} heatmap`} className="min-w-0 rounded-lg border border-border bg-surface p-3">
      <figcaption>
        <p className="text-small font-semibold text-text">{title}</p>
        <code className="text-caption text-muted">{formula}</code>
      </figcaption>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-max border-separate border-spacing-1" aria-label={`${title} attention heatmap`}>
          <thead>
            <tr>
              <th scope="col" className="p-1 text-left text-caption font-normal text-muted">Query ↓</th>
              {tokens.map((token, index) => <th key={`${token}-${index}`} scope="col" className="max-w-20 truncate p-1 text-center text-caption font-normal text-muted" title={token}>{token}</th>)}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, rowIndex) => (
              <tr key={`${tokens[rowIndex]}-${rowIndex}`}>
                <th scope="row" className="min-w-0 p-0 text-left">
                  <button
                    type="button"
                    aria-pressed={selectedRow === rowIndex}
                    onClick={() => onSelectRow(rowIndex)}
                    className={`w-full truncate rounded px-1 text-left text-caption ${selectedRow === rowIndex ? 'font-semibold text-primary' : 'text-muted'}`}
                    title={`Inspect query token ${tokens[rowIndex]}`}
                  >
                    {tokens[rowIndex]}
                  </button>
                </th>
                {row.map((weight, columnIndex) => {
                  const masked = weight === 0
                  const percent = (weight * 100).toFixed(1)
                  return (
                    <td key={`${tokens[columnIndex]}-${columnIndex}`} className="p-0">
                      <span
                        role="img"
                        aria-label={`${tokens[rowIndex]} attends to ${tokens[columnIndex]}: ${percent}%${masked ? ' (masked)' : ''}`}
                        title={masked ? 'Masked: this query cannot attend to a future token' : `${percent}% attention weight`}
                        className={`flex h-9 items-center justify-center rounded font-mono text-[11px] tabular-nums ${masked ? 'text-subtle' : 'text-text'}`}
                        style={{ backgroundColor: masked ? 'var(--surface-muted)' : `color-mix(in srgb, var(--primary) ${Math.max(5, Math.round(weight * 100))}%, var(--surface))` }}
                      >
                        {masked ? '—' : `${percent}%`}
                      </span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-caption">
        <p className="rounded bg-surface-muted p-2 text-muted">Mean row entropy <strong className="text-text">{entropy(matrix).toFixed(2)} nats</strong></p>
        <p className="rounded bg-surface-muted p-2 text-muted">Rows ≥95% on one token <strong className="text-text">{(saturationRate(matrix) * 100).toFixed(0)}%</strong></p>
      </div>
    </figure>
  )
}

function shortVector(vector: number[]) {
  const shown = vector.slice(0, 4).map((value) => value.toFixed(2)).join(', ')
  return `[${shown}${vector.length > 4 ? ', …' : ''}]`
}

export function AttentionInterventionLab() {
  const [sentence, setSentence] = useState('The model learns context')
  const [dimension, setDimension] = useState(8)
  const [head, setHead] = useState(1)
  const [mask, setMask] = useState<Mask>('bidirectional')
  const [selectedRow, setSelectedRow] = useState(0)
  const tokens = sentence.trim().split(/\s+/).filter(Boolean).slice(0, 8)
  const truncated = sentence.trim().split(/\s+/).filter(Boolean).length > 8
  const vectors = useMemo(() => tokens.map((token, position) => ({
    query: toyVector(token, position, dimension, head - 1, 1),
    key: toyVector(token, position, dimension, head - 1, 2),
    value: toyVector(token, position, dimension, head - 1, 3),
  })), [sentence, dimension, head])
  const queries = vectors.map((item) => item.query)
  const keys = vectors.map((item) => item.key)
  const values = vectors.map((item) => item.value)
  const scaled = useMemo(() => buildMatrix(queries, keys, mask, Math.sqrt(dimension)), [sentence, dimension, head, mask])
  const unscaled = useMemo(() => buildMatrix(queries, keys, mask, 1), [sentence, dimension, head, mask])
  const row = Math.min(selectedRow, Math.max(0, tokens.length - 1))
  const outputFor = (matrix: Matrix) => values[row]?.map((_, index) => matrix[row].reduce((sum, weight, keyIndex) => sum + weight * values[keyIndex][index], 0)) ?? []

  return (
    <article className="space-y-4 rounded-xl border border-border bg-surface p-4 sm:p-5" aria-labelledby="attention-lab-title">
      <header className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><SlidersHorizontal className="size-5" aria-hidden /></span>
        <div>
          <p className="text-caption font-medium tracking-wide text-primary uppercase">Change one mechanism at a time</p>
          <h3 id="attention-lab-title" className="mt-1 text-h3 text-text">Attention intervention lab</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">See how scaling and masking change token-to-token attention. Edit the tokens and settings; both heatmaps recalculate immediately.</p>
        </div>
      </header>

      <div className="grid gap-3 rounded-lg bg-surface-muted p-3 lg:grid-cols-[minmax(0,1fr)_12rem_10rem_12rem] lg:items-end">
        <label className="text-small font-medium text-text">
          Input tokens (space-separated)
          <input value={sentence} onChange={(event) => { setSentence(event.target.value); setSelectedRow(0) }} maxLength={180} aria-label="Input tokens" className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text" />
          <span className="mt-1 block text-caption font-normal text-muted">Up to 8 tokens{truncated ? ' shown; later tokens are omitted' : ''}.</span>
        </label>
        <label className="text-small font-medium text-text">
          Key dimension dₖ
          <select aria-label="Key dimension d_k" value={dimension} onChange={(event) => setDimension(Number(event.target.value))} className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text">
            {[2, 8, 32, 64, 128].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-small font-medium text-text">
          Head sample
          <select aria-label="Head sample" value={head} onChange={(event) => setHead(Number(event.target.value))} className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((value) => <option key={value} value={value}>Head {value}</option>)}
          </select>
        </label>
        <label className="text-small font-medium text-text">
          Attention mask
          <select aria-label="Attention mask" value={mask} onChange={(event) => setMask(event.target.value as Mask)} className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-2 text-small text-text">
            <option value="bidirectional">Bidirectional (encoder)</option>
            <option value="causal">Causal (decoder)</option>
          </select>
        </label>
      </div>

      {tokens.length ? (
        <>
          <div className="grid gap-3 xl:grid-cols-2">
            <Heatmap title="Scaled dot-product attention" formula={`softmax(QKᵀ / √${dimension})`} tokens={tokens} matrix={scaled} selectedRow={row} onSelectRow={setSelectedRow} />
            <Heatmap title="Without scaling (ablation)" formula="softmax(QKᵀ)" tokens={tokens} matrix={unscaled} selectedRow={row} onSelectRow={setSelectedRow} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <p className="rounded-lg border border-primary/20 bg-primary-soft p-3 text-small leading-relaxed text-text"><strong>Selected query: “{tokens[row]}”</strong><br />Scaled weighted value output: <code>{shortVector(outputFor(scaled))}</code></p>
            <p className="rounded-lg border border-border bg-surface-muted p-3 text-small leading-relaxed text-text"><strong>Same query, ablation:</strong><br />Unscaled weighted value output: <code>{shortVector(outputFor(unscaled))}</code></p>
          </div>
        </>
      ) : <p className="rounded-lg border border-border bg-surface-muted p-4 text-small text-muted">Enter at least one token to calculate attention.</p>}

      <p className="rounded-lg border border-info/30 bg-info-soft p-3 text-caption leading-relaxed text-text">
        These are deterministic toy Q/K/V vectors, not trained Transformer weights or measurements from the paper. The calculation demonstrates the softmax mechanism only. With a causal mask, future-token cells are blocked; early rows can be one-hot because of the mask, not because logits saturated.
      </p>
    </article>
  )
}
