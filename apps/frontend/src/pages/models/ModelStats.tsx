import { useLanguage } from '../../app/LanguageContext';
import type { PredictionSummary } from '../../core/types';
import Card from '../../shared/components/Card';

interface ModelStatsProps {
  summary: PredictionSummary | null;
  loading: boolean;
}

export default function ModelStats({ summary, loading }: ModelStatsProps) {
  const { language, translate } = useLanguage();
  const latest = summary?.latest_predict_time?.replace('T', ' ').slice(0, 19);
  const entries = [
    [translate('预测总数'), loading ? '…' : String(summary?.total ?? 0), translate('全部有效赛前预测')],
    [translate('模型数量'), loading ? '…' : String(summary?.model_count ?? 0), translate('按模型名称去重')],
    [translate('正 EV 预测'), loading ? '…' : String(summary?.positive_ev_count ?? 0), summary?.total ? `${((summary.positive_ev_count / summary.total) * 100).toFixed(1)}%` : '—'],
    [translate('平均置信度'), loading ? '…' : summary?.avg_confidence == null ? '—' : `${(summary.avg_confidence * 100).toFixed(1)}%`, latest ? `${translate('最新')}：${latest}` : translate('暂无数据')],
  ];
  return (
    <div className="model-stats-grid" aria-label={language === 'en' ? 'Prediction overview' : '预测概览'}>
      {entries.map(([title, value, note], index) => (
        <Card title={title} entranceDelay={index * 60} key={title}>
          <div className="fqp-stat-card model-stat-card">
            <div className="fqp-stat-value">{value}</div>
            <div className="fqp-stat-sub">{note}</div>
          </div>
        </Card>
      ))}
    </div>
  );
}
