import type { UpsetListItem, UpsetSummary } from './types';

const PLAY_LABELS: Record<string, string> = {
  spf: '胜平负', rqspf: '让球胜平负', bf: '比分', zjq: '总进球', bqc: '半全场',
};

function Metric({ label, value, detail }: { label: string; value: string | number; detail?: string }) {
  return (
    <div className="upset-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

export function UpsetMetrics({ summary }: { summary: UpsetSummary }) {
  return (
    <section className="upset-metrics" aria-label="冷门统计">
      <Metric label="冷门比赛" value={summary.upset_count} detail={`已结算 ${summary.settled_match_count} 场`} />
      <Metric label="冷门发生率" value={`${(summary.upset_rate * 100).toFixed(1)}%`} />
      <Metric label="S/A级" value={summary.severe_count} detail={`S级 ${summary.extreme_count} 场`} />
      <Metric label="热门未打出" value={summary.favourite_failed_count} />
      <Metric label="用户涉及" value={summary.user_involved_count} />
      <Metric label="Agent涉及" value={summary.agent_involved_count} />
    </section>
  );
}

export function UpsetCard({ item, onOpen }: { item: UpsetListItem; onOpen: () => void }) {
  const reviewWaiting = item.review_status === 'waiting_data' || item.review_status === 'pending';
  return (
    <article className="upset-card">
      <header>
        <div>
          <span className="upset-code">{item.official_match_code}</span>
          <span className="upset-league">{item.league_name}</span>
          {item.kickoff_time && <span className="upset-time">{item.kickoff_time.slice(0, 16).replace("T", " ")}</span>}
        </div>
        <span className={`upset-level upset-level-${item.upset_level ?? 'fav'}`}>
          {item.upset_level ? `${item.upset_level}级冷门` : '热门未打出'}
        </span>
      </header>
      <h2>{item.home_team_name} {item.full_score} {item.away_team_name}</h2>
      <div className="upset-card-facts">
        <span>{PLAY_LABELS[item.primary_play_type] ?? item.primary_play_type}</span>
        <span>实际概率 {(item.actual_outcome_probability * 100).toFixed(1)}%</span>
        <span>意外度 {item.surprise_bits.toFixed(2)} bits</span>
      </div>
      <div className="upset-tags" aria-label="关联状态">
        {item.favourite_failed && <span>热门未打出</span>}
        {item.model_warned && <span>模型曾预警</span>}
        {item.user_bet_involved && <span>用户实票涉及</span>}
        {item.agent_bet_involved && <span>Agent虚拟票涉及</span>}
        <span className={reviewWaiting ? 'is-waiting' : 'is-ready'}>
          {reviewWaiting ? '等待详细证据' : '复盘已生成'}
        </span>
      </div>
      <button type="button" className="fqp-btn upset-open" onClick={onOpen}>查看复盘</button>
    </article>
  );
}
