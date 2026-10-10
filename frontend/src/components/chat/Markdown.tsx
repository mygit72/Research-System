import { Fragment, useMemo, type ReactNode } from 'react'
import { parseMarkdown, type Block, type Inline } from '@/lib/markdown'

type RenderCite = (numbers: number[], raw: string, key: string) => ReactNode

function InlineNodes({ nodes, renderCite, prefix }: { nodes: Inline[]; renderCite: RenderCite; prefix: string }) {
  return (
    <>
      {nodes.map((node, i) => {
        const key = `${prefix}.${i}`
        switch (node.type) {
          case 'text':
            return <Fragment key={key}>{node.text}</Fragment>
          case 'strong':
            return (
              <strong key={key} className="font-semibold text-text">
                <InlineNodes nodes={node.children} renderCite={renderCite} prefix={key} />
              </strong>
            )
          case 'em':
            return (
              <em key={key}>
                <InlineNodes nodes={node.children} renderCite={renderCite} prefix={key} />
              </em>
            )
          case 'code':
            return (
              <code key={key} className="rounded-sm bg-surface-muted px-1 py-0.5 font-mono text-[0.85em]">
                {node.text}
              </code>
            )
          case 'math':
            // Shown as written (LaTeX source); typeset rendering isn't included yet.
            return (
              <span key={key} className="font-mono text-[0.9em] text-text" title="Math (LaTeX)">
                {node.text}
              </span>
            )
          case 'cite':
            return renderCite(node.numbers, node.raw, key)
        }
      })}
    </>
  )
}

function BlockNode({ block, renderCite, index }: { block: Block; renderCite: RenderCite; index: number }) {
  const inline = (nodes: Inline[], prefix: string) => (
    <InlineNodes nodes={nodes} renderCite={renderCite} prefix={prefix} />
  )
  switch (block.type) {
    case 'paragraph':
      return <p className="whitespace-pre-line">{inline(block.inline, `${index}`)}</p>
    case 'heading': {
      const Tag = (['h3', 'h3', 'h4', 'h5', 'h6', 'h6'] as const)[block.level - 1]
      return <Tag className="pt-1 text-body font-semibold text-text">{inline(block.inline, `${index}`)}</Tag>
    }
    case 'list': {
      const items = block.items.map((item, i) => <li key={i}>{inline(item, `${index}.${i}`)}</li>)
      return block.ordered ? (
        <ol start={block.start} className="list-decimal space-y-1 pl-5 marker:text-muted">
          {items}
        </ol>
      ) : (
        <ul className="list-disc space-y-1 pl-5 marker:text-subtle">{items}</ul>
      )
    }
    case 'code':
      return (
        <pre className="overflow-x-auto rounded-md border border-border bg-surface-muted p-3 font-mono text-caption leading-relaxed">
          <code>{block.text}</code>
        </pre>
      )
    case 'table':
      return (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-small">
            <thead className="bg-surface-muted text-left">
              <tr>
                {block.header.map((cell, i) => (
                  <th key={i} className="px-3 py-2 font-medium text-text" style={{ textAlign: block.align[i] ?? undefined }}>
                    {inline(cell, `${index}.h${i}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r} className="border-t border-border">
                  {row.map((cell, i) => (
                    <td key={i} className="px-3 py-2 align-top" style={{ textAlign: block.align[i] ?? undefined }}>
                      {inline(cell, `${index}.${r}.${i}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    case 'quote':
      return (
        <blockquote className="border-l-2 border-border-strong pl-3 whitespace-pre-line text-muted">
          {inline(block.inline, `${index}`)}
        </blockquote>
      )
    case 'rule':
      return <hr className="border-border" />
  }
}

export function Markdown({ text, renderCite }: { text: string; renderCite: RenderCite }) {
  const blocks = useMemo(() => parseMarkdown(text), [text])
  return (
    <div className="space-y-3 text-body leading-relaxed text-text">
      {blocks.map((block, i) => (
        <BlockNode key={i} block={block} renderCite={renderCite} index={i} />
      ))}
    </div>
  )
}
