import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import PageHeader from '../shared/components/PageHeader';
import Skeleton from '../shared/components/Skeleton';
import TeamName from '../shared/components/TeamName';
import { statusLabel } from '../shared/constants';
import MatchEvidence from '../features/command-center/MatchEvidence';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import { formatTime } from '../features/command-center/presentation';
import { compareKickoff, loadActiveMatches } from '../features/command-center/activeMatches';
import SceneViewport from '../features/command-center/SceneViewport';
import useMatchCenterState from './useMatchCenterState';
import './MatchesPage.css';

const PAGE_SIZE = 50;
const PitchScene = lazy(() => import('../features/command-center/PitchScene'));

export default function MatchesPage() {
  const list = useReadOnlyResource(loadActiveMatches);
  const [state, update] = useMatchCenterState();
  const { query, league, status, sort, page, selectedId } = state;
  const [sceneOpen, setSceneOpen] = useState(false);
  const matches = list.data?.matches;
  const leagues = [...new Set(matches?.map(match => match.league_name) ?? [])].sort();
  const statuses = [...new Set(matches?.map(match => match.match_status) ?? [])].sort();
  // Keep disappearing filter values visible until the user clears them.
  if (league && !leagues.includes(league)) leagues.push(league);
  if (status && !statuses.includes(status)) statuses.push(status);
  const filtered = useMemo(() => (matches ?? []).filter(match => (
    (!league || match.league_name === league) && (!status || match.match_status === status)
    && `${match.match_id} ${match.match_num_str} ${match.league_name} ${match.home_team_name} ${match.away_team_name}`.toLowerCase().includes(query.trim().toLowerCase())
  )).sort((a, b) => compareKickoff(a, b, sort)), [matches, league, status, query, sort]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const selectedIndex = filtered.findIndex(match => match.match_id === selectedId);
  const currentPage = selectedIndex >= 0 ? Math.floor(selectedIndex / PAGE_SIZE) + 1 : Math.min(page, pages);
  useEffect(() => { if (list.data && page !== currentPage) update({ page: currentPage, warning: state.warning }); }, [list.data, page, currentPage, state.warning, update]);
  const current = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = selectedId === null ? current[0] : filtered[selectedIndex];
  const targetExists = matches?.some(match => match.match_id === selectedId);
  const filteredActive = Boolean(query || league || status);
  function resetFilters() { update({ query: '', league: '', status: '', page: 1, selectedId: null }); }
  function changePage(next: number) { update({ page: next, selectedId: null }); }
  function selectMatch(id: number) {
    const index = filtered.findIndex(match => match.match_id === id);
    if (index >= 0) update({ selectedId: id, page: Math.floor(index / PAGE_SIZE) + 1 });
  }

  return <div className="mc-page">
    <PageHeader title="比赛中心" subtitle="体彩官方未结束比赛 · 停售比赛仍保留查看" />
    <section className="mc-toolbar cc-panel" aria-label="赛事筛选">
      <label>搜索赛事<input type="search" placeholder="球队、联赛、赛事 ID 或编号" value={query} onChange={event => update({ query: event.target.value, page: 1, selectedId: null })} /></label>
      <label>联赛<select aria-label="联赛" value={league} onChange={event => update({ league: event.target.value, page: 1, selectedId: null })}><option value="">全部联赛</option>{leagues.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>赛事状态<select aria-label="赛事状态" value={status} onChange={event => update({ status: event.target.value, page: 1, selectedId: null })}><option value="">全部状态</option>{statuses.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
      <label>开球排序<select aria-label="开球排序" value={sort} onChange={event => update({ sort: event.target.value === 'desc' ? 'desc' : 'asc', page: 1, selectedId: null })}><option value="asc">开球时间从早到晚</option><option value="desc">开球时间从晚到早</option></select></label>
      <button type="button" onClick={resetFilters} disabled={!filteredActive}>重置筛选</button>
    </section>
    <div className="mc-fetch-status" role="status">
      <div>{list.error ? <span className="mc-error">{list.error}{list.data && ' · 保留上次成功数据；本次刷新未成功'}</span> : <span>{list.loading ? '加载赛事…' : '已获取赛事响应'}</span>}
        {list.receivedAt !== null && <span> · 最近获取 {new Date(list.receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}</span>}
      </div><button type="button" onClick={() => void list.refresh()}>刷新赛事</button>
    </div>
    <p className="mc-coverage">{list.data ? `已获取 ${matches!.length} 场 · 接口总数 ${list.data.total} 场` : '赛事数量 —'} · 当前接口总数仅为本次返回数量，每次最多获取 500 场；筛选与分页作用于已获取数据，最近获取时间不代表来源更新时间</p>
    {state.warning && <p className="mc-target-notice" role="status">{state.warning}</p>}
    {list.data && selectedId !== null && !selected && <div className="mc-target-notice" role="status">
      <p>{targetExists ? `指定比赛被当前筛选隐藏：#${selectedId}` : `当前未结束列表中未找到比赛 #${selectedId}，可能已结束或不在本次获取范围。`}</p>
      {targetExists && <button type="button" onClick={() => update({ query: '', league: '', status: '', page: 1 })}>清除筛选查看该比赛</button>}
      <a href={`#/matches/${selectedId}`}>查看指定比赛详情</a>
    </div>}
    <section className="mc-scene cc-panel" aria-label="可选 3D 选赛">
      <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH NAVIGATION</span><button type="button" aria-expanded={sceneOpen} aria-controls="mc-pitch" onClick={() => setSceneOpen(open => !open)}>{sceneOpen ? '关闭 3D 选赛' : '打开 3D 选赛'}</button></div>
      {sceneOpen ? <div id="mc-pitch">
        <h3>数字球场</h3>
        <SceneViewport storageKey={null} subject="比赛选择" fallback={<p>可使用下方二维列表选择比赛</p>}>
          {(active, onFailure) => <Suspense fallback={<p role="status">加载 3D 场景…</p>}><PitchScene matches={filtered} selectedId={selected?.match_id ?? null} onSelect={selectMatch} active={active} onFailure={onFailure} /></Suspense>}
        </SceneViewport>
        <p className="cc-scene-caption">节点按筛选后列表顺序排列，最多展示 24 场；位置只用于赛事导航，不表示球员位置、实力或比赛热度。下方列表始终可用。</p>
      </div> : <p className="cc-muted">默认使用二维列表，按需打开数字球场；不影响比赛分析。</p>}
    </section>
    <div className="mc-workbench">
      <section className="cc-panel mc-list" aria-label="未结束赛事列表">
        <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH CENTER</span><span>{list.data ? `筛选结果 ${filtered.length} 场` : '等待数据'}</span></div>
        {list.loading ? <Skeleton variant="card" height={100} count={5} /> : current.length ? <>
          <ul className="mc-rows" tabIndex={0} aria-label="赛事条目">{current.map(match => <li className={selected?.match_id === match.match_id ? 'is-selected' : ''} key={match.match_id}>
            <div className="mc-row-meta"><strong>{match.match_num_str || `#${match.match_id}`}</strong><span>{match.league_name}</span><span>{formatTime(match.kickoff_time)}</span><span>{statusLabel(match.match_status)}</span></div>
            <div className="mc-teams"><TeamName name={match.home_team_name} /><span className="fqp-versus">VS</span><TeamName name={match.away_team_name} /></div>
            <div className="mc-row-actions"><button type="button" aria-pressed={selected?.match_id === match.match_id} aria-label={`查看分析 ${match.match_num_str || `#${match.match_id}`} ${match.home_team_name} VS ${match.away_team_name}`} onClick={() => selectMatch(match.match_id)}>{selected?.match_id === match.match_id ? '当前分析' : '查看分析'}</button><a href={`#/matches/${match.match_id}`} aria-label={`完整详情 ${match.match_num_str || `#${match.match_id}`}`}>完整详情</a></div>
          </li>)}</ul>
          <nav className="mc-pagination" aria-label="赛事分页"><button type="button" disabled={currentPage === 1} onClick={() => changePage(currentPage - 1)}>上一页</button><span>第 {currentPage} / {pages} 页</span><button type="button" disabled={currentPage === pages} onClick={() => changePage(currentPage + 1)}>下一页</button></nav>
        </> : !list.error && <div className="mc-empty"><h2>{matches?.length ? '没有匹配的赛事' : '暂无未结束比赛'}</h2><p>{matches?.length ? '可修改搜索条件或重置筛选。' : '等待官方数据更新，也可手动刷新。'}</p></div>}
      </section>
      {selected && <MatchEvidence key={`${selected.match_id}:${selected.home_team_name}:${selected.away_team_name}`} match={selected} />}
    </div>
  </div>;
}
