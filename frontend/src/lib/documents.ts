/** Display helpers for documents and processing jobs. */

const STAGE_LABELS: Record<string, string> = {
  queued: 'Waiting to start',
  starting: 'Starting',
  parsing: 'Extracting text',
  ocr: 'Running OCR',
  structure: 'Detecting structure',
  metadata: 'Extracting metadata',
  saving: 'Saving',
  chunking: 'Splitting into passages',
  embedding: 'Embedding passages',
  indexing: 'Adding to the search index',
  thumbnail: 'Rendering preview',
  duplicates: 'Checking for duplicates',
  entities: 'Finding datasets, models and methods',
  naming: 'Naming topics',
}

export function stageLabel(stage: string | undefined) {
  return (stage && STAGE_LABELS[stage]) ?? 'Processing'
}
