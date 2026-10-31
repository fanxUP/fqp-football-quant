import { useCallback, useEffect, useRef, useState } from 'react';
import DataTable, { type Column } from '../../shared/components/DataTable';
import PageHeader from '../../shared/components/PageHeader';
import TeamName from '../../shared/components/TeamName';
import Skeleton from '../../shared/components/Skeleton';
import { sharedLeagueSource } from './dataSource';
import type { EventCenterState } from './state';
import type { LeagueDataSource, LeagueDataset, LeagueEvidence, LeagueFixtureQuery, LeagueSeasonData, LeagueStanding, StandingScope } from './types';
import './LeagueCenter.css';

type Change = (patch: Partial<EventCenterState>, replace?: boolean) => void;
const SCOPES: Record<StandingScope, string> = { all: '总榜', home: '主场', away: '客场', form: '近况' };
const TABS = { standings: '积分榜', fixtures: '赛程赛果', teams: '球队' } as const;
const PAGE_SIZE = 20;
const shown = (value: number | null | undefined, decimals?: number) => value == null || !Number.isFinite(value) ? '—' : decimals === undefined ? String(value) : value.toFixed(decimals);

function time(value: string | null) {
  // Reject timezone-less input instead of silently interpreting it in the browser's zone.
  if (!value || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) return null;
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

/** Keyed by the parent. Retry keeps this resource's last success; unmount invalidates late responses.
 * Existing command-center polling intentionally is not used: league browsing must not trigger polling.
 */
function useLeagueRead<T>(loader: () => Promise<T>) {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null }>({ data: null, loading: true, error: null });
  const generation = useRef(0);
  const refresh = useCallback(() => {
    const request = ++generation.current;
    setState(previous => ({ ...previous, loading: true, error: null }));
    Promise.resolve().then(loader).then(data => {
      if (request === generation.current) setState({ data, loading: false, error: null });
    }, error => {
      if (request === generation.current) setState(previous => ({ ...previous, loading: false, error: error instanceof Error ? error.message : '读取失败' }));
    });
  }, [loader]);
  useEffect(() => { refresh(); return () => { generation.current += 1; }; }, [refresh]);
  return { ...state, refresh };
}

function Notice({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="lc-notice"><h3>{title}</h3>{children && <div>{children}</div>}</div>;
}
function Evidence({ value }: { value: LeagueEvidence }) {
  return <p className="lc-evidence">
    来源：{value.sourceName ?? '未知'} · 数据截止：{time(value.asOf) ?? '未知'}（北京时间）
    {' · '}{value.completeness === 'complete' ? '完整批次' : value.completeness === 'partial' ? '部分覆盖' : '暂无覆盖'}
    {value.batchId && <> · 批次：<span className="fqp-mono">{value.batchId}</span></>}
    {value.stale && <strong className="lc-warning"> · {value.asOf ? '已过期' : '时效待核实'}</strong>}
  </p>;
}
function ReadStatus({ error, hasData }: { error: string | null; hasData: boolean }) {
  return error && <p role="alert" className="lc-warning">{error}{hasData ? '；保留上次成功数据，尚未刷新。' : '；请重试。'}</p>;
}
function Metric({ label, value, decimals }: { label: string; value: number | null | undefined; decimals?: number }) {
  return <div className="lc-metric" aria-label={label}><span>{label}</span><strong className="fqp-mono">{shown(value, decimals)}</strong></div>;
}
function SectionTabs({ state, onChange }: { state: EventCenterState; onChange: Change }) {
  return <nav className="lc-tabs" aria-label="联赛资料栏目">
    {Object.entries(TABS).map(([tab, label]) => <button key={tab} type="button" aria-pressed={state.tab === tab}
      onClick={() => onChange({ tab: tab as EventCenterState['tab'], teamId: null, page: 1 })}>{label}</button>)}
  </nav>;
}
function DeferredFeatures() {
  return <aside className="lc-roadmap" aria-label="后续联赛能力">
    <div><strong>球员与阵容事实</strong><span>待后续接入归属、出场时间、转会与伤停。</span></div>
    <div><strong>赛季情景</strong><span>待数据与模型验证后开放；当前不生成模拟概率。</span></div>
  </aside>;
}

export default function LeagueCenter({ source = sharedLeagueSource, state, onChange }: {
  source?: LeagueDataSource; state: EventCenterState; onChange: Change;
}) {
  return <LeagueDirectory key={state.dataset} source={source} state={state} onChange={onChange} />;
}

function LeagueDirectory({ source, state, onChange }: { source: LeagueDataSource; state: EventCenterState; onChange: Change }) {
  const loadCatalog = useCallback(async () => {
    const result = await (state.dataset === 'verified' ? source.catalog('verified') : source.catalog());
    if ((result.dataset ?? 'reference') !== state.dataset) throw new Error('返回目录与所选数据范围不一致');
    return result;
  }, [source, state.dataset]);
  const directory = useLeagueRead(loadCatalog);
  const competition = directory.data?.competitions.find(item => item.code === state.competition)
    ?? (state.dataset === 'verified' && state.competition === '' && directory.data?.competitions.length === 1 ? directory.data.competitions[0] : undefined);
  const currentSeasons = competition?.seasons.filter(item => item.isCurrent) ?? [];
  const defaultSeason = currentSeasons.length === 1 ? currentSeasons[0] : competition?.seasons.length === 1 ? competition.seasons[0] : undefined;
  const selectedSeason = state.seasonId === null ? defaultSeason : competition?.seasons.find(item => item.id === state.seasonId);
  useEffect(() => {
    if (competition && (state.competition !== competition.code || (state.seasonId === null && selectedSeason))) {
      onChange({ competition: competition.code, ...(state.seasonId === null && selectedSeason ? { seasonId: selectedSeason.id } : {}), warning: state.warning }, true);
    }
  }, [state.competition, competition?.code, state.seasonId, state.warning, selectedSeason?.id, onChange]);
  const resetSeason = () => onChange({ seasonId: null, teamId: null, page: 1, roundId: null, status: 'all', scope: 'all' });

  return <div className="lc-page">
    <PageHeader title="赛事中心" subtitle="联赛资料 · 赛季事实、积分形势与赛程赛果" />
    <label>数据范围<select aria-label="数据范围" value={state.dataset} onChange={e => {
      const dataset = e.target.value as LeagueDataset;
      onChange({ dataset, competition: dataset === 'verified' ? '' : 'premier-league', seasonId: null,
        tab: dataset === 'verified' ? 'fixtures' : 'standings', teamId: null, page: 1, roundId: null, status: 'all', scope: 'all' });
    }}><option value="reference">联赛资料</option><option value="verified">竞彩 · 已核实赛季归属</option></select></label>
    {state.dataset === 'verified' && <p className="lc-help">仅含已核实逐场赛季归属的竞彩比赛；不代表全联赛或全部传统足彩赛事。没有完整积分榜、球员或规范球队资料时保留未知。</p>}
    {state.warning && <p role="alert" className="lc-warning">{state.warning}</p>}
    <ReadStatus error={directory.error} hasData={!!directory.data} />
    {directory.loading && !directory.data ? <div role="status" aria-label="加载联赛目录"><Skeleton variant="card" height={120} /></div> : <>
      <div className="lc-toolbar">
        <label>联赛<select aria-label="联赛" value={competition?.code ?? ''} disabled={!directory.data?.competitions.length}
          onChange={e => onChange({ competition: e.target.value, seasonId: null, teamId: null, page: 1, roundId: null, status: 'all', scope: 'all' })}>
          {!competition && <option value="">请选择联赛</option>}
          {directory.data?.competitions.map(item => <option value={item.code} key={item.code}>{item.name} · {item.country}</option>)}
        </select></label>
        <label>赛季<select aria-label="赛季" value={selectedSeason?.id ?? ''} disabled={!competition?.seasons.length}
          onChange={e => onChange({ seasonId: e.target.value ? Number(e.target.value) : null, teamId: null, page: 1, roundId: null, status: 'all', scope: 'all' })}>
          {!selectedSeason && <option value="">{competition?.seasons.length ? '请选择赛季' : '赛季待接入'}</option>}
          {competition?.seasons.map(item => <option key={item.id} value={item.id}>{item.label}{item.isCurrent ? ' · 当前赛季' : ''}</option>)}
        </select></label>
        <span className="lc-connection">{directory.data?.status === 'connected' ? '共享资料' : '数据未接入'}</span>
        <button type="button" disabled={directory.loading} onClick={directory.refresh}>刷新联赛目录</button>
      </div>
      {!directory.data ? null : !competition ? <Notice title={state.competition ? "链接中的联赛尚未配置" : "请选择联赛"}>请选择已配置联赛。</Notice>
        : state.seasonId !== null && !selectedSeason ? <Notice title="链接中的赛季暂无覆盖">
          未自动替换为其他赛季。<button type="button" onClick={resetSeason}>返回可用赛季</button>
        </Notice>
        : selectedSeason ? <SeasonContent key={`${state.competition}:${selectedSeason.id}`} source={source} seasonId={selectedSeason.id} state={state} onChange={onChange} />
        : <>
          <div className="lc-overview" aria-label="联赛概览">
            <Metric label="已赛场次" value={null} /><Metric label="总进球" value={null} /><Metric label="场均进球" value={null} />
            <Metric label="主胜 / 平局 / 客胜" value={null} />
          </div>
          <SectionTabs state={state} onChange={onChange} />
          <Notice title={competition?.seasons.length ? '请选择赛季' : '联赛数据待接入'}>
            {competition?.seasons.length ? '按赛季查看已保存的联赛资料。' : '联赛资料区已准备好。接入真实赛季数据后，这里将展示概览、积分榜、赛程和球队资料；目前没有数据。'}
          </Notice>
        </>}
    </>}
    <DeferredFeatures />
  </div>;
}

function SeasonContent({ source, seasonId, state, onChange }: { source: LeagueDataSource; seasonId: number; state: EventCenterState; onChange: Change }) {
  const loader = useCallback(async () => {
    const result = await (state.dataset === 'verified' ? source.season(seasonId, 'verified') : source.season(seasonId));
    if ((result.dataset ?? 'reference') !== state.dataset) throw new Error('返回资料与所选数据范围不一致');
    if (result.competitionSeasonId !== seasonId) throw new Error('返回资料与所选赛季不一致');
    return result;
  }, [source, seasonId, state.dataset]);
  const resource = useLeagueRead(loader);
  const data = resource.data;
  const openTeam = (teamId: number) => onChange({ tab: 'teams', teamId, page: 1, roundId: null, status: 'all' });
  return <>
    <div className="lc-section-heading"><h2>赛季概览{data && data.evidence.completeness !== 'complete' ? ' · 已收录样本统计' : ''}</h2>
      <button type="button" onClick={resource.refresh} disabled={resource.loading}>刷新联赛资料</button></div>
    <ReadStatus error={resource.error} hasData={!!data} />
    {resource.loading && !data && <div role="status" aria-label="加载赛季资料"><Skeleton variant="card" height={160} /></div>}
    {data && <>
      {data.seasonIdentity && <p className="lc-help">计划赛季：{data.seasonIdentity.plannedStartDate} 至 {data.seasonIdentity.plannedEndDate}（{data.seasonIdentity.timeZone}）。逐场归属以明确证据为准，延期越界不自动移出赛季。</p>}
      <Evidence value={data.evidence} />
      <p className="lc-coverage">球队覆盖：{shown(data.coverage.teams)} / {data.coverage.expectedTeams ?? '未知'} · 赛程覆盖：{shown(data.coverage.fixtures)} / {data.coverage.expectedFixtures ?? '未知'}。覆盖未知时不代表全联赛。</p>
      <div className="lc-overview" aria-label="联赛概览">
        <Metric label="已赛场次" value={data.overview?.played} /><Metric label="总进球" value={data.overview?.goals} />
        <Metric label="场均进球" value={data.overview?.goalsPerMatch} decimals={2} />
        <div className="lc-metric" aria-label="主胜 / 平局 / 客胜"><span>主胜 / 平局 / 客胜</span><strong className="fqp-mono">{shown(data.overview?.homeWins)} / {shown(data.overview?.draws)} / {shown(data.overview?.awayWins)}</strong></div>
      </div>
    </>}
    <SectionTabs state={state} onChange={onChange} />
    {data && (state.tab === 'standings' ? <Standings data={data} scope={state.scope} onScope={scope => onChange({ scope })} openTeam={openTeam} />
      : state.tab === 'fixtures' ? <Fixtures source={source} data={data} state={state} onChange={onChange} teamId={null} />
      : <Teams source={source} data={data} state={state} onChange={onChange} openTeam={openTeam} />)}
  </>;
}

function Standings({ data, scope, onScope, openTeam }: { data: LeagueSeasonData; scope: StandingScope; onScope: (scope: StandingScope) => void; openTeam: (id: number) => void }) {
  const batch = data.standings[scope];
  const columns: Column<LeagueStanding>[] = [
    { key: 'rank', title: '排名', align: 'center', render: value => shown(value as number | null) },
    { key: 'team', title: '球队', render: (_value, row) => <button className="lc-team-link" type="button" aria-label={`查看球队 ${row.team.name}`} onClick={() => openTeam(row.team.id)}><TeamName name={row.team.name} /></button> },
    ...[['played', '场次'], ['won', '胜'], ['drawn', '平'], ['lost', '负'], ['goalsFor', '进球'], ['goalsAgainst', '失球'], ['goalDifference', '净胜球'], ['points', '积分']].map(([key, title]): Column<LeagueStanding> => ({ key, title, align: 'center', render: value => <span className="fqp-mono">{shown(value as number | null)}</span> })),
    { key: 'form', title: '近5场', render: (_value, row) => row.form?.length ? <span className="lc-form" aria-label={row.form.map(item => ({ W: '胜', D: '平', L: '负' })[item]).join('、')}>{row.form.slice(-5).map((result, i) => <span key={i} data-result={result}>{({ W: '胜', D: '平', L: '负' })[result]}</span>)}</span> : '未知' },
    { key: 'note', title: '备注', render: value => value == null ? '—' : String(value) },
  ];
  const complete = batch?.evidence.completeness === 'complete';
  return <section aria-label="联赛积分榜" className="lc-panel">
    <div className="lc-section-heading"><h2>积分榜</h2><div className="lc-scope" aria-label="积分榜范围">
      {Object.entries(SCOPES).map(([key, label]) => <button type="button" key={key} aria-pressed={scope === key} onClick={() => onScope(key as StandingScope)}>{label}</button>)}
    </div></div>
    <p className="lc-help">当季本联赛口径；近5场从左到右为由早到晚。积分采用来源值，扣分等调整见备注；未提供预期积分。</p>
    {batch && <Evidence value={batch.evidence} />}
    {!batch || batch.evidence.completeness === 'unavailable' ? <Notice title={`${scope === 'all' ? '总榜' : `${SCOPES[scope]}榜`}暂无覆盖`}>缺失范围不会用总榜代替。</Notice>
      : !complete ? <Notice title="积分榜批次不完整">等待同一来源、同一范围的完整榜单；不拼接逐队快照。</Notice>
      : <div className="lc-table" role="region" aria-label="积分榜数据，可横向滚动" tabIndex={0}><DataTable columns={columns} rows={batch.rows} rowKey={row => row.team.id} emptyText="该批次暂无积分榜记录" /></div>}
  </section>;
}

function Teams({ source, data, state, onChange, openTeam }: { source: LeagueDataSource; data: LeagueSeasonData; state: EventCenterState; onChange: Change; openTeam: (id: number) => void }) {
  const selected = data.teams.find(team => team.id === state.teamId);
  if (state.teamId !== null && !selected) return <Notice title="该赛季未找到此球队">未自动匹配同名或其他赛季的球队。<button type="button" onClick={() => onChange({ teamId: null, page: 1 })}>返回球队列表</button></Notice>;
  if (!selected) return <section className="lc-panel" aria-label="联赛球队">
    <div className="lc-section-heading"><h2>参赛球队</h2><span>已收录 {data.teams.length} 队</span></div>
    {data.teams.length ? <ul className="lc-team-grid">{data.teams.map(team => <li key={team.id}>
      <button type="button" aria-label={`查看球队 ${team.name}`} onClick={() => openTeam(team.id)}><TeamName name={team.name} size={28} /><span>查看本赛季资料 →</span></button>
    </li>)}</ul> : <Notice title="球队资料暂无覆盖">接入当前赛季参赛关系后展示。</Notice>}
  </section>;
  const row = data.standings.all?.evidence.completeness === 'complete' ? data.standings.all.rows.find(item => item.team.id === selected.id) : undefined;
  return <section className="lc-panel" aria-label="球队赛季资料">
    <div className="lc-section-heading"><h2 aria-label={selected.name}><TeamName name={selected.name} size={28} /></h2><button type="button" onClick={() => onChange({ teamId: null, page: 1 })}>返回球队列表</button></div>
    <p className="lc-help"><span>{selected.manager ?? '教练待接入'}</span> · <span>{selected.stadium ?? '主场待接入'}</span>。球队资料仅限所选赛季，当前阵容与伤停尚未接入。</p>
    <div className="lc-overview"><Metric label="联赛排名" value={row?.rank} /><Metric label="积分" value={row?.points} /><Metric label="进球" value={row?.goalsFor} /><Metric label="失球" value={row?.goalsAgainst} /></div>
    <h3>本赛季赛程</h3>
    <Fixtures source={source} data={data} state={state} onChange={onChange} teamId={selected.id} />
  </section>;
}

function Fixtures({ source, data, state, onChange, teamId }: { source: LeagueDataSource; data: LeagueSeasonData; state: EventCenterState; onChange: Change; teamId: number | null }) {
  const query: LeagueFixtureQuery = { ...(state.dataset === 'verified' ? { dataset: state.dataset } : {}), competitionSeasonId: data.competitionSeasonId, batchId: data.evidence.batchId ?? undefined, roundId: state.roundId, status: state.status, teamId, limit: PAGE_SIZE, offset: (state.page - 1) * PAGE_SIZE };
  if (query.roundId !== null && !data.rounds.some(round => round.id === query.roundId)) return <Notice title="所选轮次暂无覆盖"><button type="button" onClick={() => onChange({ roundId: null, page: 1 })}>查看全部轮次</button></Notice>;
  if (!Number.isSafeInteger(query.offset)) return <Notice title="赛程页码超出范围"><button type="button" onClick={() => onChange({ page: 1 })}>返回第一页</button></Notice>;
  return <div className="lc-fixtures">
    <div className="lc-fixture-filters">
      <label>轮次<select aria-label="轮次" value={state.roundId ?? ''} onChange={e => onChange({ roundId: e.target.value || null, page: 1 })}>
        <option value="">全部轮次</option>{data.rounds.map(round => <option key={round.id} value={round.id}>{round.label}</option>)}
      </select></label>
      <label>赛程状态<select aria-label="赛程状态" value={state.status} onChange={e => onChange({ status: e.target.value as EventCenterState['status'], page: 1 })}>
        <option value="all">全部状态</option><option value="finished">已结束</option><option value="upcoming">未开赛</option><option value="postponed">已延期</option>
      </select></label>
    </div>
    <FixtureResults key={JSON.stringify(query)} source={source} query={query} page={state.page} onChange={onChange} />
  </div>;
}
function FixtureResults({ source, query, page, onChange }: { source: LeagueDataSource; query: LeagueFixtureQuery; page: number; onChange: Change }) {
  const loader = useCallback(async () => {
    const result = await source.fixtures(query);
    if ((result.dataset ?? 'reference') !== (query.dataset ?? 'reference')) throw new Error('返回赛程与所选数据范围不一致');
    if (result.competitionSeasonId !== query.competitionSeasonId) throw new Error('返回赛程与所选赛季不一致');
    if (query.batchId && result.evidence.batchId !== query.batchId) throw new Error('返回赛程与所选资料批次不一致');
    return result;
  }, [source, query.dataset, query.competitionSeasonId, query.batchId, query.roundId, query.status, query.teamId, query.limit, query.offset]);
  const resource = useLeagueRead(loader);
  const result = resource.data;
  const pages = result ? Math.max(1, Math.ceil(result.total / PAGE_SIZE)) : 1;
  return <section aria-label="联赛赛程赛果" className="lc-panel">
    <div className="lc-section-heading"><h2>赛程赛果</h2><button type="button" disabled={resource.loading} onClick={resource.refresh}>刷新赛程</button></div>
    <ReadStatus error={resource.error} hasData={!!result} />
    {resource.loading && !result && <div role="status" aria-label="加载赛程"><Skeleton variant="card" height={180} /></div>}
    {result && <>
      <Evidence value={result.evidence} />
      <p className="lc-help">{query.dataset === 'verified' ? '开球时间为北京时间。仅含已核实逐场赛季归属的竞彩比赛；比分只展示已确认结果，不补算联赛积分。' : '开球时间为北京时间。联赛资料包含非竞彩比赛；仅已核实关联的官方比赛可进入现有分析。'}</p>
      {page > pages ? <Notice title="该页超出当前赛程范围"><button type="button" onClick={() => onChange({ page: 1 })}>返回第一页</button></Notice>
        : result.rows.length === 0 ? <Notice title="当前筛选暂无赛程">可以切换轮次或状态查看。</Notice>
        : <ul className="lc-fixture-list">{result.rows.map(match => {
          const official = match.officialMatch;
          const verified = official?.verification === 'verified' && Number.isSafeInteger(official.id) && official.id > 0;
          const scoreKnown = [match.homeGoals, match.awayGoals].every(value => value !== null && Number.isInteger(value) && value >= 0) && ['finished', 'live'].includes(match.status);
          return <li key={match.id}>
            <div className="lc-fixture-meta"><span>{time(match.kickoff) ?? '开球时间待定'}</span><span>{({ scheduled: '未开赛', live: '进行中', finished: '已结束', postponed: '已延期', cancelled: '已取消', unknown: '状态待核实' })[match.status]}</span></div>
            <div className="lc-fixture-teams"><TeamName name={match.home.name} /><strong className="fqp-mono">{scoreKnown ? `${shown(match.homeGoals)} : ${shown(match.awayGoals)}` : 'VS'}</strong><TeamName name={match.away.name} /></div>
            {verified ? <a href={`#/matches/${official.id}`} aria-label={`查看分析 ${match.id}`}>查看分析 →</a>
              : <span className="lc-help">{official ? '竞彩映射待核实' : '未关联竞彩比赛'}</span>}
          </li>;
        })}</ul>}
      {page <= pages && <div className="lc-pagination" aria-label="赛程分页">
        <button type="button" disabled={page <= 1} onClick={() => onChange({ page: page - 1 })}>上一页</button>
        <span>第 {page} / {pages} 页 · {result.total} 场 · 每页 {PAGE_SIZE} 场</span>
        <button type="button" disabled={page >= pages} onClick={() => onChange({ page: page + 1 })}>下一页</button>
      </div>}
    </>}
  </section>;
}
