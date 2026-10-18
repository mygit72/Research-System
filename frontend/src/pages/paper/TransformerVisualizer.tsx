import { useState } from 'react'
import { Network, Sparkles } from 'lucide-react'
import { cn } from '@/lib/cn'
import { AttentionInterventionLab } from './AttentionInterventionLab'

const tokens = ['The', 'model', 'learns', 'context']
// Small hand-set vectors make the attention arithmetic inspectable. They are not learned
// parameters or measurements from the paper.
const queries = [
  [0.2, 0.8],
  [0.9, 0.7],
  [0.7, 0.6],
  [0.2, 0.9],
]
const keys = [
  [0.2, 0.3],
  [0.8, 0.7],
  [0.6, 0.5],
  [0.1, 0.9],
]
const values = [
  [0.9, 0.1],
  [0.6, 0.9],
  [0.2, 0.8],
  [0.1, 0.6],
]

function attentionFor(queryIndex: number) {
  const query = queries[queryIndex]
  const scores = keys.map((key) => (query[0] * key[0] + query[1] * key[1]) / Math.sqrt(query.length))
  const exponentials = scores.map((score) => Math.exp(score - Math.max(...scores)))
  const total = exponentials.reduce((sum, value) => sum + value, 0)
  const weights = exponentials.map((value) => value / total)
  const output = values[0].map((_, dimension) =>
    weights.reduce((sum, weight, index) => sum + weight * values[index][dimension], 0),
  )
  return { query, scores, weights, output }
}

function vector(values: number[]) {
  return `[${values.map((value) => value.toFixed(2)).join(', ')}]`
}

function Block({ title, detail, tone = 'primary' }: { title: string; detail: string; tone?: 'primary' | 'violet' | 'teal' }) {
  const tones = {
    primary: 'border-primary/40 bg-primary-soft text-primary',
    violet: 'border-violet-400/40 bg-violet-400/10 text-violet-700 dark:text-violet-300',
    teal: 'border-teal-500/40 bg-teal-500/10 text-teal-700 dark:text-teal-300',
  }
  return (
    <div className={cn('rounded-lg border px-3 py-2 text-center', tones[tone])}>
      <p className="text-small font-semibold">{title}</p>
      <p className="mt-0.5 text-caption text-muted">{detail}</p>
    </div>
  )
}

export function TransformerVisualizer() {
  const [view, setView] = useState<'flow' | 'attention' | 'lab'>('flow')
  const [query, setQuery] = useState(1)
  const attention = attentionFor(query)

  return (
    <section className="space-y-5" aria-labelledby="transformer-map-title">
      <header className="rounded-xl border border-border bg-surface p-5">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
            <Network className="size-5" aria-hidden />
          </span>
          <div>
            <p className="text-caption font-medium tracking-wide text-primary uppercase">Interactive paper guide</p>
            <h2 id="transformer-map-title" className="mt-1 text-h2 text-text">How the Transformer works</h2>
            <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
              A conceptual walkthrough of the encoder–decoder Transformer in <em>Attention Is All You Need</em>.
              Select a view below. The attention weights are illustrative; they are not measurements from the paper.
            </p>
          </div>
        </div>
        <div className="mt-4 flex gap-2" role="tablist" aria-label="Transformer visualization">
          {(['flow', 'attention', 'lab'] as const).map((item) => (
            <button
              key={item}
              role="tab"
              aria-selected={view === item}
              onClick={() => setView(item)}
              className={cn(
                'rounded-md px-3 py-1.5 text-small font-medium capitalize',
                view === item ? 'bg-primary text-white' : 'bg-surface-muted text-muted hover:text-text',
              )}
            >
              {item === 'flow' ? 'Model flow' : item === 'attention' ? 'Inside attention' : 'Intervention lab'}
            </button>
          ))}
        </div>
      </header>

      {view === 'flow' ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <article className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-h3 text-text">Encoder · read the input</h3>
            <p className="mt-1 text-small text-muted">Each layer lets every input token gather context from the others.</p>
            <div className="mx-auto mt-5 grid max-w-sm gap-2">
              <Block title="Input tokens" detail="e.g. a source sentence" tone="teal" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Token + position vectors" detail="meaning and order are represented together" tone="teal" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Multi-head self-attention" detail="several learned views of token-to-token relationships" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Feed-forward network" detail="the same small network is applied at each position" tone="violet" />
              <p className="pt-1 text-center text-caption text-muted">Repeat the layer; residual connections and normalization wrap each sublayer.</p>
            </div>
          </article>
          <article className="rounded-xl border border-border bg-surface p-5">
            <h3 className="text-h3 text-text">Decoder · write the output</h3>
            <p className="mt-1 text-small text-muted">The decoder generates one token at a time, using what it has written so far.</p>
            <div className="mx-auto mt-5 grid max-w-sm gap-2">
              <Block title="Previous output tokens" detail="shifted right during training" tone="violet" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Masked self-attention" detail="cannot look at future output tokens" tone="violet" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Encoder–decoder attention" detail="queries the encoder's representation of the input" />
              <div className="text-center text-muted" aria-hidden>↓</div>
              <Block title="Feed-forward → softmax" detail="scores the next output token" tone="violet" />
              <p className="pt-1 text-center text-caption text-muted">Repeat the layer, then feed each predicted token back into the decoder.</p>
            </div>
          </article>
          <div className="rounded-lg border border-info/30 bg-info-soft p-4 text-small leading-relaxed text-text lg:col-span-2">
            <strong>Why this mattered:</strong> the model connects positions with attention instead of recurrence or convolution.
            The paper argues this makes dependencies easier to learn in parallel; the paper's experiments provide the evidence for its translation results.
          </div>
        </div>
      ) : view === 'attention' ? (
        <article className="rounded-xl border border-border bg-surface p-5">
          <h3 className="text-h3 text-text">A tiny self-attention walkthrough</h3>
          <p className="mt-1 max-w-3xl text-small leading-relaxed text-muted">
            Choose a token. Its query is compared with every token's key; softmax turns those scores into weights that mix the value vectors.
          </p>
          <div className="mt-5 flex flex-wrap gap-2" aria-label="Choose query token">
            {tokens.map((token, index) => (
              <button
                key={token}
                onClick={() => setQuery(index)}
                aria-pressed={query === index}
                className={cn('rounded-full border px-3 py-1.5 text-small', query === index ? 'border-primary bg-primary-soft text-primary' : 'border-border text-muted')}
              >
                {token}
              </button>
            ))}
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <div className="rounded-md bg-surface-muted p-3">
              <p className="text-caption font-medium text-muted">Query Q for “{tokens[query]}”</p>
              <code className="mt-1 block text-small text-text">{vector(attention.query)}</code>
            </div>
            <div className="rounded-md bg-surface-muted p-3">
              <p className="text-caption font-medium text-muted">Scaled dot-product formula</p>
              <code className="mt-1 block text-small text-text">score = (Q · K) / √2</code>
            </div>
          </div>
          <div className="mt-5 overflow-x-auto rounded-md border border-border">
            <div className="grid min-w-[42rem] grid-cols-[6rem_6rem_5rem_minmax(8rem,1fr)_6rem] gap-3 border-b border-border bg-surface-muted px-3 py-2 text-caption font-medium text-muted">
              <span>Token</span><span>Key K</span><span>Score</span><span>Softmax weight</span><span>Value V</span>
            </div>
            {tokens.map((token, index) => {
              const weight = attention.weights[index]
              return (
                <div key={token} className="grid min-w-[42rem] grid-cols-[6rem_6rem_5rem_minmax(8rem,1fr)_6rem] items-center gap-3 border-b border-border px-3 py-2 last:border-0">
                  <span className="text-small text-text">{token}</span>
                  <code className="text-caption text-muted">{vector(keys[index])}</code>
                  <code className="text-caption tabular-nums text-muted">{attention.scores[index].toFixed(2)}</code>
                  <div className="flex items-center gap-2">
                    <div
                      className="h-2.5 min-w-2 overflow-hidden rounded-full bg-surface-muted"
                      role="img"
                      aria-label={`${(weight * 100).toFixed(1)} percent attention to ${token}`}
                    >
                      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${weight * 100}%` }} />
                    </div>
                    <span className="w-12 text-right text-caption tabular-nums text-muted">{(weight * 100).toFixed(1)}%</span>
                  </div>
                  <code className="text-caption text-muted">{vector(values[index])}</code>
                </div>
              )
            })}
          </div>
          <p className="mt-4 rounded-md bg-primary-soft p-3 text-small text-text" aria-live="polite">
            <strong>Weighted output:</strong> <code>{vector(attention.output)}</code>
            <span className="ml-2 text-muted">= sum of each value vector × its attention weight</span>
          </p>
          <p className="mt-3 rounded-md bg-surface-muted p-3 text-small leading-relaxed text-muted">
            <Sparkles className="mr-1 inline size-3.5 text-primary" aria-hidden />
            Query means “what this token is looking for”; keys determine how well each token matches; values carry the information being mixed.
            The toy Q/K/V numbers are hand-set so the calculation stays small. Real Transformer projections are learned, and multiple heads run in parallel.
          </p>
        </article>
      ) : <AttentionInterventionLab />}
      <p className="text-caption text-subtle">
        Based on the paper's described encoder–decoder architecture. This simplified view leaves out dimensions, training details, and implementation choices; consult the cited paper text for those.
      </p>
    </section>
  )
}
