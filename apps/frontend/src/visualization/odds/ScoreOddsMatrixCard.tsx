import { useMemo, useState } from 'react';
import type { OddsMovementPoint } from '../../core/types';
import { arrangeScoreOdds } from '../../features/betting-terminal/scoreOddsLayout';
import ChartFrame from '../core/ChartFrame';
import LightweightLineChart from '../timeseries/LightweightLineChart';
import { buildOddsLineSeries } from './oddsChartData';
import { buildScoreOddsView, type ScoreOddsOption } from './scoreOddsData';
import './ScoreOddsMatrixCard.css';

interface ScoreOddsMatrixCardProps {
  data: OddsMovementPoint[];
  title: string;
  subtitle: string;
  emptyReason?: string;
  anomalyCount?: number;
}

function changeText(option: ScoreOddsOption): string {
  if (option.delta === null || option.delta === 0) return '持平';
  return option.delta < 0 ? `下调 ${Math.abs(option.delta).toFixed(2)}` : `上调 ${option.delta.toFixed(2)}`;
}

export default function ScoreOddsMatrixCard({
  data,
  title,
  subtitle,
  emptyReason,
  anomalyCount = 0,
}: ScoreOddsMatrixCardProps) {
  const view = useMemo(() => buildScoreOddsView(data), [data]);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const scoreByCode = useMemo(() => new Map(
    [...view.exactScores, ...view.otherScores].map((item) => [item.code, item]),
  ), [view.exactScores, view.otherScores]);
  const orderedScores = useMemo(() => arrangeScoreOdds(
    Array.from(scoreByCode.values(), (item) => ({
      option_code: item.code,
      option_name: item.name,
      sp_value: item.currentSp,
    })),
  ).flatMap((layout) => {
    const item = scoreByCode.get(layout.option.option_code);
    return item ? [{ ...layout, item }] : [];
  }), [scoreByCode]);
  const selectedSeries = useMemo(
    () => buildOddsLineSeries(data).filter((item) => item.id === selectedCode),
    [data, selectedCode],
  );
  const context = anomalyCount ? `${subtitle} · 检出 ${anomalyCount} 次异常波动` : subtitle;

  return (
    <ChartFrame
      title={title}
      subtitle={`${context} · 按投注器“更多玩法 → 比分”票面顺序展示`}
      empty={!view.exactScores.length}
      emptyReason={emptyReason || '该玩法暂无官方比分赔率快照'}
      height={380}
    >
      <section className="score-odds-matrix" aria-label="比分赔率">
        <div className="score-odds-ticket-grid" role="group" aria-label="比分选项">
          {orderedScores.map(({ option, label, isWide, item }) => {
            const movement = item.delta === null || item.delta === 0 ? 'flat' : item.delta < 0 ? 'down' : 'up';
            return (
              <button
                type="button"
                key={option.option_code}
                data-score-code={option.option_code}
                aria-pressed={selectedCode === option.option_code}
                aria-label={`比分 ${label} SP ${item.currentSp.toFixed(2)} ${changeText(item)}`}
                className={`score-odds-cell is-${movement}${isWide ? ' is-wide' : ''}${selectedCode === option.option_code ? ' is-selected' : ''}`}
                onClick={() => setSelectedCode(option.option_code)}
              >
                <span>{label}</span>
                <strong>{item.currentSp.toFixed(2)}</strong>
                <small>{changeText(item)}</small>
              </button>
            );
          })}
        </div>

        {selectedSeries.length > 0 && (
          <div className="score-odds-detail" aria-label={`${selectedSeries[0].name} 历史走势`}>
            <p><strong>{selectedSeries[0].name}</strong> 历史赔率走势</p>
            <LightweightLineChart
              series={selectedSeries}
              ariaLabel={`${selectedSeries[0].name} 历史赔率走势`}
              height={240}
              valuePrecision={2}
            />
          </div>
        )}
      </section>
    </ChartFrame>
  );
}
