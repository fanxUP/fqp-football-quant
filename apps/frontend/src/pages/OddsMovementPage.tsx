/** Bounded, query-isolated official odds evidence. */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { OddsMovementsResponse } from '../core/types';
import Card from '../shared/components/Card';
import EmptyState from '../shared/components/EmptyState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import PageHeader from '../shared/components/PageHeader';
import useReadOnlyResource from '../features/command-center/useReadOnlyResource';
import { formatTimestamp } from '../shared/utils';
import OddsDateIndex from './odds/OddsDateIndex';
import OddsMatchCard from './odds/OddsMatchCard';
import './BusinessEvidence.css';

type PlayTab = 'spf' | 'rqspf' | 'bf' | 'zjq' | 'bqc';
type Scope = 'current' | 'history';
const PLAY_LABELS: Record<PlayTab, string> = { spf: '胜平负', rqspf: '让球胜平负', bf: '比分', zjq: '总进球', bqc: '半全场' };
const CAPTURE_LABELS: Record<string, string> = { running: '采集中', complete: '采集完整', partial: '部分缺失', not_offered: '官方未开售', failed: '采集失败', pending: '待首次采集' };

export default function OddsMovementPage() {
  const [scope, setScope] = useState<Scope>('current');
  const [businessDate, setBusinessDate] = useState<string>();
  const [activePlay, setActivePlay] = useState<PlayTab>('spf');
  const fetchIndex = useCallback(async () => {
    const value = await api.official.oddsIndex();
    if (!value || !Number.isSafeInteger(value.current?.count) || value.current.count < 0 || !Array.isArray(value.history)
      || value.history.some(item => !/^\d{4}-\d{2}-\d{2}$/.test(item.business_date) || !Number.isSafeInteger(item.match_count) || item.match_count < 0)
      || new Set(value.history.map(item => item.business_date)).size !== value.history.length) throw new Error('赔率日期索引格式不正确');
    return value;
  }, []);
  const index = useReadOnlyResource(fetchIndex);
  return (
    <div className="be-page">
      <PageHeader title="赔率走势" subtitle="官方赔率快照 · 日期与玩法独立查询 · 当前数据每 30 秒检查" />
      <Card style={{ marginBottom: 20 }}>
        {index.loading && <p>加载赔率日期索引...</p>}
        {index.error && <p className="be-error" role="status">日期索引：{index.error}{index.data ? '，保留上次索引' : ''}</p>}
        {index.data && <OddsDateIndex index={index.data} scope={scope} businessDate={businessDate}
          onCurrent={() => { setScope('current'); setBusinessDate(undefined); }}
          onHistory={date => { setScope('history'); setBusinessDate(date); }} />}
        <div className="be-actions"><button type="button" onClick={() => void index.refresh()}>刷新日期索引</button></div>
        <div className="be-actions" role="tablist" aria-label="赔率玩法">
          {(Object.keys(PLAY_LABELS) as PlayTab[]).map(play => (
            <button type="button" role="tab" aria-selected={activePlay === play} key={play}
              onClick={() => setActivePlay(play)}>{PLAY_LABELS[play]}</button>
          ))}
        </div>
      </Card>
      <OddsQuery key={`${scope}:${businessDate ?? ''}:${activePlay}`} scope={scope} businessDate={businessDate} play={activePlay} />
    </div>
  );
}

function validateResponse(value: OddsMovementsResponse, scope: Scope, businessDate: string | undefined, play: PlayTab) {
  if (!value || value.scope !== scope || value.business_date !== (businessDate ?? null) || value.play_type !== play
    || value.resolution !== (scope === 'history' ? 'hour' : 'raw')) throw new Error('赔率响应与当前查询不一致');
  if (!Array.isArray(value.matches) || value.matches.length > 200 || !Number.isSafeInteger(value.total) || value.total < value.matches.length
    || new Set(value.matches.map(match => match.id)).size !== value.matches.length
    || value.matches.some(match => !Number.isSafeInteger(match.id) || match.id <= 0
      || [match.official_match_code, match.league_name, match.home_team_name, match.away_team_name, match.kickoff_time, match.business_date].some(field => typeof field !== 'string')
      || (scope === 'history' && match.business_date !== businessDate)
      || (match.capture_status != null && typeof match.capture_status.status !== 'string')
      || !Array.isArray(match.series) || !Array.isArray(match.anomalies)
      || match.series.some(point => point.play_type !== play || !Number.isSafeInteger(point.snapshot_id) || point.snapshot_id <= 0
        || typeof point.option_code !== 'string' || typeof point.option_name !== 'string' || typeof point.snapshot_time !== 'string'
        || !Number.isFinite(Date.parse(point.snapshot_time)) || !Number.isFinite(point.sp_value) || point.sp_value <= 0))) throw new Error('赔率数据格式不正确');
  return value;
}

function OddsQuery({ scope, businessDate, play }: { scope: Scope; businessDate?: string; play: PlayTab }) {
  const fetcher = useCallback(async () => validateResponse(await api.dashboard.oddsMovements({
    scope, business_date: businessDate, play_type: play, resolution: scope === 'history' ? 'hour' : 'raw', limit: 200,
  }), scope, businessDate, play), [scope, businessDate, play]);
  const resource = useReadOnlyResource(fetcher, 30_000, scope === 'current');
  const [query, setQuery] = useState('');
  const [league, setLeague] = useState('');
  const [capture, setCapture] = useState('');
  const [page, setPage] = useState(1);
  const matches = resource.data?.matches ?? [];
  const search = query.trim().toLocaleLowerCase();
  const filtered = matches.filter(match => (!league || match.league_name === league)
    && (!capture || (match.capture_status?.status ?? 'pending') === capture)
    && (!search || [match.id, match.official_match_code, match.home_team_name, match.away_team_name, match.league_name].join(' ').toLocaleLowerCase().includes(search)));
  const pages = Math.max(1, Math.ceil(filtered.length / 10));
  const currentPage = Math.min(page, pages);
  useEffect(() => { if (page > pages) setPage(pages); }, [page, pages]);
  const leagues = [...new Set([...matches.map(match => match.league_name), ...(league ? [league] : [])])].sort();
  const captureOptions = [...new Set([...Object.keys(CAPTURE_LABELS), ...(capture ? [capture] : []), ...matches.map(match => match.capture_status?.status ?? 'pending')])];
  const reset = () => { setQuery(''); setLeague(''); setCapture(''); setPage(1); };
  const resting = resource.data?.sales_window?.is_open === false;
  return (
    <section aria-label="赔率赛事证据">
      <Card>
        <div className="be-toolbar">
          <label>搜索赛事<input type="search" aria-label="搜索赔率赛事" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} placeholder="球队、编号、联赛" /></label>
          <label>联赛<select aria-label="赔率联赛" value={league} onChange={event => { setLeague(event.target.value); setPage(1); }}><option value="">全部联赛</option>{leagues.map(item => <option key={item} value={item}>{item}</option>)}</select></label>
          <label>采集状态<select aria-label="采集状态" value={capture} onChange={event => { setCapture(event.target.value); setPage(1); }}><option value="">全部状态</option>{captureOptions.map(item => <option key={item} value={item}>{CAPTURE_LABELS[item] ?? item}</option>)}</select></label>
          <button type="button" onClick={reset} disabled={!query && !league && !capture}>清空赔率筛选</button>
        </div>
        <div className="be-status" role="status">
          <span className={resource.error ? 'be-error' : ''}>{resource.error ? `${resource.error}${resource.data ? '，保留上次成功赔率' : ''}` : resource.receivedAt ? `响应获取：${formatTimestamp(new Date(resource.receivedAt).toISOString())}` : '尚未获取赔率响应'}</span>
          <button type="button" onClick={() => void resource.refresh()}>刷新赔率</button>
        </div>
        <p className="be-note">已获取 {matches.length} 场 · 筛选 {filtered.length} 场 · 最多获取 200 场，每页 10 场。接口总数仅为本次返回数量；获取时间不代表源快照时间。{scope === 'history' ? '历史按小时采样，仅手动刷新。' : '当前查询在页面可见时自动检查。'}</p>
      </Card>
      {resource.loading ? <LoadingSpinner text="加载赔率走势..." /> : resource.data && matches.length === 0 ? (
        <EmptyState title={scope === 'history' ? '该日期暂无赔率记录' : resting ? '当前为官方休市时间' : '当前没有开盘比赛'} description={scope === 'history' ? '请选择其他历史日期' : resting ? resource.data.sales_window?.message : '赛程开盘后会自动出现在这里'} />
      ) : resource.data && filtered.length === 0 ? <EmptyState title="筛选无结果" description="清空筛选或调整搜索条件" /> : (
        <div className="be-odds-list">{filtered.slice((currentPage - 1) * 10, currentPage * 10).map(match => <OddsMatchCard key={match.id} match={match} playType={play} playLabel={PLAY_LABELS[play]} />)}</div>
      )}
      {filtered.length > 0 && <nav className="be-pagination" aria-label="赔率分页">
        <button type="button" aria-label="上一页赔率" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>上一页</button>
        <span>第 {currentPage} / {pages} 页 · {filtered.length} 场</span>
        <button type="button" aria-label="下一页赔率" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>下一页</button>
      </nav>}
    </section>
  );
}
