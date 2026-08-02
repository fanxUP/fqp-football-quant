import { useMemo, useState } from 'react';
import type { OddsMovementPoint } from '../../core/types';
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

const GOALS = [0, 1, 2, 3, 4, 5];

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
  const scoreByCode = useMemo(
    () => new Map(view.exactScores.map((item) => [item.code, item])),
    [view.exactScores],
  );
  const selectedSeries = useMemo(
    () => buildOddsLineSeries(data).filter((item) => item.id === selectedCode),
    [data, selectedCode],
  );
  const context = anomalyCount ? `${subtitle} · 检出 ${anomalyCount} 次异常波动` : subtitle;

  return (
    <ChartFrame
      title={title}
      subtitle={`${context} · 颜色表示赔率变化，下降代表市场关注度上升`}
      empty={!view.exactScores.length}
      emptyReason={emptyReason || '该玩法暂无官方比分赔率快照'}
      height={380}
    >
      <section className="score-odds-matrix" aria-label="比分赔率矩阵">
        <div className="score-odds-featured" aria-label="当前热门比分">
          <span className="score-odds-section-label">当前热门</span>
          {view.featuredScores.map((item) => (
            <button
              type="button"
              key={item.code}
              className={`score-odds-featured-item${selectedCode === item.code ? ' is-selected' : ''}`}
              onClick={() => setSelectedCode(item.code)}
            >
              <strong>{item.name}</strong><span>SP {item.currentSp.toFixed(2)}</span>
            </button>
          ))}
        </div>

        <div className="score-odds-grid-wrap">
          <span className="score-odds-axis score-odds-axis-away">客队进球 →</span>
          <span className="score-odds-axis score-odds-axis-home">主队进球 ↓</span>
          <div className="score-odds-grid" role="grid" aria-label="主客队进球比分">
            <span className="score-odds-grid-corner" aria-hidden="true">主\客</span>
            {GOALS.map((goal) => <span key={`away-${goal}`} className="score-odds-grid-header">{goal}</span>)}
            {GOALS.map((homeGoal) => (
              <div className="score-odds-grid-row" role="row" key={homeGoal}>
                <span className="score-odds-grid-header" role="rowheader">{homeGoal}</span>
                {GOALS.map((awayGoal) => {
                  const code = `${homeGoal}:${awayGoal}`;
                  const item = scoreByCode.get(code);
                  if (!item) return <span className="score-odds-grid-empty" key={code}>—</span>;
                  const movement = item.delta === null || item.delta === 0 ? 'flat' : item.delta < 0 ? 'down' : 'up';
                  return (
                    <button
                      type="button"
                      key={code}
                      role="gridcell"
                      aria-pressed={selectedCode === code}
                      aria-label={`比分 ${code}，SP ${item.currentSp.toFixed(2)}，${changeText(item)}`}
                      className={`score-odds-cell is-${movement}${selectedCode === code ? ' is-selected' : ''}`}
                      onClick={() => setSelectedCode(code)}
                    >
                      <strong>{item.currentSp.toFixed(2)}</strong>
                      <small>{changeText(item)}</small>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {view.otherScores.length > 0 && (
          <div className="score-odds-other" aria-label="其他比分">
            <span className="score-odds-section-label">其他比分</span>
            {view.otherScores.map((item) => <span key={item.code}>{item.name} SP {item.currentSp.toFixed(2)}</span>)}
          </div>
        )}

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
