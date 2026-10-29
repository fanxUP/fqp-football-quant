import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { HistoryReference } from '../../core/types';
import HistoryReferencePanel from './HistoryReferencePanel';
import MatchDetailPage from '../../pages/MatchDetailPage';

const mocks = vi.hoisted(() => ({ history: vi.fn(), features: vi.fn(), predictions: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { matches: { historyReference: mocks.history }, features: mocks.features, predictions: mocks.predictions } }));

function fixture(params: Partial<HistoryReference> = {}): HistoryReference {
  return {
    match_id: 90, domain: 'match_stats', status: 'available',
    batch: { id: 3, source_name: 'titan007', imported_at: '2026-10-29T12:00:00Z', content_sha256: 'a'.repeat(64), normalization_version: 'v1' },
    source_match: { id: 123, home_name: '甲', away_name: '乙', kickoff_at: '2024-01-01T12:00:00Z', season: null, status: 'finished' },
    counts: { match_stats: 51, lineups: 1, odds_history: 1 },
    rows: [{ key: 'a', side: null, origin: 'reported', value: { stat_key: '射正', home_numeric: 0, away_numeric: null }, timeline: null }],
    total: 51, limit: 50, offset: 0, has_more: true,
    ...params,
  };
}

beforeEach(() => { vi.clearAllMocks(); mocks.history.mockResolvedValue(fixture()); mocks.features.mockResolvedValue({ snapshots: [] }); mocks.predictions.mockResolvedValue({ predictions: [] }); });

it('renders real zero, unknown season and independent acquisition limits', async () => {
  render(<HistoryReferencePanel matchId={90} />);
  await screen.findByText('射正');
  expect(screen.getByText('主 0 · 客 —')).toBeInTheDocument();
  expect(screen.getByText(/赛季 未知/)).toBeInTheDocument();
  expect(screen.getByText(/来源公布\/采集时间未知/)).toBeInTheDocument();
  expect(screen.getByText(/可读走势不证明当时已经公布/)).toBeInTheDocument();
});

it('pins the successful batch across pages and data domains', async () => {
  render(<HistoryReferencePanel matchId={90} />); await screen.findByText('射正');
  mocks.history.mockResolvedValueOnce(fixture({ offset: 50, has_more: false }));
  fireEvent.click(screen.getByRole('button', { name: '下一页' }));
  await screen.findByText('51–51 / 51 条');
  expect(mocks.history).toHaveBeenLastCalledWith(90, { domain: 'match_stats', batch_id: 3, limit: 50, offset: 50 });
  mocks.history.mockResolvedValueOnce(fixture({ domain: 'lineups', total: 1, has_more: false, rows: [{ key: '1', side: 'home', origin: 'reported', value: { player_name: '球员甲', starter: 1, roster_complete: false }, timeline: null }] }));
  fireEvent.click(screen.getByRole('button', { name: '实际阵容' }));
  await screen.findByText('球员甲');
  expect(screen.getByText('来源名单不完整')).toBeInTheDocument();
  expect(mocks.history).toHaveBeenLastCalledWith(90, { domain: 'lineups', batch_id: 3, limit: 50, offset: 0 });
});

it('distinguishes unmatched from successful empty coverage', async () => {
  mocks.history.mockResolvedValueOnce(fixture({ status: 'unmatched', batch: null, source_match: null, rows: [], counts: {}, total: 0, has_more: false }));
  render(<HistoryReferencePanel matchId={90} />); await screen.findByText(/尚无经过核实的历史资料映射/);
  mocks.history.mockResolvedValueOnce(fixture({ rows: [], total: 0, has_more: false }));
  fireEvent.click(screen.getByRole('button', { name: '刷新历史参考' }));
  await screen.findByText(/所选批次暂无技术统计记录/);
});

it('uses resolved odds timestamps despite false raw JSON flags', async () => {
  render(<HistoryReferencePanel matchId={90} />); await screen.findByText('射正');
  mocks.history.mockResolvedValueOnce(fixture({ domain: 'odds_history', rows: [{ key: 'odds', side: null, origin: 'market', value: { home: 0, line: '3.2', away: 4, company_id: 1, odds_type: 'europe', change_time: '12-31 23:00', change_at: null, timeline_usable: false }, timeline: { change_at: '2023-12-31T15:00:00Z', time_basis: 'inferred_year', time_resolution_reason: 'unique_candidate', timeline_usable: true, change_timezone_basis: 'assumed_site_Asia/Shanghai', effective_kickoff_at: '2024-01-01T12:00:00Z', kickoff_time_basis: 'original_source_schedule', time_resolution_version: 'v2' } }] }));
  fireEvent.click(screen.getByRole('button', { name: '赔率变化' }));
  await screen.findByText('2023-12-31 23:00:00 · 年份推定');
  expect(screen.getByText('主 0 · 中 3.2 · 客 4')).toBeInTheDocument();
});

it('rejects a foreign pinned batch and retries without discarding current evidence', async () => {
  render(<HistoryReferencePanel matchId={90} />); await screen.findByText('射正');
  const other = fixture(); other.batch!.id = 4; mocks.history.mockResolvedValueOnce(other);
  fireEvent.click(screen.getByRole('button', { name: '刷新历史参考' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('历史参考与所选比赛、批次或分页不一致');
  expect(screen.getByText('射正')).toBeInTheDocument();
});

it('ignores late old-match data and starts the next match without its batch', async () => {
  let resolve!: (value: HistoryReference) => void;
  mocks.history.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const { rerender } = render(<HistoryReferencePanel matchId={90} />);
  mocks.history.mockResolvedValueOnce(fixture({ match_id: 91 })); rerender(<HistoryReferencePanel matchId={91} />);
  await screen.findByText('射正');
  await act(async () => resolve(fixture({ rows: [{ key: 'old', origin: 'reported', side: null, value: { stat_key: '过期统计' }, timeline: null }] })));
  expect(screen.queryByText('过期统计')).not.toBeInTheDocument();
  expect(mocks.history).toHaveBeenLastCalledWith(91, { domain: 'match_stats', batch_id: undefined, limit: 50, offset: 0 });
});

it('opens history lazily in the existing match page', async () => {
  render(<MatchDetailPage matchId={90} />);
  expect(mocks.history).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '历史参考' }));
  await screen.findByText('射正');
});

it('shows ambiguous mappings without offering unrelated evidence', async () => {
  mocks.history.mockResolvedValueOnce(fixture({ status: 'ambiguous', batch: null, source_match: null, rows: [], total: 0, has_more: false }));
  render(<HistoryReferencePanel matchId={90} />);
  await screen.findByText(/对应多个来源身份/);
  expect(screen.queryByText('射正')).not.toBeInTheDocument();
});

it('keeps predicted lineup and historical injury semantics visible', async () => {
  render(<HistoryReferencePanel matchId={90} />); await screen.findByText('射正');
  mocks.history.mockResolvedValueOnce(fixture({ domain: 'predicted_lineups', rows: [{ key: 'pred', origin: 'prediction', side: 'away', value: { player_name: '预计球员', starter: 1 }, timeline: null }] }));
  fireEvent.click(screen.getByRole('button', { name: '预计阵容' }));
  await screen.findByText('预计球员');
  expect(screen.getByText(/预计名单，未确认/)).toBeInTheDocument();
  expect(screen.queryByText('来源实际首发')).not.toBeInTheDocument();
  mocks.history.mockResolvedValueOnce(fixture({ domain: 'match_injuries', rows: [{ key: 'injury', origin: 'reported', side: null, value: { player_name: '历史球员', team_name: '来源队名', reason: '伤病' }, timeline: null }] }));
  fireEvent.click(screen.getByRole('button', { name: '历史伤停' }));
  await screen.findByText('历史球员');
  expect(screen.getByText('来源球队 来源队名 · 伤病')).toBeInTheDocument();
  expect(screen.getByText(/不代表球员当前状态/)).toBeInTheDocument();
});

it('rejects malformed records without crashing the page', async () => {
  const broken = fixture(); broken.rows[0].value = null as unknown as Record<string, unknown>;
  mocks.history.mockResolvedValueOnce(broken);
  render(<HistoryReferencePanel matchId={90} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('历史参考与所选比赛、批次或分页不一致');
});

it('rejects malformed coverage counts without crashing the page', async () => {
  mocks.history.mockResolvedValueOnce(fixture({ counts: null as unknown as HistoryReference['counts'] }));
  render(<HistoryReferencePanel matchId={90} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('历史参考与所选比赛、批次或分页不一致');
});
