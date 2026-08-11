import { useLanguage } from '../../app/LanguageContext';
import { modelNameLabel, playTypeLabel } from '../../shared/constants';

export type PerformancePlayType = 'spf' | 'rqspf' | 'bf' | 'zjq' | 'bqc' | 'all';

interface ModelPerformanceToolbarProps {
  days: number;
  playType: PerformancePlayType;
  modelNames: string[];
  selectedModels: string[];
  onDaysChange: (days: number) => void;
  onPlayTypeChange: (playType: PerformancePlayType) => void;
  onSelectedModelsChange: (models: string[]) => void;
}

const PLAY_TYPES: PerformancePlayType[] = ['spf', 'rqspf', 'bf', 'zjq', 'bqc', 'all'];

export default function ModelPerformanceToolbar(props: ModelPerformanceToolbarProps) {
  const { translate } = useLanguage();
  const toggleModel = (model: string) => {
    const next = props.selectedModels.includes(model)
      ? props.selectedModels.filter((item) => item !== model)
      : [...props.selectedModels, model];
    if (next.length > 0) props.onSelectedModelsChange(next);
  };
  return (
    <div className="model-performance-toolbar" aria-label={translate('模型表现筛选')}>
      <label>{translate('时间范围')}
        <select value={props.days} onChange={(event) => props.onDaysChange(Number(event.target.value))}>
          <option value={30}>{translate('近 30 天')}</option><option value={90}>{translate('近 90 天')}</option><option value={365}>{translate('近 365 天')}</option>
        </select>
      </label>
      <label>{translate('玩法')}
        <select value={props.playType} onChange={(event) => props.onPlayTypeChange(event.target.value as PerformancePlayType)}>
          {PLAY_TYPES.map((playType) => <option value={playType} key={playType}>{playType === 'all' ? translate('跨玩法概览') : playTypeLabel(playType)}</option>)}
        </select>
      </label>
      <details className="model-filter-menu">
        <summary>{translate('选择模型')} <span>{props.selectedModels.length}</span></summary>
        <div role="group" aria-label={translate('选择模型')}>
          {props.modelNames.map((model) => <label key={model}><input type="checkbox" checked={props.selectedModels.includes(model)} onChange={() => toggleModel(model)} />{translate(modelNameLabel(model))}</label>)}
        </div>
      </details>
    </div>
  );
}
