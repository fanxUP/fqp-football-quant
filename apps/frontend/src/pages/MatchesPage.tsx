import { useEffect, useMemo, useState } from 'react';
import { api } from '../core/apiClient';
import PageHeader from '../shared/components/PageHeader';
import Skeleton from '../shared/components/Skeleton';
import TeamName from '../shared/components/TeamName';
import { statusLabel } from '../shared/constants';
import MatchEvidence from '../features/command-center/MatchEvidence';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import { formatTime, validateMatches } from '../features/command-center/presentation';
import './MatchesPage.css';

const PAGE_SIZE = 50;
function kickoffValue(time: string) {
  const normalized = time.replace(' ', 'T');
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(normalized) ? normalized : `${normalized}+08:00`).valueOf();
}

export default function MatchesPage() {
  const list = useReadOnlyResource(async () => {
    const response = await api.matches.active({ limit: 500 });
    const matches = validateMatches(response.matches);
    if (matches.some(match => typeof match.match_status !== 'string' || (match.match_num_str != null && typeof match.match_num_str !== 'string'))) throw new Error('赛事状态或编号格式异常');
    if (matches.length > 500 || !Number.isSafeInteger(response.total) || response.total < matches.length) {
      throw new Error('赛事数量格式异常');
    }
    return { matches, total: response.total };
  });
  const [query, setQuery] = useState('');
  const [league, setLeague] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('asc');
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const matches = list.data?.matches;
  const leagues = [...new Set(matches?.map(match => match.league_name) ?? [])].sort();
  const statuses = [...new Set(matches?.map(match => match.match_status) ?? [])].sort();
  // Keep disappearing filter values visible until the user clears them.
  if (league && !leagues.includes(league)) leagues.push(league);
  if (status && !statuses.includes(status)) statuses.push(status);
  const filtered = useMemo(() => (matches ?? []).filter(match => (
    (!league || match.league_name === league) && (!status || match.match_status === status)
    && `${match.match_id} ${match.match_num_str} ${match.league_name} ${match.home_team_name} ${match.away_team_name}`.toLowerCase().includes(query.trim().toLowerCase())
  )).sort((a, b) => {
    const left = kickoffValue(a.kickoff_time), right = kickoffValue(b.kickoff_time);
    if (!Number.isFinite(left) || !Number.isFinite(right)) {
      return Number.isFinite(left) ? -1 : Number.isFinite(right) ? 1 : a.match_id - b.match_id;
    }
    return (sort === 'desc' ? right - left : left - right) || a.match_id - b.match_id;
  }), [matches, league, status, query, sort]);
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  useEffect(() => { if (page > pages) setPage(pages); }, [page, pages]);
  const current = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const selected = current.find(match => match.match_id === selectedId) ?? current[0];
  const filteredActive = Boolean(query || league || status);
  function resetFilters() { setQuery(''); setLeague(''); setStatus(''); setPage(1); }
  function changePage(next: number) { setPage(next); setSelectedId(null); }

  return <div className="mc-page">
    <PageHeader title="比赛中心" subtitle="体彩官方未结束比赛 · 停售比赛仍保留查看" />
    <section className="mc-toolbar cc-panel" aria-label="赛事筛选">
      <label>搜索赛事<input type="search" placeholder="球队、联赛、赛事 ID 或编号" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} /></label>
      <label>联赛<select aria-label="联赛" value={league} onChange={event => { setLeague(event.target.value); setPage(1); }}><option value="">全部联赛</option>{leagues.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>赛事状态<select aria-label="赛事状态" value={status} onChange={event => { setStatus(event.target.value); setPage(1); }}><option value="">全部状态</option>{statuses.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
      <label>开球排序<select aria-label="开球排序" value={sort} onChange={event => { setSort(event.target.value); setPage(1); }}><option value="asc">开球时间从早到晚</option><option value="desc">开球时间从晚到早</option></select></label>
      <button type="button" onClick={resetFilters} disabled={!filteredActive}>重置筛选</button>
    </section>
    <div className="mc-fetch-status" role="status">
      <div>{list.error ? <span className="mc-error">{list.error}{list.data && ' · 保留上次成功数据；本次刷新未成功'}</span> : <span>{list.loading ? '加载赛事…' : '已获取赛事响应'}</span>}
        {list.receivedAt !== null && <span> · 最近获取 {new Date(list.receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}</span>}
      </div><button type="button" onClick={() => void list.refresh()}>刷新赛事</button>
    </div>
    <p className="mc-coverage">{list.data ? `已获取 ${matches!.length} 场 · 接口总数 ${list.data.total} 场` : '赛事数量 —'} · 当前接口总数仅为本次返回数量，每次最多获取 500 场；筛选与分页作用于已获取数据，最近获取时间不代表来源更新时间</p>
    <div className="mc-workbench">
      <section className="cc-panel mc-list" aria-label="未结束赛事列表">
        <div className="cc-panel-heading"><span className="cc-eyebrow">MATCH CENTER</span><span>{list.data ? `筛选结果 ${filtered.length} 场` : '等待数据'}</span></div>
        {list.loading ? <Skeleton variant="card" height={100} count={5} /> : current.length ? <>
          <ul className="mc-rows" tabIndex={0} aria-label="赛事条目">{current.map(match => <li className={selected?.match_id === match.match_id ? 'is-selected' : ''} key={match.match_id}>
            <div className="mc-row-meta"><strong>{match.match_num_str || `#${match.match_id}`}</strong><span>{match.league_name}</span><span>{formatTime(match.kickoff_time)}</span><span>{statusLabel(match.match_status)}</span></div>
            <div className="mc-teams"><TeamName name={match.home_team_name} /><span className="fqp-versus">VS</span><TeamName name={match.away_team_name} /></div>
            <div className="mc-row-actions"><button type="button" aria-pressed={selected?.match_id === match.match_id} aria-label={`查看分析 ${match.match_num_str || `#${match.match_id}`} ${match.home_team_name} VS ${match.away_team_name}`} onClick={() => setSelectedId(match.match_id)}>{selected?.match_id === match.match_id ? '当前分析' : '查看分析'}</button><a href={`#/matches/${match.match_id}`} aria-label={`完整详情 ${match.match_num_str || `#${match.match_id}`}`}>完整详情</a></div>
          </li>)}</ul>
          <nav className="mc-pagination" aria-label="赛事分页"><button type="button" disabled={currentPage === 1} onClick={() => changePage(currentPage - 1)}>上一页</button><span>第 {currentPage} / {pages} 页</span><button type="button" disabled={currentPage === pages} onClick={() => changePage(currentPage + 1)}>下一页</button></nav>
        </> : !list.error && <div className="mc-empty"><h2>{matches?.length ? '没有匹配的赛事' : '暂无未结束比赛'}</h2><p>{matches?.length ? '可修改搜索条件或重置筛选。' : '等待官方数据更新，也可手动刷新。'}</p></div>}
      </section>
      {selected && <MatchEvidence key={`${selected.match_id}:${selected.home_team_name}:${selected.away_team_name}`} match={selected} />}
    </div>
  </div>;
}
