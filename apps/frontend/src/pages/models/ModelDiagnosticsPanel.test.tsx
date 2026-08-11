import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ModelDiagnosticsPanel from './ModelDiagnosticsPanel';

const apiMocks = vi.hoisted(() => ({ calibration: vi.fn(), conditionPerformance: vi.fn(), modelCompare: vi.fn(), recommendations: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { analysis: apiMocks } }));

describe('ModelDiagnosticsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.calibration.mockResolvedValue({ status: 'ok', model_name: 'elo_rating', bins: [{ bin_center: 0.5, pred_mean: 0.5, actual_freq: 0.45, count: 20 }], ece: 0.05, mce: 0.08, n_predictions: 100 });
    apiMocks.conditionPerformance.mockResolvedValue({ status: 'ok', dimension: 'league', segments: [] });
    apiMocks.modelCompare.mockResolvedValue({ status: 'ok', models: [], total_models: 0, radar_dimensions: [] });
    apiMocks.recommendations.mockResolvedValue({ status: 'ok', recommendations: [] });
  });

  it('按需读取校准和条件切片接口', async () => {
    render(<ModelDiagnosticsPanel modelNames={['elo_rating']} />);
    expect(await screen.findByText('0.0500')).toBeInTheDocument();
    expect(apiMocks.calibration).toHaveBeenCalledWith({ model_name: 'elo_rating' });
    fireEvent.click(screen.getByRole('tab', { name: '条件切片' }));
    expect(await screen.findByText('当前切片没有足够样本')).toBeInTheDocument();
    expect(apiMocks.conditionPerformance).toHaveBeenCalledWith('league');
  });

  it('接口失败时显示错误并允许重试', async () => {
    apiMocks.calibration.mockRejectedValueOnce(new Error('offline'));
    render(<ModelDiagnosticsPanel modelNames={['elo_rating']} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('诊断数据加载失败');
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(apiMocks.calibration).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('0.0500')).toBeInTheDocument();
  });
});
