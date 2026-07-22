import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import ChartCard from './ChartCard';

// ----- Mock the tree-shakeable ECharts core entry ---------------------------

const { mockEnsureRuntime, mockInit, mockInstance } = vi.hoisted(() => {
  const inst = {
    setOption: vi.fn(),
    dispose: vi.fn(),
    resize: vi.fn(),
  };
  return {
    mockEnsureRuntime: vi.fn(),
    mockInit: vi.fn(() => inst),
    mockInstance: inst,
  };
});

vi.mock('./chartRuntime', () => ({
  ensureChartRuntime: mockEnsureRuntime,
}));

// ----- Mock ThemeContext (ChartCard reads theme for textColor) ---------------
let mockTheme = 'redline-quant';
vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: mockTheme, toggleTheme: vi.fn() }),
}));

// ----- Mock Card wrapper ----------------------------------------------------
vi.mock('./Card', () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="card-wrapper">
      <div data-testid="card-body">{children}</div>
    </div>
  ),
}));

// ----- Tests -----------------------------------------------------------------

describe('ChartCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEnsureRuntime.mockResolvedValue({ init: mockInit });
    mockTheme = 'redline-quant';
    document.documentElement.removeAttribute('style');
    document.documentElement.style.setProperty('--fqp-chart-text', '#F5F5F7');
  });

  const baseOption = {
    xAxis: { type: 'category', data: ['A', 'B', 'C'] },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: [1, 2, 3] }],
  };

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------
  describe('rendering', () => {
    it('renders the title via Card', () => {
      render(<ChartCard title="Test Chart" option={baseOption} />);
      expect(screen.getByRole('heading', { name: 'Test Chart' })).toBeTruthy();
    });

    it('renders a chart container div', () => {
      const { container } = render(<ChartCard title="Chart" option={baseOption} />);
      const chartDiv = container.querySelector('div[style]');
      expect(chartDiv).toBeTruthy();
    });

    it('applies the height prop to the chart container', () => {
      const { container } = render(
        <ChartCard title="Tall Chart" option={baseOption} height={450} />,
      );
      const chartDiv = container.querySelector('[style*="height: 450px"]');
      expect(chartDiv).toBeTruthy();
    });

    it('defaults height to 300', () => {
      const { container } = render(
        <ChartCard title="Default Height" option={baseOption} />,
      );
      const chartDiv = container.querySelector('[style*="height: 300px"]');
      expect(chartDiv).toBeTruthy();
    });
  });

  // ------------------------------------------------------------------
  // Loading state
  // ------------------------------------------------------------------
  describe('loading state', () => {
    it('shows loading message when loading=true', () => {
      render(<ChartCard title="Loading Chart" option={baseOption} loading={true} />);
      expect(screen.getByRole('status', { name: '加载图表...' })).toBeTruthy();
    });

    it('does not render chart container when loading', () => {
      const { container } = render(
        <ChartCard title="Loading" option={baseOption} loading={true} />,
      );
      expect(screen.getByRole('status', { name: '加载图表...' })).toBeTruthy();
      // No canvas element should exist (echarts renders to canvas)
      expect(container.querySelector('canvas')).toBeFalsy();
    });
  });

  // ------------------------------------------------------------------
  // Options / theme
  // ------------------------------------------------------------------
  describe('echarts integration', () => {
    it('shows a readable error when the chart runtime cannot load', async () => {
      mockEnsureRuntime.mockRejectedValueOnce(new Error('chunk unavailable'));
      render(<ChartCard title="Broken Chart" option={baseOption} />);

      expect(await screen.findByRole('alert')).toHaveTextContent('图表组件加载失败，请刷新后重试');
      expect(mockInit).not.toHaveBeenCalled();
    });

    it('initialises echarts with the themed option', async () => {
      render(<ChartCard title="Theme Test" option={baseOption} />);
      await waitFor(() => expect(mockInit).toHaveBeenCalledTimes(1));

      const setOptCalls = mockInstance.setOption.mock.calls;
      expect(setOptCalls.length).toBeGreaterThanOrEqual(1);

      const passedOption = setOptCalls[0][0] as Record<string, unknown>;
      expect(passedOption.backgroundColor).toBe('transparent');
      expect(passedOption.textStyle).toEqual({ color: '#F5F5F7', fontSize: 14 });
    });

    it('uses the active theme text token', async () => {
      mockTheme = 'polar-lab';
      document.documentElement.style.setProperty('--fqp-chart-text', '#172033');
      render(<ChartCard title="Light Chart" option={baseOption} />);
      await waitFor(() => expect(mockInstance.setOption).toHaveBeenCalled());
      const passedOption = mockInstance.setOption.mock.calls[0][0] as Record<string, unknown>;
      expect(passedOption.textStyle).toEqual({ color: '#172033', fontSize: 14 });
    });

    it('更新数据时复用图表实例', async () => {
      const { rerender } = render(<ChartCard title="Trend" option={baseOption} />);
      await waitFor(() => expect(mockInstance.setOption).toHaveBeenCalledTimes(1));

      rerender(
        <ChartCard
          title="Trend"
          option={{ ...baseOption, series: [{ type: 'bar', data: [2, 3, 4] }] }}
        />,
      );

      await waitFor(() => expect(mockInstance.setOption).toHaveBeenCalledTimes(2));
      expect(mockInit).toHaveBeenCalledTimes(1);
      expect(mockInstance.dispose).not.toHaveBeenCalled();
    });
  });

  // ------------------------------------------------------------------
  // Cleanup
  // ------------------------------------------------------------------
  describe('cleanup', () => {
    it('disposes instance on unmount', async () => {
      const { unmount } = render(<ChartCard title="Cleanup" option={baseOption} />);
      await waitFor(() => expect(mockInit).toHaveBeenCalledTimes(1));
      unmount();
      expect(mockInstance.dispose).toHaveBeenCalledTimes(1);
    });
  });
});
