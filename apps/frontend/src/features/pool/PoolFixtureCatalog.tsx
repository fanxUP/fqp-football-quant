import { useEffect, useRef, useState } from 'react';
import { api } from '../../core/apiClient';
import type { PoolCatalogDetail, PoolCatalogFilters, PoolCatalogIssue, PoolCatalogPage, PoolGameType } from '../../core/types';
import Card from '../../shared/components/Card';
import './PoolFixtureCatalog.css';

const GAME_LABELS: Record<PoolGameType, string> = {
  t14c: '14场胜负彩', r9: '任选9场', bqc6: '6场半全场', jq4: '4场进球',
};
const STATES: Record<string, string> = {
  selling: '在售', closed: '已停售', unknown: '停售待核实', conflict: '销售证据冲突',
  suspended: '销售暂停', not_started: '未开售',
};
const REASONS: Record<string, string> = {
  missing_typed_source_identity: '缺少可核实来源ID', unverified_game_source: '玩法来源待核实',
  unverified_game_type: '玩法类型待核实', unverified_slot_layout: '原始槽位结构待核实',
  duplicate_fixture_slots: '来源槽位重复，待核实', source_id_evidence_mismatch: '来源ID证据不一致',
  ambiguous_official_identity: '存在多个竞彩候选', conflicting_fixture_bindings: '比赛关联证据冲突',
  source_namespace_collision: '同一来源存在多个比赛ID', source_identity_fields_conflict: '来源对阵信息冲突',
};
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '请稍后重试';
const formatTime = (value: string | null) => value ? new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(value)) : '待核实';

export default function PoolFixtureCatalog() {
  const [query, setQuery] = useState<PoolCatalogFilters>({ limit: 20, offset: 0 });
  const [draft, setDraft] = useState({ issue_no: '', date_from: '', date_to: '' });
  const [page, setPage] = useState<PoolCatalogPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [formError, setFormError] = useState('');
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<PoolCatalogIssue | null>(null);
  const [detail, setDetail] = useState<PoolCatalogDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const detailSequence = useRef(0);
  const filtersDirty = draft.issue_no.trim() !== (query.issue_no ?? '')
    || draft.date_from !== (query.date_from ?? '') || draft.date_to !== (query.date_to ?? '');

  useEffect(() => {
    let active = true;
    detailSequence.current++;
    setSelected(null); setDetail(null); setDetailError(''); setDetailLoading(false);
    setLoading(true); setError(''); setPage(null);
    void api.pool.catalog(query).then(result => {
      if (active) setPage(result);
    }).catch(e => { if (active) setError(errorMessage(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; detailSequence.current++; };
  }, [query, reload]);

  async function openIssue(issue: PoolCatalogIssue) {
    const sequence = ++detailSequence.current;
    setSelected(issue); setDetail(null); setDetailError(''); setDetailLoading(true);
    try {
      const result = await api.pool.catalogIssue(issue.id);
      if (sequence === detailSequence.current) setDetail(result);
    } catch (e) { if (sequence === detailSequence.current) setDetailError(errorMessage(e)); }
    finally { if (sequence === detailSequence.current) setDetailLoading(false); }
  }

  return <Card title="官方期次与选场" subtitle="四种传统足彩共用比赛目录；14场与任九保留各自期次，半全场与进球彩按实际比赛展示。" className="pool-catalog">
    <form className="pool-catalog__filters" onSubmit={event => {
      event.preventDefault();
      if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) {
        setFormError('起始日期不能晚于结束日期'); return;
      }
      setFormError('');
      setQuery({ ...query, issue_no: draft.issue_no.trim() || undefined,
        date_from: draft.date_from || undefined, date_to: draft.date_to || undefined, offset: 0 });
    }}>
      <label>查询玩法<select className="fqp-select" value={query.game_type ?? ''} onChange={event => {
        setFormError(''); setQuery({ ...query, game_type: (event.target.value || undefined) as PoolGameType | undefined, offset: 0 });
      }}>
        <option value="">全部玩法</option>
        {Object.entries(GAME_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>官方期号<input className="fqp-input" maxLength={64} value={draft.issue_no} placeholder="输入完整期号" onChange={e => setDraft({ ...draft, issue_no: e.target.value })} /></label>
      <label>开球起始日期<input className="fqp-input" type="date" value={draft.date_from} max="9999-12-30" onChange={e => setDraft({ ...draft, date_from: e.target.value })} /></label>
      <label>开球结束日期<input className="fqp-input" type="date" value={draft.date_to} max="9999-12-30" onChange={e => setDraft({ ...draft, date_to: e.target.value })} /></label>
      <button className="fqp-btn fqp-btn-primary" type="submit" disabled={loading}>查询期次</button>
      <button className="fqp-btn" type="button" onClick={() => {
        setDraft({ issue_no: '', date_from: '', date_to: '' }); setFormError(''); setQuery({ limit: 20, offset: 0 });
      }}>重置条件</button>
    </form>
    {formError && <p role="alert" className="pool-catalog__warning">{formError}</p>}
    {filtersDirty && <p role="status" className="pool-catalog__warning">查询条件已修改，请点击“查询期次”应用。</p>}
    <p className="pool-catalog__hint">日期按北京时间筛选：一期只要有一场符合范围就列出，查看时仍展示全期。赛季归属尚待核实，日期范围不等同于赛季。</p>
    <div aria-busy={loading}>
      {loading && <p role="status">正在查询官方期次…</p>}
      {error && <div role="alert" className="pool-catalog__warning">期次查询失败：{error} <button type="button" className="fqp-btn" onClick={() => setReload(v => v + 1)}>重试期次查询</button></div>}
      {page && <>
        <p role="status">共 {page.total} 期 · 当前显示 {page.issues.length} 期</p>
        {page.issues.length === 0 ? <p className="pool-catalog__empty">暂无符合条件的已采集期次。可调整条件；尚未采集不代表官方没有安排。</p> :
          <div className="pool-catalog__table-scroll" role="region" aria-label="官方期次列表" tabIndex={0}>
            <table className="fqp-table">
              <thead><tr><th scope="col">玩法 / 期号</th><th scope="col">选场材料</th><th scope="col">比赛身份</th><th scope="col">开球 / 销售状态</th><th scope="col">详情</th></tr></thead>
              <tbody>{page.issues.map(issue => <tr key={issue.id} aria-selected={selected?.id === issue.id}>
                <td>{GAME_LABELS[issue.game_type]}<br /><strong>{issue.issue_no}</strong></td>
                <td>{issue.stored_matches} / {issue.expected_matches} 场<br /><small>{issue.catalogue_complete ? '场序齐全' : '场序或来源待核实'}</small></td>
                <td><span className="pool-catalog__linked">已关联 {issue.linked_matches}</span><br />待核实 {issue.pending_matches} · <span className={issue.conflict_matches ? 'pool-catalog__warning' : ''}>冲突 {issue.conflict_matches}</span></td>
                <td>{formatTime(issue.first_kickoff)}<br /><small>{STATES[issue.state ?? 'unknown'] ?? '销售状态待核实'}</small></td>
                <td><button type="button" className="fqp-btn" aria-label={`查看${GAME_LABELS[issue.game_type]}第${issue.issue_no}期`} aria-pressed={selected?.id === issue.id} onClick={() => void openIssue(issue)}>查看比赛</button></td>
              </tr>)}</tbody>
            </table>
          </div>}
        <div className="pool-catalog__pagination">
          <button type="button" className="fqp-btn" aria-label="上一页期次" disabled={!query.offset} onClick={() => setQuery({ ...query, offset: Math.max(0, (query.offset ?? 0) - 20) })}>上一页</button>
          <span>第 {Math.floor((query.offset ?? 0) / 20) + 1} 页</span>
          <button type="button" className="fqp-btn" aria-label="下一页期次" disabled={(query.offset ?? 0) + 20 >= page.total || (query.offset ?? 0) >= 100000} onClick={() => setQuery({ ...query, offset: (query.offset ?? 0) + 20 })}>下一页</button>
        </div>
      </>}
    </div>
    {selected && <section className="pool-catalog__detail" aria-labelledby="pool-catalog-detail-title" aria-busy={detailLoading}>
      <div className="pool-catalog__detail-heading"><h4 id="pool-catalog-detail-title">{GAME_LABELS[selected.game_type]} · 第{selected.issue_no}期</h4><button type="button" className="fqp-btn" onClick={() => { detailSequence.current++; setSelected(null); setDetail(null); }}>收起比赛</button></div>
      {detailLoading && <p role="status">正在加载全期比赛…</p>}
      {detailError && <div role="alert" className="pool-catalog__warning">比赛列表加载失败：{detailError} <button type="button" className="fqp-btn" onClick={() => void openIssue(selected)}>重试比赛列表</button></div>}
      {detail && <>
        <p>全期 {detail.issue.stored_matches} 条选场记录 · {detail.issue.unique_fixtures} 个已关联比赛身份 · 停售时间：{formatTime(detail.issue.sale_stop)}</p>
        {!detail.issue.catalogue_complete && <p className="pool-catalog__warning">场序或玩法来源尚未核实完整；以下保留已采集材料。</p>}
        <p className="pool-catalog__hint">无竞彩关联的传统足彩比赛也会保留。身份已关联不代表赛季、赛果或预测数据已齐全。6场半全场和4场进球当前提供选场查询。</p>
        {detail.fixtures.length === 0 ? <p className="pool-catalog__empty">该期尚未采集到比赛材料。</p> :
          <div className="pool-catalog__table-scroll" role="region" aria-label="全期比赛列表" tabIndex={0}>
            <table className="fqp-table"><thead><tr><th scope="col">场序</th><th scope="col">联赛 / 对阵</th><th scope="col">开球（北京时间）</th><th scope="col">统一身份</th><th scope="col">竞彩关联</th></tr></thead>
              <tbody>{detail.fixtures.map(fixture => <tr key={fixture.match_order}>
                <td>{fixture.match_order}</td><td><small>{fixture.league || '联赛待核实'}</small><br />{fixture.home_team || '主队待核实'} vs {fixture.away_team || '客队待核实'}</td>
                <td>{formatTime(fixture.kickoff)}</td>
                <td><span className={fixture.identity_status === 'linked' ? 'pool-catalog__linked' : 'pool-catalog__warning'}>{fixture.identity_status === 'linked' ? `已关联 · 比赛 #${fixture.fixture_id}` : fixture.identity_status === 'conflict' ? '关联冲突' : '待核实'}</span>
                  {fixture.identity_status !== 'linked' && <><br /><small>{REASONS[fixture.identity_reason ?? ''] ?? '身份关联材料待核实'}</small></>}</td>
                <td>{fixture.official_match_id == null ? '无竞彩关联' : `竞彩 #${fixture.official_match_id}`}</td>
              </tr>)}</tbody>
            </table>
          </div>}
      </>}
    </section>}
  </Card>;
}
