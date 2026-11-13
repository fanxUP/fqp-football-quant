import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import PageHeader from '../shared/components/PageHeader';
import Skeleton from '../shared/components/Skeleton';
import TeamName from '../shared/components/TeamName';
import { statusLabel } from '../shared/constants';
import MatchEvidence from '../features/command-center/MatchEvidence';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import { formatTime } from '../features/command-center/presentation';
import { loadActiveMatches } from '../features/command-center/activeMatches';
import type { MatchCatalogQuery } from '../core/types';
import SceneViewport from '../features/command-center/SceneViewport';
import useMatchCenterState from './useMatchCenterState';
import './MatchesPage.css';

const PAGE_SIZE = 50;
const PitchScene = lazy(() => import('../features/command-center/PitchScene'));

export default function MatchesPage() {
  const [state, update] = useMatchCenterState();
  const { query, league, status, sort, page, selectedId, scope, historyDate } = state;
  const request: MatchCatalogQuery = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, q: query, league, status, sort, scope,
    selected_id: selectedId ?? undefined, ...(scope === 'history' ? { date_from: historyDate, date_to: historyDate } : {}) };
  const requestKey = JSON.stringify(request);
  // Bind each response to its query; a slower earlier query must not replace it.
  const fetchMatches = useCallback(async () => ({ ...await loadActiveMatches(JSON.parse(requestKey)), requestKey }), [requestKey]);
  const list = useReadOnlyResource(fetchMatches, 30_000, true, requestKey);
  const data = list.data?.requestKey === requestKey ? list.data : null;
  const [sceneOpen, setSceneOpen] = useState(false);
  const matches = data?.matches;
  const leagues = [...(data?.leagues ?? [])];
  const statuses = [...(data?.statuses ?? [])];
  // Keep disappearing filter values visible until the user clears them.
  if (league && !leagues.includes(league)) leagues.push(league);
  if (status && !statuses.includes(status)) statuses.push(status);
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));
  const currentPage = data ? Math.floor(data.offset / PAGE_SIZE) + 1 : page;
  useEffect(() => { if (data && page !== currentPage) update({ page: currentPage, warning: state.warning }); }, [data, page, currentPage, state.warning, update]);
  const current = matches ?? [];
  const selected = selectedId === null ? current[0] : current.find(match => match.match_id === selectedId);
  const targetExists = data?.selected_in_scope;
  const filteredActive = Boolean(query || league || status);
  function resetFilters() { update({ query: '', league: '', status: '', page: 1, selectedId: null }); }
  function changePage(next: number) { update({ page: next, selectedId: null }); }
  function selectMatch(id: number) {
    if (current.some(match => match.match_id === id)) update({ selectedId: id });
  }

  return <div className="mc-page">
    <PageHeader title="比赛中心" subtitle="当前赛程与历史档案 · 停售比赛仍保留查看" />
    <section className="mc-toolbar cc-panel" aria-label="赛事筛选">
      <label>赛事范围<select aria-label="赛事范围" value={scope} onChange={event => update({ scope: event.target.value === 'history' ? 'history' : 'current', page: 1, selectedId: null })}><option value="current">当前赛程</option><option value="history">历史档案</option></select></label>
      {scope === 'history' && <label>体彩业务日<input type="date" aria-label="体彩业务日" value={historyDate} onChange={event => { if (event.target.value) update({ historyDate: event.target.value, page: 1, selectedId: null }); }} /></label>}
      <label>搜索赛事<input type="search" placeholder="球队、联赛、赛事 ID 或编号" value={query} onChange={event => update({ query: event.target.value, page: 1, selectedId: null })} /></label>
      <label>联赛<select aria-label="联赛" value={league} onChange={event => update({ league: event.target.value, page: 1, selectedId: null })}><option value="">全部联赛</option>{leagues.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>赛事状态<select aria-label="赛事状态" value={status} onChange={event => update({ status: event.target.value, page: 1, selectedId: null })}><option value="">全部状态</option>{statuses.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
      <label>开球排序<select aria-label="开球排序" value={sort} onChange={event => update({ sort: event.target.value === 'desc' ? 'desc' : 'asc', page: 1, selectedId: null })}><option value="asc">开球时间从早到晚</option><option value="desc">开球时间从晚到早</option></select></label>
      <button type="button" onClick={resetFilters} disabled={!filteredActive}>重置筛选</button>
    </section>
    <div className="mc-fetch-status" role="status">
      <div>{list.error ? <span className="mc-error">{list.error}{data && ' · 保留上次成功数据；本次刷新未成功'}</span> : <span>{list.loading || !data ? '加载赛事…' : '已获取赛事响应'}</span>}
        {list.receivedAt !== null && <span> · 最近获取 {new Date(list.receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}</span>}
      </div><button type="button" onClick={() => void list.refresh()}>刷新赛事</button>
    </div>
    <p className="mc-coverage">{data ? `本页 ${matches!.length} 场 · 筛选总数 ${data.total} 场` : '赛事数量 —'} · {scope === 'current' ? '未来比赛及近48小时内未确认结束的比赛' : '按体彩业务日查看已归档比赛，缺赛果单独标示'} · 最近获取时间不代表来源更新时间</p>
    {state.warning && <p className="mc-target-notice" role="status">{state.warning}</p>}
    {data && selectedId !== null && !selected && <div className="mc-target-notice" role="status">
      <p>{targetExists ? `指定比赛被当前筛选隐藏：#${selectedId}` : `当前查询范围内未找到比赛 #${selectedId}，可切换历史档案或查看详情。`}</p>
      {targetExists && <button type="button" onClick={() => update({ query: '', league: '', status: '', page: 1 })}>清除筛选查看该比赛</button>}
      <a href={`#/matches/${selectedId}`}>查看指定比赛详情</a>
    </div>}
    <section className="mc-scene cc-panel" aria-label="可选 3D 选赛">
      <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH NAVIGATION</span><button type="button" aria-expanded={sceneOpen} aria-controls="mc-pitch" onClick={() => setSceneOpen(open => !open)}>{sceneOpen ? '关闭 3D 选赛' : '打开 3D 选赛'}</button></div>
      {sceneOpen ? <div id="mc-pitch">
        <h3>数字球场</h3>
        <SceneViewport storageKey={null} subject="比赛选择" fallback={<p>可使用下方二维列表选择比赛</p>}>
          {(active, onFailure) => <Suspense fallback={<p role="status">加载 3D 场景…</p>}><PitchScene matches={current} selectedId={selected?.match_id ?? null} onSelect={selectMatch} active={active} onFailure={onFailure} /></Suspense>}
        </SceneViewport>
        <p className="cc-scene-caption">节点按当前页顺序排列，最多展示 24 场；位置只用于赛事导航，不表示球员位置、实力或比赛热度。下方列表始终可用。</p>
      </div> : <p className="cc-muted">默认使用二维列表，按需打开数字球场；不影响比赛分析。</p>}
    </section>
    <div className="mc-workbench">
      <section className="cc-panel mc-list" aria-label="赛事列表">
        <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH CENTER</span><span>{data ? `筛选结果 ${data.total} 场` : '等待数据'}</span></div>
        {list.loading || (!data && !list.error) ? <Skeleton variant="card" height={100} count={5} /> : current.length ? <>
          <ul className="mc-rows" tabIndex={0} aria-label="赛事条目">{current.map(match => <li className={selected?.match_id === match.match_id ? 'is-selected' : ''} key={match.match_id}>
            <div className="mc-row-meta"><strong>{match.match_num_str || `#${match.match_id}`}</strong><span>{match.league_name}</span><span>{formatTime(match.kickoff_time)}</span><span>{match.status_note || statusLabel(match.match_status)}</span>{scope === 'history' && match.result_status && match.result_status !== 'confirmed' && <span>{match.result_status === 'missing' ? '赛果待补' : '赛果待确认'}</span>}</div>
            <div className="mc-teams"><TeamName name={match.home_team_name} /><span className="fqp-versus">VS</span><TeamName name={match.away_team_name} /></div>
            <div className="mc-row-actions"><button type="button" aria-pressed={selected?.match_id === match.match_id} aria-label={`查看分析 ${match.match_num_str || `#${match.match_id}`} ${match.home_team_name} VS ${match.away_team_name}`} onClick={() => selectMatch(match.match_id)}>{selected?.match_id === match.match_id ? '当前分析' : '查看分析'}</button><a href={`#/matches/${match.match_id}`} aria-label={`完整详情 ${match.match_num_str || `#${match.match_id}`}`}>完整详情</a></div>
          </li>)}</ul>
          <nav className="mc-pagination" aria-label="赛事分页"><button type="button" disabled={currentPage === 1} onClick={() => changePage(currentPage - 1)}>上一页</button><span>第 {currentPage} / {pages} 页</span><button type="button" disabled={currentPage === pages} onClick={() => changePage(currentPage + 1)}>下一页</button></nav>
        </> : !list.error && <div className="mc-empty"><h2>{filteredActive ? '没有匹配的赛事' : scope === 'current' ? '暂无当前比赛' : '该业务日暂无历史档案'}</h2><p>{filteredActive ? '可修改搜索条件或重置筛选。' : '可切换查询范围或手动刷新。'}</p></div>}
      </section>
      {selected && <MatchEvidence key={`${selected.match_id}:${selected.home_team_name}:${selected.away_team_name}`} match={selected} />}
    </div>
  </div>;
}
