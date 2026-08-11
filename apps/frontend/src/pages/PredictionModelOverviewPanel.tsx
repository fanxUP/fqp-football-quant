import { useEffect, useMemo, useState } from 'react';
import { useLanguage } from '../app/LanguageContext';
import { api } from '../core/apiClient';
import type { CalibrationProfile, CalibrationTrend, PredictionModelRuntimeState } from '../core/types';

const fallbackMetadata = (code: string) => ({
  title: { 'zh-CN': code, en: code }, summary: { 'zh-CN': '模型元数据暂不可用。', en: 'Model metadata is temporarily unavailable.' },
  output: { 'zh-CN': '—', en: '—' }, cadence: { 'zh-CN': '—', en: '—' }, condition: { 'zh-CN': '—', en: '—' }, role: { 'zh-CN': '—', en: '—' },
});

function formatTime(value: string | null, empty: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : empty;
}

function RuntimeStatus({ state }: { state: PredictionModelRuntimeState }) {
  const { translate } = useLanguage();
  return (
    <span className="prediction-model-status" data-status={state.isActive ? 'enabled' : 'disabled'}>
      {translate(state.isActive ? '已启用' : '未启用')}
    </span>
  );
}

export default function PredictionModelOverviewPanel() {
  const { language, translate } = useLanguage();
  const [states, setStates] = useState<PredictionModelRuntimeState[]>([]);
  const [loading, setLoading] = useState(true);
  const [runtimeError, setRuntimeError] = useState(false);
  const [calibrationError, setCalibrationError] = useState(false);
  const [calibrationProfiles, setCalibrationProfiles] = useState<CalibrationProfile[]>([]);
  const [calibrationTrends, setCalibrationTrends] = useState<CalibrationTrend[]>([]);

  const load = () => {
    setLoading(true);
    setRuntimeError(false);
    setCalibrationError(false);
    Promise.allSettled([api.modelOverview(), api.calibrationProfiles()])
      .then(([overviewResult, calibrationResult]) => {
        if (overviewResult.status === 'fulfilled') setStates(overviewResult.value.models);
        else setRuntimeError(true);
        if (calibrationResult.status === 'fulfilled') {
          setCalibrationProfiles(calibrationResult.value.profiles);
          setCalibrationTrends(calibrationResult.value.trends);
        } else {
          setCalibrationProfiles([]);
          setCalibrationTrends([]);
          setCalibrationError(true);
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const titleByCode = useMemo(() => new Map(states.map((state) => [
    state.code,
    state.metadata?.title[language] ?? state.code,
  ])), [language, states]);
  const calibrationTrendByCode = new Map(calibrationTrends.map((trend) => [trend.modelCode, trend]));
  const activeCount = states.filter((state) => state.isActive).length;

  return (
    <details className="prediction-model-overview">
      <summary className="prediction-model-overview-summary">
        <span>
          <span className="appearance-eyebrow">{translate('预测体系')}</span>
          <strong>{translate('预测模型说明')}</strong>
          <small>{translate('模型说明默认收起，运行状态与元数据由后端统一提供。')}</small>
        </span>
        <span className="prediction-model-overview-count">
          {loading ? translate('加载中...') : `${activeCount}/${states.length} ${translate('已启用')}`}
        </span>
      </summary>

      <div className="prediction-model-overview-body">
        <div className="prediction-model-overview-heading">
          <p>{translate('模型只提供概率信号；单一模型不会直接生成投注推荐。')}</p>
          {(runtimeError || calibrationError) && (
            <button type="button" className="fqp-btn fqp-btn-secondary" onClick={load}>{translate('重试')}</button>
          )}
        </div>
        {runtimeError && <p className="prediction-model-runtime-message" role="alert">{translate('运行状态加载失败，模型目录暂不可用。')}</p>}
        {calibrationError && <p className="prediction-model-runtime-message" role="alert">{translate('概率校准记录加载失败，不会伪装成无数据。')}</p>}

        {!loading && calibrationProfiles.length > 0 && (
          <section className="prediction-calibration-monitor" aria-labelledby="prediction-calibration-monitor-title">
            <div>
              <h3 id="prediction-calibration-monitor-title">{translate('概率校准监测')}</h3>
              <p>{translate('仅用于影子评估；达到门槛仍需人工评审，不会自动影响预测、推荐或风控。')}</p>
            </div>
            <div className="prediction-calibration-history" role="list">
              {calibrationProfiles.map((profile) => {
                const trend = calibrationTrendByCode.get(profile.modelCode);
                return (
                  <div className="prediction-calibration-history-row" role="listitem" key={`${profile.modelCode}-${profile.version}`}>
                    <strong>{titleByCode.get(profile.modelCode) ?? profile.modelCode}</strong>
                    <span>{translate('验证样本')} {profile.sampleCount}</span>
                    <span>{profile.logLossBefore.toFixed(3)} → {profile.logLossAfter.toFixed(3)}</span>
                    {trend && <span className="prediction-calibration-trend" data-status={trend.status}>{language === 'en' ? translate(trend.label) : trend.label}</span>}
                    {trend && <span className="prediction-calibration-comparison" data-status={trend.comparison.status}>{language === 'en' ? translate(trend.comparison.label) : trend.comparison.label}</span>}
                    <span className="prediction-calibration-review" data-status={profile.review.status}>{language === 'en' ? translate(profile.review.label) : profile.review.label}</span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        <div className="prediction-model-card-grid" aria-busy={loading}>
          {states.map((state) => {
            const metadata = state.metadata ?? fallbackMetadata(state.code);
            return (
              <article className="prediction-model-card" key={state.code}>
                <div className="prediction-model-card-heading">
                  <h3>{metadata.title[language]}</h3>
                  <RuntimeStatus state={state} />
                </div>
                <p>{metadata.summary[language]}</p>
                <dl>
                  <div><dt>{translate('产出范围')}</dt><dd>{metadata.output[language]}</dd></div>
                  <div><dt>{translate('更新频率')}</dt><dd>{metadata.cadence[language]}</dd></div>
                  <div><dt>{translate('出数条件')}</dt><dd>{metadata.condition[language]}</dd></div>
                  <div><dt>{translate('推荐角色')}</dt><dd>{metadata.role[language]}</dd></div>
                </dl>
                <div className="prediction-model-runtime">
                  <span>{translate('版本')} {state.version ?? '—'}</span>
                  <span>{state.validPredictionMatchCount} {translate('场有效预测')}</span>
                  <span>{translate('最近')}：{formatTime(state.latestPredictionAt, translate('暂无有效预测'))}</span>
                </div>
                {state.calibration && (
                  <div className="prediction-model-calibration" role="status">
                    <strong>{translate('概率校准：影子验证')}</strong>
                    <span>{translate('验证样本')} {state.calibration.sampleCount}</span>
                    <span>{translate('温度')} {state.calibration.temperature.toFixed(2)}</span>
                    <span>{translate('对数损失')} {state.calibration.logLossBefore.toFixed(3)} → {state.calibration.logLossAfter.toFixed(3)}</span>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </details>
  );
}
