import { render } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui/Tooltip'
import type { DocumentStructure } from '@/types/api'
import { DocumentReader } from './DocumentReader'

const structure = {
  version_id: 'v1',
  paginated: true,
  pages: [{ number: 1, width: 600, height: 800, used_ocr: false }],
  sections: [],
  elements: [],
  references: [],
} as DocumentStructure

beforeAll(() => {
  // jsdom has neither observer; the reader only needs them to exist.
  class Observer {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
  }
  vi.stubGlobal('ResizeObserver', Observer)
  vi.stubGlobal('IntersectionObserver', Observer)
})

const highlights = (container: HTMLElement) =>
  container.querySelectorAll<HTMLElement>('[data-page="1"] .ring-2')

describe('DocumentReader', () => {
  it('highlights the target it is first mounted with (deep links, search results)', () => {
    // Regression: the first target was treated as "already seen", so nothing was highlighted.
    const { container } = render(
      <TooltipProvider>
        <DocumentReader
          structure={structure}
          pageTemplate="/pages/{page}.png?w={width}"
          target={{ page: 1, boxes: [[1, 60, 80, 360, 160]], nonce: 0 }}
        />
      </TooltipProvider>,
    )
    const boxes = highlights(container)
    expect(boxes).toHaveLength(1)
    expect(boxes[0].style.left).toBe('10%')
    expect(boxes[0].style.top).toBe('10%')
  })

  it('shows no highlight without a target', () => {
    const { container } = render(
      <TooltipProvider>
        <DocumentReader structure={structure} pageTemplate="/pages/{page}.png?w={width}" />
      </TooltipProvider>,
    )
    expect(highlights(container)).toHaveLength(0)
  })
})

describe('DocumentReader passages', () => {
  const paragraph = (text: string, charStart: number, box: [number, number, number, number, number]) => ({
    text,
    kind: 'text' as const,
    page_start: box[0],
    page_end: box[0],
    char_start: charStart,
    char_end: charStart + text.length,
    boxes: [box],
  })
  const withText = {
    ...structure,
    sections: [
      {
        id: 's1', parent_id: null, level: 1, kind: 'method', title: '3 Approach', number: '3',
        page_start: 1, page_end: 1,
        paragraphs: [
          paragraph('We freeze the pretrained weights.', 100, [1, 60, 80, 540, 120]),
          paragraph('Only A and B receive gradients.', 140, [1, 60, 130, 540, 170]),
        ],
      },
    ],
  } as DocumentStructure

  it('selects the clicked paragraph on a PDF page and offers the passage actions', async () => {
    const { container, getByRole } = render(
      <TooltipProvider>
        <DocumentReader
          structure={withText}
          pageTemplate="/pages/{page}.png?w={width}"
          passageActions={({ paragraph, sectionTitle }) => (
            <span>
              actions for {paragraph.char_start} in {sectionTitle}
            </span>
          )}
          marks={[{ boxes: [[1, 60, 130, 540, 170]], charStart: 140 }]}
        />
      </TooltipProvider>,
    )
    const page = container.querySelector<HTMLElement>('[data-page="1"]')!
    // jsdom has no layout: give the page a size so the click maps to PDF points (1 px = 1 pt).
    page.getBoundingClientRect = () => ({ left: 0, top: 0, width: 600, height: 800 }) as DOMRect
    page.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 300, clientY: 150 }))
    const bar = await vi.waitFor(() => getByRole('region', { name: 'Selected passage' }))
    expect(bar).toHaveTextContent('actions for 140 in 3 Approach')
    expect(bar).toHaveTextContent('p. 1')
    expect(container.querySelectorAll('[data-testid="annotation-mark"]')).toHaveLength(1)
  })

  it('does nothing on click without passage actions', () => {
    const { container, queryByRole } = render(
      <TooltipProvider>
        <DocumentReader structure={withText} pageTemplate="/pages/{page}.png?w={width}" />
      </TooltipProvider>,
    )
    const page = container.querySelector<HTMLElement>('[data-page="1"]')!
    page.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 300, clientY: 150 }))
    expect(queryByRole('region', { name: 'Selected passage' })).toBeNull()
  })
})
