import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ReviewDateIndex from './ReviewDateIndex';

const dates = [
  '2026-08-12',
  '2026-08-11',
  '2026-08-10',
  '2026-08-09',
  '2026-08-08',
  '2026-08-07',
  '2026-08-06',
  '2026-08-05',
  '2026-08-04',
];

describe('ReviewDateIndex', () => {
  it('日期按钮使用年-月-日完整格式', () => {
    render(<ReviewDateIndex dates={dates} selectedDate={null} onSelect={vi.fn()} />);

    expect(screen.getByText('2026-08-12')).toBeInTheDocument();
    expect(screen.queryByText('08.12')).not.toBeInTheDocument();
  });

  it('每次只展示一组七个日报日期，并可整周切换到更早日期', async () => {
    const user = userEvent.setup();
    render(<ReviewDateIndex dates={dates} selectedDate={null} onSelect={vi.fn()} />);

    expect(screen.getAllByRole('button', { name: /查看 2026-08-/ })).toHaveLength(7);
    expect(screen.getByRole('button', { name: '查看 2026-08-12 日报' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '查看 2026-08-05 日报' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '查看较早一周' }));

    expect(screen.getAllByRole('button', { name: /查看 2026-08-/ })).toHaveLength(2);
    expect(screen.getByRole('button', { name: '查看 2026-08-05 日报' })).toBeInTheDocument();
    expect(screen.getByText('第 2 / 2 周')).toBeInTheDocument();
  });

  it('点击日期后传回完整日期并标记当前选择', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(
      <ReviewDateIndex dates={dates} selectedDate={null} onSelect={onSelect} />,
    );

    await user.click(screen.getByRole('button', { name: '查看 2026-08-09 日报' }));
    expect(onSelect).toHaveBeenCalledWith('2026-08-09');

    rerender(<ReviewDateIndex dates={dates} selectedDate="2026-08-09" onSelect={onSelect} />);
    expect(screen.getByRole('button', { name: '查看 2026-08-09 日报' })).toHaveAttribute('aria-pressed', 'true');
  });
});
