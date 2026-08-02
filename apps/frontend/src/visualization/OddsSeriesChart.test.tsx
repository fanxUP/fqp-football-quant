import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { OddsMovementPoint } from '../core/types';
import OddsSeriesChart from './OddsSeriesChart';

vi.mock('./odds/OddsLineSeriesCard', () => ({
  default: ({ playType }: { playType: string }) => <div data-testid="odds-line">{playType}</div>,
}));

vi.mock('./odds/OddsHeatmapCard', () => ({
  default: ({ playType }: { playType: string }) => <div data-testid="odds-heatmap">{playType}</div>,
}));

vi.mock('./odds/ScoreOddsMatrixCard', () => ({
  default: () => <div data-testid="odds-score-matrix" />,
}));

vi.mock('../shared/components/ChartCard', () => ({
  default: () => <div data-testid="legacy-echarts" />,
}));

const point: OddsMovementPoint = {
  snapshot_id: 1,
  snapshot_time: '2026-07-14T17:30:00+08:00',
  play_type: 'spf',
  option_code: 'h',
  option_name: '主胜',
  sp_value: 1.8,
  handicap: null,
  implied_probability: 0.56,
  prev_sp_value: null,
};

describe('OddsSeriesChart', () => {
  it('普通玩法使用 Lightweight Charts 时间线', async () => {
    render(
      <OddsSeriesChart data={[point]} playType="spf" title="测试" subtitle="胜平负" />,
    );

    expect(await screen.findByTestId('odds-line')).toHaveTextContent('spf');
    expect(screen.queryByTestId('odds-heatmap')).not.toBeInTheDocument();
  });

  it('比分使用比分矩阵，半全场保留热力图', async () => {
    render(
      <OddsSeriesChart data={[{ ...point, play_type: 'bf' }]} playType="bf" title="测试" subtitle="比分" />,
    );

    expect(await screen.findByTestId('odds-score-matrix')).toBeInTheDocument();
    expect(screen.queryByTestId('odds-heatmap')).not.toBeInTheDocument();
    expect(screen.queryByTestId('odds-line')).not.toBeInTheDocument();
  });
});
