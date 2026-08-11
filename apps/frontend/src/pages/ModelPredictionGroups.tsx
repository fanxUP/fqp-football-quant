import type { Prediction } from '../core/types';
import { useLanguage } from '../app/LanguageContext';
import DataTable, { type Column } from '../shared/components/DataTable';
import { modelNameLabel } from '../shared/constants';

interface ModelPredictionGroupsProps {
  columns: Column<Prediction>[];
  predictions: Prediction[];
}

interface PredictionGroup {
  modelName: string;
  rows: Prediction[];
}

function groupPredictionsByModel(predictions: Prediction[]): PredictionGroup[] {
  const groups = new Map<string, Prediction[]>();

  predictions.forEach((prediction) => {
    const rows = groups.get(prediction.model_name) ?? [];
    rows.push(prediction);
    groups.set(prediction.model_name, rows);
  });

  return Array.from(groups, ([modelName, rows]) => ({ modelName, rows }));
}

export default function ModelPredictionGroups({ columns, predictions }: ModelPredictionGroupsProps) {
  const { translate } = useLanguage();
  const groups = groupPredictionsByModel(predictions);

  return (
    <section className="model-prediction-groups" aria-label={translate('模型预测明细')}>
      {groups.map((group) => (
        <details className="model-prediction-group" key={group.modelName}>
          <summary>
            <span className="model-prediction-group-title">
              {translate(modelNameLabel(group.modelName))}（{group.rows.length} {translate('条')}）
            </span>
            <span className="model-prediction-group-hint">{translate('展开预测明细')}</span>
          </summary>
          <div className="model-prediction-group-content">
            <DataTable
              columns={columns}
              rows={group.rows}
              emptyText="暂无模型预测数据"
              rowKey={(prediction) => String(prediction.id)}
            />
          </div>
        </details>
      ))}
    </section>
  );
}
