import { useEffect, useRef, useState } from 'react';
import { api } from '../../core/apiClient';
import type { FixtureSeasonReference, HistoryDomain, HistoryReference } from '../../core/types';
import useManualEvidence from '../../pages/useManualEvidence';
import ReadEvidenceStatus from '../../pages/ReadEvidenceStatus';
import { formatTimestamp } from '../utils';
import Card from './Card';
import '../../pages/BusinessEvidence.css';

const DOMAINS: { key: HistoryDomain; label: string; note: string }[] = [
  { key: 'match_stats', label: '技术统计', note: '赛后统计；常规时间、半场或加时口径以来源为准。' },
  { key: 'events', label: '比赛事件', note: '来源记录的比赛事件，可能缺项。' },
  { key: 'lineups', label: '实际阵容', note: '历史实际名单；不完整名单单独标记。' },
  { key: 'predicted_lineups', label: '预计阵容', note: '预计名单，不代表确认首发；旧采集时间不能证明公布时间。' },
  { key: 'match_injuries', label: '历史伤停', note: '关联当时比赛的历史记录，不代表球员当前状态；空列表不代表全员健康。' },
  { key: 'odds_history', label: '赔率变化', note: '第三方参考盘；主/中/客依次为主赔、盘口或平赔、客赔。盘口单位与公司以来源为准。' },
];
const PAGE_SIZE = 50;
const text = (value: unknown) => typeof value === 'string' && value.trim() ? value : typeof value === 'number' && Number.isFinite(value) ? String(value) : '—';
const sideLabel = (value: string | null) => value === 'home' ? '主队' : value === 'away' ? '客队' : '归属未知';
const basisLabel = (value: string) => ({ source_full: '来源完整日期', inferred_year: '年份推定', unresolved: '时间待确认' })[value] ?? '时间依据未知';

function validSeason(season: HistoryReference['fixture_season']) {
  if (season == null) return true;
  return typeof season === 'object' && !Array.isArray(season)
    && [season.fixture_id, season.competition_id, season.competition_season_id, season.season_id].every(id => Number.isSafeInteger(id) && id > 0)
    && [season.competition_code, season.season_code, season.season_name, season.source_timezone, season.source_name, season.source_competition_id, season.source_season_id].every(value => typeof value === 'string' && value.trim())
    && (season.competition_name === null || typeof season.competition_name === 'string')
    && [season.planned_start_date, season.planned_end_date].every(value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value))
    && season.planned_start_date <= season.planned_end_date
    && [season.boundary_evidence, season.membership_evidence].every(proof => proof && typeof proof === 'object' && !Array.isArray(proof)
      && [proof.url, proof.sha256, proof.captured_at].every(value => value === null || typeof value === 'string'));
}

function sourceUrl(value: string | null) {
  try {
    const url = new URL(value ?? '');
    return url.protocol === 'https:' && url.hostname === 'webapi.sporttery.cn' && !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}

function FixtureSeason({ season }: { season: FixtureSeasonReference | null | undefined }) {
  if (!season) return <p className="be-note">赛事赛季待核实：尚无明确的逐场归属，不按开球日期或来源旧标签推定。</p>;
  const boundaryUrl = sourceUrl(season.boundary_evidence.url);
  const memberUrl = sourceUrl(season.membership_evidence.url);
  return <section aria-label="赛事赛季归属">
    <p><strong>已核实赛季：{season.competition_name || season.competition_code} · {season.season_name}</strong></p>
    <p className="be-note">官方计划范围：{season.planned_start_date} 至 {season.planned_end_date}（{season.source_timezone}）；延期比赛按明确成员归属。</p>
    <details>
      <summary style={{ minHeight: 44, alignContent: 'center', cursor: 'pointer' }}>查看赛季归属依据</summary>
      <p className="be-note">来源 {season.source_name} · 来源赛事 {season.source_competition_id} · 来源赛季 {season.source_season_id}</p>
      <div className="be-match-meta">
        {boundaryUrl && <a href={boundaryUrl} target="_blank" rel="noopener noreferrer">赛季边界来源</a>}
        {memberUrl && <a href={memberUrl} target="_blank" rel="noopener noreferrer">逐场归属来源</a>}
      </div>
      <p className="be-note">边界证据采集：{formatTimestamp(season.boundary_evidence.captured_at)} · 逐场证据采集：{formatTimestamp(season.membership_evidence.captured_at)}</p>
      <p className="be-note">边界材料 SHA256：{season.boundary_evidence.sha256 ?? '未知'}<br />逐场材料 SHA256：{season.membership_evidence.sha256 ?? '未知'}</p>
      <p className="be-note">证据采集时间不代表历史公布时间，赛季归属不证明当时可用于赛前预测。</p>
    </details>
  </section>;
}

function HistoryRows({ matchId, domain, offset, batchRef, onPage }: {
  matchId: number; domain: HistoryDomain; offset: number;
  batchRef: { current: number | undefined }; onPage: (offset: number) => void;
}) {
  const resource = useManualEvidence(async () => {
    const expectedBatch = batchRef.current;
    const data = await api.matches.historyReference(matchId, { domain, batch_id: expectedBatch, limit: PAGE_SIZE, offset });
    if (data.match_id !== matchId || data.domain !== domain || data.offset !== offset
      || data.limit !== PAGE_SIZE || !Array.isArray(data.rows) || data.rows.length > PAGE_SIZE
      || !['available', 'unmatched', 'ambiguous'].includes(data.status)
      || !Number.isSafeInteger(data.total) || data.total < 0
      || !data.counts || typeof data.counts !== 'object' || Array.isArray(data.counts)
      || Object.values(data.counts).some(count => !Number.isSafeInteger(count) || count < 0)
      || data.rows.some(row => !row || typeof row.key !== 'string' || !row.value || typeof row.value !== 'object' || Array.isArray(row.value))
      || (expectedBatch !== undefined && data.batch?.id !== expectedBatch)
      || (data.status === 'available' && (!data.batch || !data.source_match))) {
      throw new Error('历史参考与所选比赛、批次或分页不一致');
    }
    if (!validSeason(data.fixture_season)) throw new Error('历史参考与所选比赛、批次或分页不一致');
    return data;
  });
  // A late response from an unmounted query cannot replace the pinned batch.
  useEffect(() => { if (resource.data?.batch) batchRef.current = resource.data.batch.id; }, [resource.data, batchRef]);
  const data = resource.data;
  function rowContent(row: HistoryReference['rows'][number]) {
    const v = row.value;
    switch (domain) {
      case 'match_stats':
        return <><strong>{text(v.stat_key)}</strong><p>主 {text(v.home_value ?? v.home_numeric)} · 客 {text(v.away_value ?? v.away_numeric)}</p><p className="be-note">{({ source_full_match: '来源全场口径', first_half: '半场', extra_time: '加时' })[text(v.period)] ?? '时间段未知'}</p></>;
      case 'events':
        return <><strong>{text(v.minute)} · {text(v.event_type)}</strong><p>{sideLabel(row.side)} · {text(v.player_name)}</p></>;
      case 'lineups':
      case 'predicted_lineups':
        return <><strong>{text(v.player_name)}</strong><p>{sideLabel(row.side)} · {text(v.position)} · {domain === 'predicted_lineups' ? '预计名单，未确认' : v.starter === 1 ? '来源实际首发' : v.starter === 0 ? '来源实际替补' : '首发身份未知'}</p>{domain === 'lineups' && <p className="be-note">{v.roster_complete === true ? '来源名单完整性检查通过' : '来源名单不完整'}</p>}</>;
      case 'match_injuries':
        return <><strong>{text(v.player_name)}</strong><p>{row.side ? sideLabel(row.side) : `来源球队 ${text(v.team_name)}`} · {text(v.reason)}</p><p className="be-note">发生日期 {text(v.occurred_date)} · 预计回归 {text(v.expected_return_date)}</p></>;
      case 'odds_history': {
        const timeline = row.timeline;
        return <><strong>公司 {text(v.company_id)} · {({ europe: '胜平负', asian: '亚洲让球', overunder: '总进球' })[text(v.odds_type)] ?? '类型未知'}</strong>
          <p>主 {text(v.home)} · 中 {text(v.line)} · 客 {text(v.away)}</p>
          <p>{timeline?.timeline_usable ? formatTimestamp(timeline.change_at) : '时间待确认'} · {timeline ? basisLabel(timeline.time_basis) : '时间依据未知'}</p>
          <p className="be-note">原文 {text(v.change_time)} · {timeline?.change_timezone_basis === 'source_explicit_offset' ? '来源明确时区' : '按站点北京时间解释'}</p>
          {timeline && !timeline.timeline_usable && <p className="be-note">{timeline.time_resolution_reason}</p>}
          {timeline?.kickoff_time_basis === 'source_and_official' && <p className="be-note">已核验参考开球：{formatTimestamp(timeline.effective_kickoff_at)}</p>}
        </>;
      }
    }
  }
  return <>
    <ReadEvidenceStatus resource={resource} label="刷新历史参考" note="接收时间不代表来源公布时间" />
    {data && <FixtureSeason season={data.fixture_season} />}
    {data?.status === 'unmatched' && <p>该比赛尚无经过核实的历史资料映射，不能据此判断来源没有数据。</p>}
    {data?.status === 'ambiguous' && <p>该比赛对应多个来源身份，待核实后展示历史资料。</p>}
    {data?.status === 'available' && data.batch && data.source_match && <>
      <p className="be-note">来源 {data.batch.source_name} · 批次 {data.batch.id} · 来源比赛 {data.source_match.id} · {data.source_match.home_name ?? '主队未知'} / {data.source_match.away_name ?? '客队未知'}</p>
      <p className="be-note">来源赛季原文（未核实）：{data.source_match.season ?? '未知'}</p>
      <p className="be-note">原记录开球 {formatTimestamp(data.source_match.kickoff_at)} · 入库 {formatTimestamp(data.batch.imported_at)} · 来源公布/采集时间未知</p>
      <p className="be-note">该批次覆盖：{DOMAINS.map(item => `${item.label} ${data.counts[item.key] ?? 0}`).join(' · ')}</p>
      {data.rows.length === 0 ? <p>所选批次暂无{DOMAINS.find(item => item.key === domain)?.label}记录，采集覆盖未知。</p> : <ul style={{ listStyle: 'none', padding: 0 }}>
        {data.rows.map(row => <li key={row.key} style={{ borderBottom: '1px solid var(--fqp-border)', padding: '12px 0', overflowWrap: 'anywhere' }}>{rowContent(row)}</li>)}
      </ul>}
      <div className="be-pagination" aria-label="历史资料分页">
        <button type="button" disabled={resource.loading || offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE_SIZE))}>上一页</button>
        <span>{data.total ? `${Math.min(offset + 1, data.total)}–${Math.min(offset + data.rows.length, data.total)}` : '0'} / {data.total} 条</span>
        <button type="button" disabled={resource.loading || !data.has_more || offset + PAGE_SIZE > 10000} onClick={() => onPage(offset + PAGE_SIZE)}>下一页</button>
      </div>
      {data.has_more && offset + PAGE_SIZE > 10000 && <p className="be-note">已达单次浏览上限，其余记录请使用离线分析读取。</p>}
    </>}
  </>;
}

function HistoryQuery({ matchId }: { matchId: number }) {
  const [domain, setDomain] = useState<HistoryDomain>('match_stats');
  const [offset, setOffset] = useState(0);
  const batchRef = useRef<number | undefined>(undefined);
  return <Card>
    <h2>历史参考资料</h2>
    <p>历史回填仅供核对与研究。赔率时间可包含推定年份；可读走势不证明当时已经公布或属于赛前盘。</p>
    <div className="be-actions" aria-label="历史资料分类">{DOMAINS.map(item => <button type="button" key={item.key} aria-pressed={domain === item.key} onClick={() => { setDomain(item.key); setOffset(0); }}>{item.label}</button>)}</div>
    <p className="be-note">{DOMAINS.find(item => item.key === domain)?.note}</p>
    <HistoryRows key={`${domain}:${offset}`} matchId={matchId} domain={domain} offset={offset} batchRef={batchRef} onPage={setOffset} />
  </Card>;
}

export default function HistoryReferencePanel({ matchId }: { matchId: number }) {
  return <HistoryQuery key={matchId} matchId={matchId} />;
}
