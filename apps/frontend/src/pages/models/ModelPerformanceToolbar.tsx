import { useLanguage } from '../../app/LanguageContext';
import { modelNameLabel } from '../../shared/constants';

interface ModelPerformanceToolbarProps {
  days: number;
  modelNames: string[];
  selectedModels: string[];
  onDaysChange: (days: number) => void;
  onSelectedModelsChange: (models: string[]) => void;
}

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
      <details className="model-filter-menu">
        <summary>{translate('选择模型')} <span>{props.selectedModels.length}</span></summary>
        <div role="group" aria-label={translate('选择模型')}>
          {props.modelNames.map((model) => <label key={model}><input type="checkbox" checked={props.selectedModels.includes(model)} onChange={() => toggleModel(model)} />{translate(modelNameLabel(model))}</label>)}
        </div>
      </details>
    </div>
  );
}
