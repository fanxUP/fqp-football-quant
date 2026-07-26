import type { ModelPerformanceSample } from '../../core/types';
import { modelNameLabel, playTypeLabel } from '../../shared/constants';
import { modelOrderIndex } from './modelVisuals';
import './ModelSampleSufficiency.css';

const SAMPLE_PLAY_TYPES = ['all', 'spf', 'rqspf', 'bf', 'zjq', 'bqc'] as const;

interface SampleLevel {
  label: '无样本' | '观察中' | '初步可看' | '样本较稳';
  tone: 'empty' | 'low' | 'medium' | 'high';
}

export function sampleLevel(totalSamples: number): SampleLevel {
  if (totalSamples <= 0) return { label: '无样本', tone: 'empty' };
  if (totalSamples < 30) return { label: '观察中', tone: 'low' };
  if (totalSamples < 100) return { label: '初步可看', tone: 'medium' };
  return { label: '样本较稳', tone: 'high' };
}

interface ModelSampleSufficiencyProps {
  samples: ModelPerformanceSample[];
  modelNames: string[];
  days: number;
}

function playTypeName(playType: string): string {
  return playType === 'all' ? '综合' : playTypeLabel(playType);
}

export default function ModelSampleSufficiency({
  samples,
  modelNames,
  days,
}: ModelSampleSufficiencyProps) {
  const models = [...new Set([...modelNames, ...samples.map((sample) => sample.model_name)])]
    .sort((left, right) => modelOrderIndex(left) - modelOrderIndex(right) || left.localeCompare(right));
  const sampleMap = new Map(
    samples.map((sample) => [`${sample.model_name}:${sample.play_type}`, sample]),
  );

  return (
    <section className="fqp-card model-sample-panel" aria-labelledby="model-sample-title">
      <header className="model-sample-header">
        <div>
          <h3 id="model-sample-title">赛前有效样本</h3>
          <p>
            近 {days} 天、已结算且预测时间早于开赛的有效预测；每个模型×玩法每场只计一次，综合为各玩法合计。分级只衡量样本量，不代表模型有效。
          </p>
        </div>
        <div className="model-sample-legend" aria-label="样本量分级规则">
          <span>&lt;30 观察中</span>
          <span>30–99 初步可看</span>
          <span>≥100 样本较稳</span>
        </div>
      </header>

      {models.length === 0 ? (
        <div className="model-sample-empty" role="status">暂无可评估的赛前样本</div>
      ) : (
        <div className="model-sample-table-wrap">
          <table className="model-sample-table" aria-label="模型与玩法赛前有效样本量">
            <thead>
              <tr>
                <th scope="col">模型</th>
                {SAMPLE_PLAY_TYPES.map((playType) => (
                  <th scope="col" key={playType}>{playTypeName(playType)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((modelName) => (
                <tr key={modelName}>
                  <th scope="row">{modelNameLabel(modelName)}</th>
                  {SAMPLE_PLAY_TYPES.map((playType) => {
                    const sample = sampleMap.get(`${modelName}:${playType}`);
                    const total = sample?.total_samples ?? 0;
                    const level = sampleLevel(total);
                    const detail = sample
                      ? `${sample.settled_dates} 个结算日期 · ${sample.first_date} 至 ${sample.last_date}`
                      : '无已结算赛前预测';
                    return (
                      <td key={playType}>
                        <div className={`model-sample-cell is-${level.tone}`} title={detail}>
                          <strong>{total}</strong>
                          <span>{level.label}</span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
