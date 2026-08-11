import type { ModelPerformanceSample } from '../../core/types';
import { useLanguage } from '../../app/LanguageContext';
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

  const { translate } = useLanguage();
  const playTypeName = (playType: string) => playType === 'all' ? translate('综合') : translate(playTypeLabel(playType));
  return (
    <details className="fqp-card model-sample-panel">
      <summary className="model-sample-summary"><span id="model-sample-title">{translate('赛前有效样本')}</span><small>{models.length} {translate('个模型')}</small></summary>
      <section aria-labelledby="model-sample-title">
      <header className="model-sample-header">
        <div>
          <p>
            {translate('近')} {days} {translate('天、已结算且预测时间早于开赛的有效预测；每个模型与玩法每场只计一次。分级只衡量样本量，不代表模型有效。')}
          </p>
        </div>
        <div className="model-sample-legend" aria-label={translate('样本量分级规则')}>
          <span>&lt;30 {translate('观察中')}</span>
          <span>30–99 {translate('初步可看')}</span>
          <span>≥100 {translate('样本较稳')}</span>
        </div>
      </header>

      {models.length === 0 ? (
        <div className="model-sample-empty" role="status">{translate('暂无可评估的赛前样本')}</div>
      ) : (
        <div className="model-sample-table-wrap">
          <table className="model-sample-table" aria-label={translate('模型与玩法赛前有效样本量')}>
            <thead>
              <tr>
                <th scope="col">{translate('模型')}</th>
                {SAMPLE_PLAY_TYPES.map((playType) => (
                  <th scope="col" key={playType}>{playTypeName(playType)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {models.map((modelName) => (
                <tr key={modelName}>
                  <th scope="row">{translate(modelNameLabel(modelName))}</th>
                  {SAMPLE_PLAY_TYPES.map((playType) => {
                    const sample = sampleMap.get(`${modelName}:${playType}`);
                    const total = sample?.total_samples ?? 0;
                    const level = sampleLevel(total);
                    const detail = sample
                      ? `${sample.settled_dates} ${translate('个结算日期')} · ${sample.first_date} ${translate('至')} ${sample.last_date}`
                      : translate('无已结算赛前预测');
                    return (
                      <td key={playType}>
                        <div className={`model-sample-cell is-${level.tone}`}>
                          <strong>{total}</strong>
                          <span>{translate(level.label)}</span>
                          <small>{detail}</small>
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
    </details>
  );
}
