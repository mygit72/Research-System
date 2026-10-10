import type { DocumentDetail, MetadataUpdate } from '@/types/api'

export interface MetadataForm {
  title: string
  authors: string
  year: string
  venue: string
  doi: string
  arxiv_id: string
  keywords: string
  abstract: string
}

export function initialMetadataForm(doc: DocumentDetail): MetadataForm {
  const m = doc.metadata
  return {
    title: m?.title ?? doc.title,
    authors: (m?.authors ?? []).map((a) => a.name).join('\n'),
    year: m?.year ? String(m.year) : '',
    venue: m?.venue ?? '',
    doi: m?.doi ?? '',
    arxiv_id: m?.arxiv_id ?? '',
    keywords: (m?.keywords ?? []).join(', '),
    abstract: m?.abstract ?? '',
  }
}

/** Only send fields the user actually changed (they become "corrected" and protected). */
export function diffMetadata(before: MetadataForm, after: MetadataForm, doc: DocumentDetail): MetadataUpdate {
  const patch: MetadataUpdate = {}
  const text = (v: string) => v.trim() || null
  if (after.title.trim() !== before.title.trim()) patch.title = after.title.trim()
  if (after.authors !== before.authors) {
    const previous = new Map((doc.metadata?.authors ?? []).map((a) => [a.name, a]))
    patch.authors = after.authors
      .split('\n')
      .map((name) => name.trim())
      .filter(Boolean)
      .map((name) => previous.get(name) ?? { name })
  }
  if (after.year !== before.year) patch.year = after.year ? Number(after.year) : null
  if (after.venue !== before.venue) patch.venue = text(after.venue)
  if (after.doi !== before.doi) patch.doi = text(after.doi)
  if (after.arxiv_id !== before.arxiv_id) patch.arxiv_id = text(after.arxiv_id)
  if (after.keywords !== before.keywords)
    patch.keywords = after.keywords
      .split(',')
      .map((k) => k.trim())
      .filter(Boolean)
  if (after.abstract !== before.abstract) patch.abstract = text(after.abstract)
  return patch
}
