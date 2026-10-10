import type { ReactNode } from 'react'
import type { EvidenceItem } from '@/types/api'
import { CitationChip, type OpenSource } from './Sources'

/** Renders the markers in a [n, m] group; numbers with no passage are shown as plain text. */
export function citationRenderer(evidence: EvidenceItem[], reranker: string | null, onOpen?: OpenSource) {
  return (numbers: number[], raw: string, key: string): ReactNode => {
    const items = numbers.map((n) => evidence.find((e) => e.number === n))
    if (items.some((item) => !item)) return <span key={key}>{raw}</span>
    return (
      <span key={key} className="whitespace-nowrap">
        {items.map((item) => (
          <CitationChip key={item!.number} item={item!} reranker={reranker} onOpen={onOpen} />
        ))}
      </span>
    )
  }
}
