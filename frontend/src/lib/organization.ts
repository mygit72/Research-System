/** Labels and links shared by the organization features (collections, tags, notes, bookmarks). */
import type { Anchor, BookmarkKind, CollectionKind, ReadingStatus } from '@/types/api'

export const COLLECTION_KINDS: Record<CollectionKind, string> = {
  project: 'Research project',
  review: 'Literature review',
  thesis: 'Thesis',
  course: 'Coursework',
  other: 'Other',
}

export const READING_STATUS: Record<ReadingStatus, string> = {
  to_read: 'To read',
  reading: 'Reading',
  done: 'Read',
}

export const BOOKMARK_KINDS: Record<BookmarkKind, string> = {
  paper: 'Paper',
  passage: 'Passage',
  table: 'Table',
  figure: 'Figure',
  citation: 'Citation',
}

/** Deep link into the reader at a bookmarked / noted spot (same format search results use). */
export function anchorLink(documentId: string, anchor: Anchor | null | undefined) {
  if (!anchor || (!anchor.page && anchor.char_start === undefined)) return `/papers/${documentId}`
  const params = new URLSearchParams({ tab: 'paper' })
  if (anchor.page) params.set('page', String(anchor.page))
  if (anchor.char_start !== undefined) params.set('char', String(anchor.char_start))
  return `/papers/${documentId}?${params}`
}
