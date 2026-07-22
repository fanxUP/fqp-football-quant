import { useEffect, useMemo, useRef, useState } from 'react';
import type { ECharts } from 'echarts/core';
import { useTheme } from '../../app/ThemeContext';
import { getChartColors } from '../../theme/chartTokens';
import ChartFrame from '../../visualization/core/ChartFrame';

interface ChartCardProps {
  title: string;
  subtitle?: string;
  option: Record<string, unknown>;
  height?: number;
  loading?: boolean;
  empty?: boolean;
  emptyReason?: string;
  error?: string | null;
  updatedAt?: string;
}

interface RenderConfig {
  option: Record<string, unknown>;
  subtitle?: string;
  title: string;
}

function applyChartOption(instance: ECharts, config: RenderConfig) {
  const textColor = getChartColors().text;
  instance.setOption({
    backgroundColor: 'transparent',
    textStyle: { color: textColor, fontSize: 14 },
    legend: { textStyle: { color: textColor, fontSize: 14 } },
    aria: { show: true, description: config.subtitle ? `${config.title}。${config.subtitle}` : config.title },
    ...config.option,
  }, {
    notMerge: false,
    lazyUpdate: true,
    replaceMerge: ['series'],
  });
}

export default function ChartCard({
  title,
  subtitle,
  option,
  height = 300,
  loading = false,
  empty = false,
  emptyReason,
  error,
  updatedAt,
}: ChartCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ECharts | null>(null);
  const appliedConfigRef = useRef<RenderConfig | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const { theme } = useTheme();
  const effectiveError = error ?? runtimeError;
  const canRender = !loading && !empty && !effectiveError;
  const renderConfig = useMemo(
    () => ({ option, subtitle, title }),
    [option, subtitle, theme, title],
  );
  const latestConfigRef = useRef(renderConfig);
  latestConfigRef.current = renderConfig;

  useEffect(() => {
    if (!canRender || !chartRef.current) return;

    let cancelled = false;
    let observer: ResizeObserver | null = null;
    let resize: (() => void) | null = null;

    void (async () => {
      try {
        const { ensureChartRuntime } = await import('./chartRuntime');
        const runtime = await ensureChartRuntime(latestConfigRef.current.option);
        if (cancelled || !chartRef.current) return;

        const instance = runtime.init(chartRef.current, undefined, { renderer: 'canvas' });
        instanceRef.current = instance;
        resize = () => instance.resize();
        observer = typeof ResizeObserver === 'undefined'
          ? null
          : new ResizeObserver(resize);

        if (observer) observer.observe(chartRef.current);
        else window.addEventListener('resize', resize);

        applyChartOption(instance, latestConfigRef.current);
        appliedConfigRef.current = latestConfigRef.current;
      } catch {
        if (!cancelled) setRuntimeError('图表组件加载失败，请刷新后重试');
      }
    })();

    return () => {
      cancelled = true;
      observer?.disconnect();
      if (!observer && resize) window.removeEventListener('resize', resize);
      instanceRef.current?.dispose();
      instanceRef.current = null;
      appliedConfigRef.current = null;
    };
  }, [canRender]);

  useEffect(() => {
    if (!canRender) return;
    let cancelled = false;

    void (async () => {
      try {
        const { ensureChartRuntime } = await import('./chartRuntime');
        await ensureChartRuntime(renderConfig.option);
        const instance = instanceRef.current;
        if (cancelled || !instance || appliedConfigRef.current === renderConfig) return;
        applyChartOption(instance, renderConfig);
        appliedConfigRef.current = renderConfig;
      } catch {
        if (!cancelled) setRuntimeError('图表组件加载失败，请刷新后重试');
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [canRender, renderConfig]);

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      updatedAt={updatedAt}
      loading={loading}
      empty={empty}
      emptyReason={emptyReason}
      error={effectiveError}
      height={height}
    >
      <div
        ref={chartRef}
        className="fqp-anim-chartReveal"
        role="img"
        aria-label={subtitle ? `${title}。${subtitle}` : title}
        style={{ width: '100%', height }}
      />
    </ChartFrame>
  );
}
