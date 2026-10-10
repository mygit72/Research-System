import { describe, expect, it } from 'vitest'
import { citationNumbers, citedNumbers, parseInline, parseMarkdown } from './markdown'

describe('parseInline', () => {
  it('parses emphasis, code, math and citations', () => {
    expect(parseInline('**LoRA** cuts memory by `60%` [1, 3] and $W = BA$ [2-4].')).toEqual([
      { type: 'strong', children: [{ type: 'text', text: 'LoRA' }] },
      { type: 'text', text: ' cuts memory by ' },
      { type: 'code', text: '60%' },
      { type: 'text', text: ' ' },
      { type: 'cite', numbers: [1, 3], raw: '[1, 3]' },
      { type: 'text', text: ' and ' },
      { type: 'math', text: 'W = BA' },
      { type: 'text', text: ' ' },
      { type: 'cite', numbers: [2, 3, 4], raw: '[2-4]' },
      { type: 'text', text: '.' },
    ])
  })

  it('leaves prices, snake_case and lone asterisks alone', () => {
    const nodes = parseInline('It costs $5 and $10, uses top_k_value and 2 * 3 * 4.')
    expect(nodes).toEqual([{ type: 'text', text: 'It costs $5 and $10, uses top_k_value and 2 * 3 * 4.' }])
  })

  it('expands short citation ranges only', () => {
    expect(citationNumbers('1–3')).toEqual([1, 2, 3])
    expect(citationNumbers('1-200')).toEqual([1, 200])
    expect(citedNumbers('A [2]. B [1][2]. C [3, 1].')).toEqual([2, 1, 3])
  })
})

describe('parseMarkdown', () => {
  it('parses lists, headings, tables and code', () => {
    const blocks = parseMarkdown(
      [
        '## Findings',
        '',
        '- First point [1]',
        '- Second point',
        '  continues here',
        '',
        '1. Step one',
        '2. Step two',
        '',
        '| Method | Memory |',
        '|:--|--:|',
        '| LoRA | 60% [2] |',
        '',
        '```python',
        'print("hi")',
        '```',
        'Closing paragraph.',
      ].join('\n'),
    )
    expect(blocks.map((b) => b.type)).toEqual(['heading', 'list', 'list', 'table', 'code', 'paragraph'])
    const [heading, bullets, numbered, table, code] = blocks
    expect(heading).toMatchObject({ level: 2 })
    expect(bullets).toMatchObject({ ordered: false })
    if (bullets.type !== 'list' || numbered.type !== 'list' || table.type !== 'table') throw new Error()
    expect(bullets.items[1]).toEqual([{ type: 'text', text: 'Second point continues here' }])
    expect(numbered).toMatchObject({ ordered: true, start: 1 })
    expect(table.align).toEqual(['left', 'right'])
    expect(table.rows[0][1]).toContainEqual({ type: 'cite', numbers: [2], raw: '[2]' })
    expect(code).toEqual({ type: 'code', lang: 'python', text: 'print("hi")' })
  })

  it('renders an unfinished code fence while the answer is streaming', () => {
    expect(parseMarkdown('Text\n```\npartial')).toEqual([
      { type: 'paragraph', inline: [{ type: 'text', text: 'Text' }] },
      { type: 'code', lang: '', text: 'partial' },
    ])
  })
})
