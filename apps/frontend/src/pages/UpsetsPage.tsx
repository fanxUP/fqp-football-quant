import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import UpsetDetailDialog from '../features/upsets/UpsetDetailDialog';
import { UpsetCard, UpsetMetrics } from '../features/upsets/UpsetOverview';
import type { UpsetDetail, UpsetFilters, UpsetLeagueOption, UpsetListItem, UpsetReport, UpsetSummary } from '../features/upsets/types';
import EmptyState from '../shared/components/EmptyState';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import PageHeader from '../shared/components/PageHeader';
import './UpsetsPage.css';

export default function UpsetsPage() {
  const [filters, setFilters] = useState<UpsetFilters>({});
  const [summary, setSummary] = useState<UpsetSummary | null>(null);
  const [items, setItems] = useState<UpsetListItem[]>([]);
  const [leagues, setLeagues] = useState<UpsetLeagueOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<UpsetDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [reports, setReports] = useState<UpsetReport[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryResponse, listResponse, leagueResponse, reportResponse] = await Promise.all([
        api.upsets.summary({ start_date: filters.start_date, end_date: filters.end_date }),
        api.upsets.list({ ...filters, limit: 50, offset: 0 }),
        api.upsets.leagues({ start_date: filters.start_date, end_date: filters.end_date }),
        api.upsets.reports(6),
      ]);
      setSummary(summaryResponse);
      setItems(listResponse.items);
      setLeagues(leagueResponse.items);
      setReports(reportResponse.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '加载冷门研究数据失败');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => { void load(); }, [load]);

  const openDetail = async (eventId: number) => {
    setDetailLoading(true);
    try { setDetail(await api.upsets.detail(eventId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '加载冷门复盘失败'); }
    finally { setDetailLoading(false); }
  };

  const updateFilter = (name: keyof UpsetFilters, value: string) => {
    setFilters((current) => ({ ...current, [name]: value || undefined }));
  };

  const allLeagueCount = leagues.reduce((total, league) => total + league.upset_count, 0);

  return (
    <div className="upset-page">
      <PageHeader title="冷门研究" subtitle="依据开赛前最后官方赔率识别，复盘模型、用户实票与 Agent 虚拟票" />

      <section className="upset-filters" aria-label="冷门筛选">
        <label>开始日期<input type="date" value={filters.start_date ?? ''} onChange={(event) => updateFilter('start_date', event.target.value)} /></label>
        <label>结束日期<input type="date" value={filters.end_date ?? ''} onChange={(event) => updateFilter('end_date', event.target.value)} /></label>
        <label className="upset-league-nav">联赛导航<select aria-label="联赛导航" value={filters.league_name ?? ''} onChange={(event) => updateFilter('league_name', event.target.value)}><option value="">全部联赛（{allLeagueCount}场）</option>{leagues.map((league) => <option key={league.league_name} value={league.league_name}>{league.league_name}（{league.upset_count}场）</option>)}</select></label>
        <label>冷门等级<select value={filters.level ?? ''} onChange={(event) => updateFilter('level', event.target.value)}><option value="">全部</option><option value="S">S级</option><option value="A">A级</option><option value="B">B级</option><option value="C">C级</option></select></label>
        <label>玩法<select value={filters.play_type ?? ''} onChange={(event) => updateFilter('play_type', event.target.value)}><option value="">全部</option><option value="spf">胜平负</option><option value="rqspf">让球胜平负</option><option value="bf">比分</option><option value="zjq">总进球</option><option value="bqc">半全场</option></select></label>
      </section>

      {loading ? <LoadingSpinner text="加载冷门研究数据..." size="lg" /> : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : (
        <>
          {summary && <UpsetMetrics summary={summary} />}
          {reports.length > 0 && (
            <section className="upset-reports" aria-label="冷门周期报告">
              <header><h2>周期报告</h2><span>日报 / 周报 / 月报</span></header>
              <div>
                {reports.map((report) => (
                  <article key={report.id}>
                    <strong>{report.report_type === 'daily' ? '日报' : report.report_type === 'weekly' ? '周报' : '月报'}</strong>
                    <span>{report.period_start} 至 {report.period_end}</span>
                    <small>{report.pdf_available ? 'Markdown · HTML · PDF' : 'Markdown · HTML'}</small>
                  </article>
                ))}
              </div>
            </section>
          )}
          {items.length === 0 ? <EmptyState icon="🧊" title="没有符合条件的冷门" description="调整日期、等级或玩法筛选" /> : (
            <section className="upset-list" aria-label="冷门比赛列表">
              {items.map((item) => <UpsetCard key={item.id} item={item} onOpen={() => void openDetail(item.id)} />)}
            </section>
          )}
        </>
      )}

      {detailLoading && <div className="upset-detail-loading" role="status">加载复盘...</div>}
      {detail && <UpsetDetailDialog detail={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}
