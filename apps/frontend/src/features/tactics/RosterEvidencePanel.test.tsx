import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import RosterEvidencePanel from './RosterEvidencePanel';
import MatchDetailPage from '../../pages/MatchDetailPage';
const mocks = vi.hoisted(() => ({ detail: vi.fn(), features: vi.fn(), predictions: vi.fn() }));
vi.mock('../../core/apiClient', () => ({ api: { matches: { detail: mocks.detail }, features: mocks.features, predictions: mocks.predictions } }));
function fixture(id = 101) {
  return { match: {id, home_team_name:'主队',away_team_name:'客队',kickoff_time:'2026-10-09T20:00:00'}, teams: {home:{id:1},away:{id:2}}, lineups:{home:{snapshot_id:11,match_id:id,team_id:1,lineup_type:'confirmed',source:'测试来源',snapshot_time:'2026-10-09T19:00:00',collected_at:'2026-10-09T19:05:00',formation:'4-3-3',strength_score:0,players:Array.from({length:11},(_,i)=>({player_id:i+1,name_cn:`球员${i+1}`,is_starting:true,is_substitute:false,position:'DF',tactical_role:'边路'}))},away:null}, injuries:[],availability_scope:'latest_per_player_team',availability_limit_per_team:20 };
}
beforeEach(() => {vi.clearAllMocks();mocks.detail.mockResolvedValue(fixture());mocks.features.mockResolvedValue({snapshots:[]});mocks.predictions.mockResolvedValue({predictions:[]});});
it('shows source times, provenance, real zero and keyboard-operable player details without jersey IDs', async () => {
  render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('测试来源');
  expect(screen.getByText(/入库时间/)).toBeInTheDocument();expect(screen.getByText('战力 0.00')).toBeInTheDocument();
  expect(screen.getByText('来源标记为确认首发 · 11/11')).toBeInTheDocument();
  const button=screen.getByRole('button',{name:'选择球员 球员1'});button.focus();expect(button).toHaveFocus();fireEvent.click(button);
  expect(button).toHaveAttribute('aria-pressed','true');expect(screen.getByText('战术角色：边路')).toBeInTheDocument();
  expect(screen.queryByText('#1')).not.toBeInTheDocument();
});
it('does not claim health or reliable lineup for successful empty evidence', async () => {
  mocks.detail.mockResolvedValue({...fixture(),lineups:{home:null,away:null}});render(<RosterEvidencePanel matchId={101}/>);
  expect((await screen.findAllByText('尚无阵容快照')).length).toBe(2);expect(screen.getByText(/空列表不代表全员健康/)).toBeInTheDocument();
});
it('distinguishes predicted, incomplete and missing provenance lineups', async () => {
  const data=fixture();data.lineups.home.lineup_type='predicted';data.lineups.home.players=data.lineups.home.players.slice(0,2);data.lineups.home.source='';
  mocks.detail.mockResolvedValue(data);render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('预估名单 · 2/11');
  expect(screen.getByText('来源未知')).toBeInTheDocument();expect(screen.getAllByText(/可靠首发证据不足/).length).toBeGreaterThan(0);
});
it('rejects foreign matches and allows manual retry', async () => {
  mocks.detail.mockResolvedValueOnce(fixture(102));render(<RosterEvidencePanel matchId={101}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('阵容证据与所选比赛不一致');fireEvent.click(screen.getByRole('button',{name:'刷新阵容与伤停证据'}));await screen.findByText('测试来源');
});
it('retains same-match evidence on failure and clears it after valid empty refresh', async () => {
  render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('测试来源');mocks.detail.mockRejectedValueOnce(new Error('失败'));
  fireEvent.click(screen.getByRole('button',{name:'刷新阵容与伤停证据'}));await screen.findByRole('alert');expect(screen.getByText('测试来源')).toBeInTheDocument();
  mocks.detail.mockResolvedValueOnce({...fixture(),lineups:{home:null,away:null}});fireEvent.click(screen.getByRole('button',{name:'刷新阵容与伤停证据'}));await screen.findAllByText('尚无阵容快照');expect(screen.queryByText('测试来源')).not.toBeInTheDocument();
});
it('clears old-match evidence when the next match fails', async () => {
  const {rerender}=render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('测试来源');mocks.detail.mockRejectedValueOnce(new Error('下一场失败'));rerender(<RosterEvidencePanel matchId={102}/>);
  await screen.findByRole('alert');expect(screen.queryByText('测试来源')).not.toBeInTheDocument();
});
it('ignores late old-match responses', async () => {
  let resolve!:(value:unknown)=>void;mocks.detail.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));const {rerender}=render(<RosterEvidencePanel matchId={101}/>);
  mocks.detail.mockResolvedValueOnce(fixture(102));rerender(<RosterEvidencePanel matchId={102}/>);await screen.findByText('测试来源');resolve({...fixture(),match:{...fixture().match,home_team_name:'过期球队'}});
  await waitFor(()=>expect(screen.queryByText('过期球队')).not.toBeInTheDocument());
});
it('rejects duplicate players and wrong team identities', async () => {
  const data=fixture();data.lineups.home.players[1].player_id=1;mocks.detail.mockResolvedValueOnce(data);render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByRole('alert')).toHaveTextContent('阵容球员格式不正确');
});
it('shows latest team injury source and historical boundary', async () => {
  mocks.detail.mockResolvedValue({...fixture(),injuries:[{snapshot_id:55,player_id:1,team_id:1,status:'injured',player_name_cn:'受伤球员',source:'伤停来源',snapshot_time:'2026-10-10T10:00:00',collected_at:'2026-10-10T10:05:00',impact_score:0}]});
  render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('受伤球员');expect(screen.getByText(/球队最新状态，不代表该场比赛赛前伤停/)).toBeInTheDocument();expect(screen.getByText('影响分 0.00')).toBeInTheDocument();expect(screen.getByText('伤停来源')).toBeInTheDocument();
});
it('does not certify legacy timestamps and scopes', async () => {
  const data=fixture();mocks.detail.mockResolvedValue({...data,availability_scope:undefined,lineups:{home:{...data.lineups.home,snapshot_time:undefined,source:undefined},away:null}});
  render(<RosterEvidencePanel matchId={101}/>);await screen.findAllByText(/可靠首发证据不足/);expect(screen.getByText(/旧接口未提供伤停去重范围/)).toBeInTheDocument();
});
it('keeps roster usable while independent feature and prediction reads fail', async () => {
  mocks.features.mockRejectedValue(new Error('特征失败'));mocks.predictions.mockRejectedValue(new Error('预测失败'));render(<MatchDetailPage matchId={101}/>);
  fireEvent.click(screen.getByRole('button',{name:'阵容与伤停'}));await screen.findByText('测试来源');expect(screen.getByRole('button',{name:/多维特征/})).toBeInTheDocument();
});
it('deduplicates overlapping refreshes and preserves selection only while player exists', async () => {
  render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('测试来源');fireEvent.click(screen.getByRole('button',{name:'选择球员 球员1'}));
  let resolve!:(v:unknown)=>void;mocks.detail.mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));const button=screen.getByRole('button',{name:'刷新阵容与伤停证据'});fireEvent.click(button);fireEvent.click(button);expect(mocks.detail).toHaveBeenCalledTimes(2);
  const data=fixture();data.lineups.home.players=data.lineups.home.players.slice(1);resolve(data);await waitFor(()=>expect(screen.queryByText('战术角色：边路')).not.toBeInTheDocument());
});
it('rejects lineup from another team', async () => {
  const data=fixture();data.lineups.home.team_id=2;mocks.detail.mockResolvedValueOnce(data);render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByRole('alert')).toHaveTextContent('阵容证据与所选球队不一致');
});
it('rejects invalid injury metrics instead of rendering NaN', async () => {
  mocks.detail.mockResolvedValueOnce({...fixture(),injuries:[{team_id:1,player_id:1,status:'injured',impact_score:NaN}]});render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByRole('alert')).toHaveTextContent('伤停证据格式不正确');
});
it('rejects duplicate current player injury states', async () => {
  const injury={team_id:1,player_id:1,status:'injured',impact_score:0};mocks.detail.mockResolvedValueOnce({...fixture(),injuries:[injury,injury]});render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByRole('alert')).toHaveTextContent('伤停球员重复或缺少标识');
});
it('does not certify eleven confirmed players with invalid snapshot time', async () => {
  const data=fixture();data.lineups.home.snapshot_time='bad time';mocks.detail.mockResolvedValue(data);render(<RosterEvidencePanel matchId={101}/>);await screen.findByText('测试来源');expect(screen.getAllByText(/可靠首发证据不足/).length).toBe(2);expect(screen.queryByText('Invalid Date')).not.toBeInTheDocument();
});
it('rejects foreign feature snapshots without blocking roster', async () => {
  mocks.features.mockResolvedValue({snapshots:[{match_id:102}]});render(<MatchDetailPage matchId={101}/>);expect(await screen.findByRole('alert')).toHaveTextContent('特征快照与所选比赛不一致');fireEvent.click(screen.getByRole('button',{name:'阵容与伤停'}));await screen.findByText('测试来源');
});
it('rejects foreign predictions with independent retry', async () => {
  mocks.predictions.mockResolvedValueOnce({predictions:[{match_id:102}]});render(<MatchDetailPage matchId={101}/>);fireEvent.click(screen.getByRole('button',{name:/模型预测/}));expect(await screen.findByRole('alert')).toHaveTextContent('预测与所选比赛不一致');fireEvent.click(screen.getByRole('button',{name:'刷新模型预测'}));await screen.findByText('暂无模型预测');
});
it('preserves collector clock time without assuming a timezone', async () => {
  render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByText('2026-10-09 19:00:00（时区未记录）')).toBeInTheDocument();
});
it('formats explicit timezone timestamps in Beijing time', async () => {
  const data=fixture();data.lineups.home.snapshot_time='2026-10-09T11:00:00Z';mocks.detail.mockResolvedValue(data);render(<RosterEvidencePanel matchId={101}/>);expect(await screen.findByText('2026-10-09 19:00:00（北京时间）')).toBeInTheDocument();
});
it('shows unknown query counts instead of zero when feature and prediction reads fail', async () => {
  mocks.features.mockRejectedValue(new Error('特征失败'));mocks.predictions.mockRejectedValue(new Error('预测失败'));render(<MatchDetailPage matchId={101}/>);await screen.findByRole('alert');expect(screen.getByRole('button',{name:'多维特征 (—)'})).toBeInTheDocument();expect(screen.getByRole('button',{name:'模型预测 (—)'})).toBeInTheDocument();
});
