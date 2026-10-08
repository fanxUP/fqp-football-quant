import { lazy, Suspense, useMemo, useState } from 'react';
import { api } from '../../core/apiClient';
import type { MatchDetail, TodayMatch } from '../../core/types';
import { optionLabel, statusLabel } from '../../shared/constants';
import useReadOnlyResource from './useReadOnlyResource';
import { formatTime, freshness, latestOdds, percent, predictionGroups, validateMatches } from './presentation';
import SceneViewport from './SceneViewport';
const PitchScene = lazy(() => import('./PitchScene'));

function ResourceNotice({ error, receivedAt, refresh }: { error: string | null; receivedAt: number | null; refresh: () => Promise<void> }) {
  return <div className="cc-resource-notice" role={error ? 'status' : undefined}>
    <span>{error ? `${error}${receivedAt !== null ? ' · 保留上次成功数据' : ''}` : freshness(receivedAt)}{receivedAt !== null && ` · 最近获取 ${new Date(receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}`}</span>
    <button type="button" onClick={() => void refresh()}>刷新</button>
  </div>;
}

function MatchEvidence({ match }: { match: TodayMatch }) {
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
export default function CommandCenter() {
  const list = useReadOnlyResource(async () => {
    const response = await api.matches.active({ limit: 500 });
    return validateMatches(response.matches);
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState('');
  const matches = list.data ?? [];
  const visible = matches.filter(row => `${row.match_num_str} ${row.league_name} ${row.home_team_name} ${row.away_team_name}`.toLowerCase().includes(filter.toLowerCase()));
  const selected = visible.find(row => row.match_id === selectedId) ?? visible[0];
  return <section className="cc-workbench" aria-label="赛事指挥台">
    <div className="cc-match-list cc-panel">
      <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH RADAR</span><span>{list.data ? `${visible.length} / ${matches.length}` : '— / —'}</span></div>
      <h3>赛事雷达</h3><p className="cc-muted">官方未结束比赛 · 上限 500 场</p>
      <label className="cc-label">查找赛事<input type="search" placeholder="球队、联赛或编号" value={filter} onChange={event => setFilter(event.target.value)} /></label>
      <ResourceNotice {...list} />
      <div className="cc-match-scroll">{list.loading ? <p role="status">加载赛事…</p> : !visible.length && !list.error ? <p className="cc-empty">{matches.length ? '没有匹配的赛事' : '暂无未结束比赛'}</p> : visible.map(row => <button type="button" className={`cc-match ${selected?.match_id === row.match_id ? 'is-selected' : ''}`} aria-pressed={selected?.match_id === row.match_id} key={row.match_id} onClick={() => setSelectedId(row.match_id)}>
        <span className="cc-match-meta">{row.match_num_str || `#${row.match_id}`} · {row.league_name}</span><strong>{row.home_team_name}<span className="cc-vs">VS</span>{row.away_team_name}</strong><span className="cc-match-meta">{formatTime(row.kickoff_time)} · {statusLabel(row.match_status)}</span>
      </button>)}</div>
      <a href="#/matches" className="cc-detail-link">进入比赛中心</a>
    </div>
    <div className="cc-stage cc-panel">
      <div className="cc-panel-heading"><span className="cc-eyebrow">PITCH COMMAND</span><span>赛事空间导航</span></div>
      <h3>数字球场</h3>
      <SceneViewport fallback={<div className="cc-pitch-flat" aria-hidden="true"><i className="cc-pitch-circle" /><i className="cc-pitch-half" /><i className="cc-pitch-box cc-pitch-box-left" /><i className="cc-pitch-box cc-pitch-box-right" /></div>}>
        {(active, onFailure) => <Suspense fallback={<div className="cc-empty" role="status">加载 3D 场景…</div>}><PitchScene matches={visible} selectedId={selected?.match_id ?? null} onSelect={setSelectedId} active={active} onFailure={onFailure} /></Suspense>}
      </SceneViewport>
      <p className="cc-scene-caption">节点按列表顺序排列，最多展示 24 场；表示真实赛事入口，不表示球员位置或比赛热度。全部赛事可在左侧选择。</p>
      {selected && <div className="cc-selected-strip"><span>当前赛事</span><strong>{selected.home_team_name} <span className="cc-vs">VS</span> {selected.away_team_name}</strong><span>{selected.match_num_str || `#${selected.match_id}`}</span></div>}
    </div>
    {selected ? <MatchEvidence key={selected.match_id} match={selected} /> : <aside className="cc-evidence cc-panel"><h3>赛事分析</h3><p className="cc-empty">选择真实赛事后查看预测与赔率</p></aside>}
  </section>;
}
