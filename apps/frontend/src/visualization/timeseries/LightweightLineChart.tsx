import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import { useTheme } from '../../app/ThemeContext';
import { getChartColors } from '../../theme/chartTokens';
import './LightweightLineChart.css';

export interface LightweightLineSeries {
  id: string;
  name: string;
  data: LineData<Time>[];
  color?: string;
}

interface LightweightLineChartProps {
  series: LightweightLineSeries[];
  ariaLabel: string;
  height?: number;
  valuePrecision?: number;
  valueSuffix?: string;
  valueRange?: readonly [number, number];
}

function formatTime(time: Time): string {
  if (typeof time !== 'number') return String(time);
  return TIME_FORMATTER.format(new Date(time * 1000));
}

const TIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

export default function LightweightLineChart({
  series,
  ariaLabel,
  height = 300,
  valuePrecision = 2,
  valueSuffix = '',
  valueRange,
}: LightweightLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef(new Map<string, ISeriesApi<'Line'>>());
  const { theme } = useTheme();
  const seriesIds = useMemo(() => series.map((item) => item.id).join('|'), [series]);
  const [visibleIds, setVisibleIds] = useState(() => new Set(series.map((item) => item.id)));
  const [interactionsEnabled, setInteractionsEnabled] = useState(false);

  useEffect(() => {
    setVisibleIds(new Set(series.map((item) => item.id)));
  }, [seriesIds]);

  useEffect(() => {
    if (!containerRef.current) return;
    const colors = getChartColors();
    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: colors.textMuted,
        fontFamily: "'JetBrains Mono', 'Noto Sans SC', monospace",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: colors.gridLine },
        horzLines: { color: colors.gridLine },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: colors.gridLine, scaleMargins: { top: 0.12, bottom: 0.12 } },
      timeScale: {
        borderColor: colors.gridLine,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
        tickMarkFormatter: (time: Time) => formatTime(time),
      },
      localization: {
        locale: 'zh-CN',
        priceFormatter: (value: number) => `${value.toFixed(valuePrecision)}${valueSuffix}`,
        timeFormatter: (time: Time) => formatTime(time),
      },
      handleScale: {
        axisPressedMouseMove: interactionsEnabled,
        mouseWheel: interactionsEnabled,
        pinch: interactionsEnabled,
      },
      handleScroll: {
        horzTouchDrag: interactionsEnabled,
        mouseWheel: interactionsEnabled,
        pressedMouseMove: interactionsEnabled,
      },
    });
    chartRef.current = chart;

    const resize = () => {
      if (containerRef.current) chart.resize(containerRef.current.clientWidth, height);
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    if (observer) observer.observe(containerRef.current);
    else window.addEventListener('resize', resize);

    return () => {
      observer?.disconnect();
      if (!observer) window.removeEventListener('resize', resize);
      seriesRef.current.clear();
      chart.remove();
      chartRef.current = null;
    };
  }, [height, interactionsEnabled, theme, valuePrecision, valueSuffix]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const colors = getChartColors();
    const palette = [colors.primary, colors.blue, colors.amber, colors.green, colors.purple, colors.cyan];
    const nextIds = new Set(series.map((item) => item.id));

    seriesRef.current.forEach((api, id) => {
      if (!nextIds.has(id)) {
        chart.removeSeries(api);
        seriesRef.current.delete(id);
      }
    });

    series.forEach((item, index) => {
      let api = seriesRef.current.get(item.id);
      if (!api) {
        api = chart.addSeries(LineSeries, {
          color: item.color ?? palette[index % palette.length],
          lineStyle: LineStyle.Solid,
          lineWidth: 2,
          title: item.name,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
          crosshairMarkerRadius: 4,
          autoscaleInfoProvider: valueRange
            ? () => ({ priceRange: { minValue: valueRange[0], maxValue: valueRange[1] } })
            : undefined,
          priceFormat: valueSuffix
            ? {
                type: 'custom',
                formatter: (value: number) => `${value.toFixed(valuePrecision)}${valueSuffix}`,
                minMove: 10 ** -valuePrecision,
              }
            : { type: 'price', precision: valuePrecision, minMove: 10 ** -valuePrecision },
        });
        seriesRef.current.set(item.id, api);
      }
      api.setData(item.data);
    });

    chart.timeScale().fitContent();
  }, [interactionsEnabled, series, theme, valuePrecision, valueRange, valueSuffix]);

  useEffect(() => {
    seriesRef.current.forEach((api, id) => {
      api.applyOptions({ visible: visibleIds.has(id) });
    });
  }, [visibleIds]);

  const toggleSeries = (id: string) => {
    setVisibleIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      seriesRef.current.get(id)?.applyOptions({ visible: next.has(id) });
      return next;
    });
  };

  const enableInteractions = () => setInteractionsEnabled(true);

  const colors = getChartColors();
  const palette = [colors.primary, colors.blue, colors.amber, colors.green, colors.purple, colors.cyan];

  return (
    <div className="lightweight-line-chart">
      <div className="lightweight-line-legend" aria-label="图例">
        {series.map((item, index) => {
          const visible = visibleIds.has(item.id);
          return (
            <button
              type="button"
              key={item.id}
              className="lightweight-line-legend-item"
              aria-pressed={visible}
              aria-label={`${visible ? '隐藏' : '显示'}${item.name}`}
              onClick={() => toggleSeries(item.id)}
            >
              <span
                className="lightweight-line-legend-swatch"
                style={{ borderTopColor: item.color ?? palette[index % palette.length] }}
                aria-hidden="true"
              />
              {item.name}
            </button>
          );
        })}
      </div>
      <div
        ref={containerRef}
        className={`lightweight-line-canvas${interactionsEnabled ? ' is-interactive' : ''}`}
        role="img"
        aria-label={ariaLabel}
        aria-description={interactionsEnabled ? '已启用滚轮缩放和拖动查看时间' : '点击图表后可使用滚轮缩放和拖动查看时间'}
        data-zoom-enabled={interactionsEnabled}
        tabIndex={0}
        onClick={enableInteractions}
        onMouseLeave={() => setInteractionsEnabled(false)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            enableInteractions();
          }
        }}
        style={{ height }}
      />
    </div>
  );
}
