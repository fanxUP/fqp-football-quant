import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { EvalModelSummary } from '../../core/types';
import ModelEvaluationPanel from './ModelEvaluationPanel';

const model = (overrides: Partial<EvalModelSummary>): EvalModelSummary => ({
  model_name: 'elo_rating', n: 100, avg_brier: 0.55, avg_logloss: 1.01, avg_rps: 0.2,
  avg_market_probability_move: 0.01, avg_closing_edge: 0.02, avg_odds_clv: null,
  paired_market_samples: 100, brier_improvement_vs_market: 0.03,
  brier_improvement_ci_low: 0.01, brier_improvement_ci_high: 0.05,
  sample_status: 'qualified', is_publishable: true, ...overrides,
});

describe('ModelEvaluationPanel', () => {
  it('正式排名只包含达标模型，并将小样本放入观察区', () => {
    render(<ModelEvaluationPanel models={[
      model({ model_name: 'elo_rating' }),
      model({ model_name: 'xgboost_shadow', n: 24, sample_status: 'monitoring', is_publishable: false, brier_improvement_vs_market: 0.4 }),
    ]} loading={false} error={null} onRetry={vi.fn()} />);
    const formal = screen.getByRole('table', { name: '正式模型排名' });
    expect(within(formal).getByText('Elo 实力评分')).toBeInTheDocument();
    expect(within(formal).queryByText('XGBoost 赛前特征模型')).not.toBeInTheDocument();
    expect(within(formal).getByText('0.0100 ~ 0.0500')).toBeInTheDocument();
    expect(within(formal).getByText('暂未采集')).toBeInTheDocument();
    expect(screen.getByText('观察区')).toBeInTheDocument();
  });

  it('接口失败时提供原位重试', () => {
    const retry = vi.fn();
    render(<ModelEvaluationPanel models={[]} loading={false} error="评估指标加载失败，请稍后重试" onRetry={retry} />);
    screen.getByRole('button', { name: '重试' }).click();
    expect(retry).toHaveBeenCalledOnce();
    expect(screen.getByRole('alert')).toHaveTextContent('评估指标加载失败');
  });
});
