import { lazy, Suspense, useState } from 'react';
import { api } from '../../core/apiClient';
import { statusLabel } from '../../shared/constants';
import useReadOnlyResource from './useReadOnlyResource';
import { formatTime, validateMatches } from './presentation';
import SceneViewport from './SceneViewport';
import MatchEvidence, { ResourceNotice } from './MatchEvidence';
const PitchScene = lazy(() => import('./PitchScene'));

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
