import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import BusinessInterpretationPanel from './BusinessInterpretationPanel';

describe('BusinessInterpretationPanel', () => {
  it('only invokes the supplied manual action and labels output as untrusted', async () => {
    const run = vi.fn().mockResolvedValue({ task: { id: 42, response: '需人工核验的解读。' } });
    render(<BusinessInterpretationPanel title="赛前解读" onRun={run} />);

    fireEvent.change(screen.getByLabelText('关注问题（可选）'), { target: { value: '核对赔率变化' } });
    fireEvent.click(screen.getByRole('button', { name: '生成赛前解读' }));

    expect(await screen.findByText('需人工核验的解读。')).toBeInTheDocument();
    expect(run).toHaveBeenCalledWith('核对赔率变化');
    expect(screen.getByText('模型输出仅供人工核验')).toBeInTheDocument();
  });
});
