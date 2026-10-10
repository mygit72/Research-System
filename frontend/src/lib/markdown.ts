/**
 * A small Markdown subset for assistant answers, parsed to data and rendered as React
 * elements (never injected as HTML, so model output can't smuggle in markup).
 *
 * Blocks: paragraphs, headings, bullet/numbered lists, fenced code, pipe tables,
 * block quotes, rules. Inline: **bold**, *italic*, `code`, $math$ and citation
 * markers like [1], [1, 3] or [2-4].
 */

export type Inline =
  | { type: 'text'; text: string }
  | { type: 'strong' | 'em'; children: Inline[] }
  | { type: 'code' | 'math'; text: string }
  | { type: 'cite'; numbers: number[]; raw: string }

export type Block =
  | { type: 'paragraph'; inline: Inline[] }
  | { type: 'heading'; level: number; inline: Inline[] }
  | { type: 'list'; ordered: boolean; start: number; items: Inline[][] }
  | { type: 'code'; lang: string; text: string }
  | { type: 'table'; header: Inline[][]; align: ('left' | 'right' | 'center' | null)[]; rows: Inline[][][] }
  | { type: 'quote'; inline: Inline[] }
  | { type: 'rule' }

const CITE = String.raw`\[(\d+(?:\s*[,–-]\s*\d+)*)\]`
const INLINE = new RegExp(
  [
    String.raw`(\x60+)([\s\S]+?)\1`, // `code`
    String.raw`\$([^\s$](?:[^$\n]*[^\s$])?)\$`, // $math$ (no "$5 and $10")
    String.raw`\*\*([\s\S]+?)\*\*`, // **strong**
    String.raw`__([\s\S]+?)__`,
    String.raw`\*([^\s*](?:[\s\S]*?[^\s*])?)\*`, // *em*
    String.raw`(?<![\w])_([^\s_](?:[\s\S]*?[^\s_])?)_(?![\w])`, // _em_ (not snake_case)
    CITE,
  ].join('|'),
  'g',
)

/** "1, 3" → [1, 3]; "2-4" → [2, 3, 4] (short ranges only, like the backend). */
export function citationNumbers(group: string): number[] {
  const numbers: number[] = []
  for (const part of group.split(/\s*,\s*/)) {
    const bounds = part.split(/\s*[-–]\s*/).map(Number)
    if (bounds.length === 2 && bounds[1] > bounds[0] && bounds[1] - bounds[0] <= 20) {
      for (let n = bounds[0]; n <= bounds[1]; n++) numbers.push(n)
    } else numbers.push(...bounds)
  }
  return [...new Set(numbers)]
}

export function parseInline(text: string): Inline[] {
  const out: Inline[] = []
  let last = 0
  const pushText = (value: string) => {
    if (!value) return
    const previous = out[out.length - 1]
    if (previous?.type === 'text') previous.text += value
    else out.push({ type: 'text', text: value })
  }
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0
    pushText(text.slice(last, index))
    const [raw, , code, math, strong, strong2, em, em2, cite] = match
    if (code !== undefined) out.push({ type: 'code', text: code.trim() })
    else if (math !== undefined) out.push({ type: 'math', text: math })
    else if (strong !== undefined || strong2 !== undefined)
      out.push({ type: 'strong', children: parseInline(strong ?? strong2) })
    else if (em !== undefined || em2 !== undefined)
      out.push({ type: 'em', children: parseInline(em ?? em2) })
    else if (cite !== undefined) out.push({ type: 'cite', numbers: citationNumbers(cite), raw })
    last = index + raw.length
  }
  pushText(text.slice(last))
  return out
}

const LIST_ITEM = /^\s*(?:([-*+•])|(\d+)[.)])\s+(.*)$/
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function cells(row: string): string[] {
  return row
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim().replace(/\\\|/g, '|'))
}

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) blocks.push({ type: 'paragraph', inline: parseInline(paragraph.join('\n')) })
    paragraph = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const fence = /^\s*(```|~~~)\s*([\w+-]*)/.exec(line)
    if (fence) {
      flush()
      const body: string[] = []
      for (i++; i < lines.length && !lines[i].trim().startsWith(fence[1]); i++) body.push(lines[i])
      blocks.push({ type: 'code', lang: fence[2], text: body.join('\n') }) // unclosed while streaming: fine
      continue
    }
    if (!line.trim()) {
      flush()
      continue
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      blocks.push({ type: 'heading', level: heading[1].length, inline: parseInline(heading[2].replace(/\s#+\s*$/, '')) })
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flush()
      blocks.push({ type: 'rule' })
      continue
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      flush()
      const header = cells(line)
      const align = cells(lines[i + 1]).map((c) =>
        c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : c.startsWith(':') ? 'left' : null,
      )
      const rows: Inline[][][] = []
      for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++)
        rows.push(cells(lines[i]).map(parseInline))
      i--
      blocks.push({ type: 'table', header: header.map(parseInline), align, rows })
      continue
    }
    if (/^\s*>/.test(line)) {
      flush()
      const quoted: string[] = []
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) quoted.push(lines[i].replace(/^\s*>\s?/, ''))
      i--
      blocks.push({ type: 'quote', inline: parseInline(quoted.join('\n')) })
      continue
    }
    const item = LIST_ITEM.exec(line)
    if (item) {
      flush()
      const ordered = item[2] !== undefined
      const items: string[] = []
      for (; i < lines.length; i++) {
        const next = LIST_ITEM.exec(lines[i])
        if (next && (next[2] !== undefined) === ordered) items.push(next[3])
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length)
          items[items.length - 1] += ` ${lines[i].trim()}` // continuation line
        else break
      }
      i--
      blocks.push({ type: 'list', ordered, start: ordered ? Number(item[2]) : 1, items: items.map(parseInline) })
      continue
    }
    paragraph.push(line)
  }
  flush()
  return blocks
}

/** Citation numbers used in a text, in order of first use. */
export function citedNumbers(text: string): number[] {
  const numbers = [...text.matchAll(new RegExp(CITE, 'g'))].flatMap((m) => citationNumbers(m[1]))
  return [...new Set(numbers)]
}
