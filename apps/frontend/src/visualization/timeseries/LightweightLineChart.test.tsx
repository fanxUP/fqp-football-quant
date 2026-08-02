import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LightweightLineChart from './LightweightLineChart';

const { addSeries, applyOptions, createChart, fitContent, setData } = vi.hoisted(() => {
  const setDataMock = vi.fn();
  const applyOptionsMock = vi.fn();
  const fitContentMock = vi.fn();
  const addSeriesMock = vi.fn(() => ({
    setData: setDataMock,
    applyOptions: applyOptionsMock,
  }));
  return {
    addSeries: addSeriesMock,
    applyOptions: applyOptionsMock,
    fitContent: fitContentMock,
    setData: setDataMock,
    createChart: vi.fn(() => ({
      addSeries: addSeriesMock,
      removeSeries: vi.fn(),
      remove: vi.fn(),
      resize: vi.fn(),
      timeScale: () => ({ fitContent: fitContentMock }),
    })),
  };
});

vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0 },
  LineSeries: 'LineSeries',
  createChart,
}));

vi.mock('../../app/ThemeContext', () => ({
  useTheme: () => ({ theme: 'redline-quant' }),
}));

describe('LightweightLineChart', () => {
  beforeEach(() => vi.clearAllMocks());

  const series = [
    {
      id: 'home',
      name: '主胜',
      data: [
        { time: 1784019600 as never, value: 1.8 },
        { time: 1784021400 as never, value: 1.82 },
      ],
    },
  ];

  it('创建真实时间轴图表并写入折线数据', () => {
    render(<LightweightLineChart
      series={series}
      ariaLabel="胜平负赔率走势"
      valueSuffix="%"
      valueRange={[0, 100]}
    />);

    expect(createChart).toHaveBeenCalledOnce();
    expect(addSeries).toHaveBeenCalledOnce();
    expect(setData).toHaveBeenCalledWith(series[0].data);
    expect(screen.getByRole('img', { name: '胜平负赔率走势' })).toBeInTheDocument();
    expect(addSeries).toHaveBeenCalledWith('LineSeries', expect.objectContaining({
      priceFormat: expect.objectContaining({ type: 'custom' }),
      autoscaleInfoProvider: expect.any(Function),
    }));
  });

  it('业务图表只允许固定颜色并统一使用实线', () => {
    render(<LightweightLineChart
      series={[{ ...series[0], color: '#123456' }]}
      ariaLabel="模型表现"
    />);

    expect(addSeries).toHaveBeenCalledWith('LineSeries', expect.objectContaining({
      color: '#123456',
      lineStyle: 0,
    }));
  });

  it('图例可通过键盘可访问按钮隐藏与显示折线', () => {
    render(<LightweightLineChart series={series} ariaLabel="胜平负赔率走势" />);

    const legendButton = screen.getByRole('button', { name: '隐藏主胜' });
    fireEvent.click(legendButton);

    expect(applyOptions).toHaveBeenLastCalledWith({ visible: false });
    expect(screen.getByRole('button', { name: '显示主胜' })).toHaveAttribute('aria-pressed', 'false');
    expect(fitContent).toHaveBeenCalledTimes(1);
  });

  it('仅在点击图表后启用滚轮缩放和滚轮平移', () => {
    render(<LightweightLineChart series={series} ariaLabel="胜平负赔率走势" />);

    expect(createChart).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({
      handleScale: expect.objectContaining({ mouseWheel: false }),
      handleScroll: expect.objectContaining({ mouseWheel: false }),
    }));

    fireEvent.click(screen.getByRole('img', { name: '胜平负赔率走势' }));

    expect(createChart).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({
      handleScale: expect.objectContaining({ mouseWheel: true }),
      handleScroll: expect.objectContaining({ mouseWheel: true }),
    }));
    expect(setData).toHaveBeenCalledTimes(2);

    fireEvent.mouseLeave(screen.getByRole('img', { name: '胜平负赔率走势' }));

    expect(createChart).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({
      handleScale: expect.objectContaining({ mouseWheel: false }),
      handleScroll: expect.objectContaining({ mouseWheel: false }),
    }));
    expect(setData).toHaveBeenCalledTimes(3);
  });
});
