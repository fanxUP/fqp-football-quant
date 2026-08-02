import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { OddsMovementPoint } from '../../core/types';
import ScoreOddsMatrixCard from './ScoreOddsMatrixCard';

vi.mock('../timeseries/LightweightLineChart', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div data-testid="score-detail-line">{ariaLabel}</div>,
}));

const points: OddsMovementPoint[] = [
  { snapshot_id: 1, snapshot_time: '2026-08-01T10:00:00+08:00', play_type: 'bf', option_code: '0:0', option_name: '0:0', sp_value: 7.2, handicap: null, implied_probability: null, prev_sp_value: null },
  { snapshot_id: 2, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: '0:0', option_name: '0:0', sp_value: 6.8, handicap: null, implied_probability: null, prev_sp_value: 7.2 },
  { snapshot_id: 3, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: '1:0', option_name: '1:0', sp_value: 5.6, handicap: null, implied_probability: null, prev_sp_value: null },
  { snapshot_id: 4, snapshot_time: '2026-08-01T11:00:00+08:00', play_type: 'bf', option_code: 'other_h', option_name: '胜其他', sp_value: 18, handicap: null, implied_probability: null, prev_sp_value: null },
];

describe('ScoreOddsMatrixCard', () => {
  it('以主客进球矩阵展示比分，并在点击后展开单个比分走势', () => {
    render(<ScoreOddsMatrixCard data={points} title="比分走势" subtitle="官方固定奖金" />);

    expect(screen.getByRole('grid', { name: '主客队进球比分' })).toBeInTheDocument();
    expect(screen.getByText('胜其他 SP 18.00')).toBeInTheDocument();
    expect(screen.queryByTestId('score-detail-line')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('gridcell', { name: '比分 0:0，SP 6.80，下调 0.40' }));

    expect(screen.getByTestId('score-detail-line')).toHaveTextContent('0:0 历史赔率走势');
  });
});
