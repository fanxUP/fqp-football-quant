import { useMemo, useState } from 'react';
import { api } from '../../core/apiClient';
import type { MatchDetail, TodayMatch } from '../../core/types';
import { optionLabel, statusLabel } from '../../shared/constants';
import useReadOnlyResource from './useReadOnlyResource';
import { formatTime, freshness, latestOdds, percent, predictionGroups } from './presentation';

export function ResourceNotice({ error, receivedAt, refresh }: { error: string | null; receivedAt: number | null; refresh: () => Promise<void> }) {
  return <div className="cc-resource-notice" role={error ? 'status' : undefined}>
    <span>{error ? `${error}${receivedAt !== null ? ' · 保留上次成功数据' : ''}` : freshness(receivedAt)}{receivedAt !== null && ` · 最近获取 ${new Date(receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}`}</span>
    <button type="button" onClick={() => void refresh()}>刷新</button>
  </div>;
}

export default function MatchEvidence({ match }: { match: TodayMatch }) {
  const detail = useReadOnlyResource(async () => {
    const response = await api.matches.detail(match.match_id);
    if (response?.match?.id !== match.match_id) throw new Error('赛事 ID 不一致，已停止展示');
    if (response.match.home_team_name !== match.home_team_name || response.match.away_team_name !== match.away_team_name) throw new Error('球队信息不一致，已停止展示');
    if (response.predictions && !Array.isArray(response.predictions.models)) throw new Error('预测证据格式异常');
    return response;
  });
  const odds = useReadOnlyResource(async () => {
    const response = await api.official.oddsSnapshots(match.match_id);
    if (!Array.isArray(response.snapshots)) throw new Error('赔率数据格式异常');
    return latestOdds(response.snapshots, match.match_id);
  });
  return <aside className="cc-evidence cc-panel" aria-label="所选赛事分析">
    <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH EVIDENCE</span><span className="cc-id">#{match.match_id}</span></div>
    <h3>{match.home_team_name}<span className="cc-vs">VS</span>{match.away_team_name}</h3>
    <p className="cc-muted">{match.league_name} · {formatTime(match.kickoff_time)} · {statusLabel(match.match_status)}</p>
    <ResourceNotice {...detail} />
    {detail.loading ? <p className="cc-muted" role="status">加载赛事证据…</p> : detail.data && <PredictionEvidence detail={detail.data} />}
    <h4>官方胜平负赔率</h4>
    <ResourceNotice {...odds} />
    {odds.loading ? <p className="cc-muted">加载官方赔率…</p> : odds.data?.length ? <>
      <div className="cc-odds-grid">{odds.data.map(row => <div key={`${row.id}-${row.option_code}`}><span>{optionLabel('spf', row.option_code)}</span><strong>{typeof row.sp_value === 'number' && Number.isFinite(row.sp_value) && row.sp_value > 0 ? row.sp_value.toFixed(2) : '—'}</strong><span>记录 #{row.id}</span><span>{row.is_open ? '记录为开盘' : '记录为关闭'}</span></div>)}</div>
      <p className="cc-muted">快照时间 {formatTime(odds.data[0].snapshot_time)} · 从最近 200 条官方记录中展示此时间实际存在的选项，不补齐缺失赔率</p>
    </> : !odds.error && <p className="cc-empty">暂无官方赔率快照</p>}
    <a className="cc-detail-link" href={`#/matches/${match.match_id}`}>完整比赛详情</a>
  </aside>;
}
function PredictionEvidence({ detail }: { detail: MatchDetail }) {
  const groups = useMemo(() => predictionGroups(detail.predictions?.models ?? []), [detail]);
  const [selected, setSelected] = useState('');
  const group = groups.find(value => value.key === selected) ?? groups[0];
  return <section aria-label="模型预测证据">
    <h4>模型概率</h4>
    {!group ? <p className="cc-empty">暂无模型预测</p> : <>
      <label className="cc-label">模型 / 玩法 / 预测时间<select className="fqp-select" value={group.key} onChange={event => setSelected(event.target.value)}>{groups.map(value => <option key={value.key} value={value.key}>{value.model} · {value.play} · {formatTime(value.time)}</option>)}</select></label>
      <div className="cc-probabilities">{group.rows.map((row, index) => <div key={`${row.option_code}-${index}`}><span>{optionLabel(row.play_type, row.option_code)}</span><strong>{percent(row.model_probability)}</strong><div className="cc-probability-track" aria-hidden="true"><i style={{ width: percent(row.model_probability) === '—' ? '0%' : percent(row.model_probability) }} /></div></div>)}</div>
      <p className="cc-muted">预测于 {formatTime(group.time)} · {group.play} · 同一模型与时间；不是实时赛况</p>
    </>}
  </section>;
}
