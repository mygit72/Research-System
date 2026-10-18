import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { TransformerVisualizer } from './TransformerVisualizer'

describe('TransformerVisualizer', () => {
  it('recomputes scaled attention and its weighted output for the selected token', async () => {
    render(<TransformerVisualizer />)
    await userEvent.click(screen.getByRole('tab', { name: 'Inside attention' }))

    expect(screen.getByText('Query Q for “model”')).toBeInTheDocument()
    expect(screen.getByText('[0.90, 0.70]')).toBeInTheDocument()
    const modelWeights = screen.getAllByRole('img').map((bar) => bar.getAttribute('aria-label'))
    expect(modelWeights).toHaveLength(4)
    expect(modelWeights.reduce((sum, label) => sum + Number.parseFloat(label ?? ''), 0)).toBeCloseTo(100, 0)

    const modelOutput = screen.getByText(/Weighted output:/).parentElement?.textContent
    await userEvent.click(screen.getByRole('button', { name: 'The' }))

    const selectedQuery = screen.getByText('Query Q for “The”').parentElement
    expect(selectedQuery?.querySelector('code')).toHaveTextContent('[0.20, 0.80]')
    expect(screen.getByText(/Weighted output:/).parentElement?.textContent).not.toBe(modelOutput)
  })

  it('lets readers change tokens and see the causal mask block future attention', async () => {
    const user = userEvent.setup()
    render(<TransformerVisualizer />)
    await user.click(screen.getByRole('tab', { name: 'Intervention lab' }))

    expect(screen.getByRole('figure', { name: /Scaled dot-product attention/ })).toBeInTheDocument()
    expect(screen.getAllByRole('img', { name: /The attends to model:/ })).toHaveLength(2)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Key dimension d_k' }), '64')
    expect(screen.getByText('softmax(QKᵀ / √64)')).toBeInTheDocument()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Attention mask' }), 'causal')
    expect(screen.getAllByRole('img', { name: 'The attends to model: 0.0% (masked)' })).toHaveLength(2)

    const input = screen.getByRole('textbox', { name: 'Input tokens' })
    await user.clear(input)
    await user.type(input, 'Attention changes context')
    expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
      'Query ↓', 'Attention', 'changes', 'context',
      'Query ↓', 'Attention', 'changes', 'context',
    ])
  })
})
