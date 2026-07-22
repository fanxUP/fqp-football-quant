import { useEffect, useRef } from 'react';
import type { UpsetDetail, UpsetTicketImpact } from './types';

const PLAY_LABELS: Record<string, string> = {
  spf: '胜平负', rqspf: '让球胜平负', bf: '比分', zjq: '总进球', bqc: '半全场',
};

function TicketRows({ title, prefix, tickets }: { title: string; prefix: string; tickets: UpsetTicketImpact[] }) {
  return (
    <section>
      <h3>{title}</h3>
      {tickets.length === 0 ? <p className="upset-muted">未涉及</p> : (
        <div className="upset-ticket-list">
          {tickets.map((ticket) => (
            <div key={ticket.ticket_id}>
              <strong>{prefix} #{ticket.ticket_id}</strong>
              <span>投入 ¥{Number(ticket.stake_amount ?? 0).toFixed(2)}</span>
              <span>盈亏 ¥{Number(ticket.profit_loss ?? 0).toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ReviewSection({ detail }: { detail: UpsetDetail }) {
  if (!detail.review) {
    return (
      <section className="upset-review-waiting" role="status">
        <h3>客观复盘</h3>
        <p>暂无充分证据，详细复盘等待数据补全。</p>
      </section>
    );
  }
  const facts = detail.review.facts_json.map((fact) => typeof fact === 'string' ? fact : fact.text).filter(Boolean);
  return (
    <section>
      <h3>客观复盘</h3>
      {detail.review.summary && <p>{detail.review.summary}</p>}
      {facts.length > 0 && <ul>{facts.map((fact) => <li key={fact}>{fact}</li>)}</ul>}
      <p className="upset-muted">
        数据完整度 {((detail.review.data_completeness ?? 0) * 100).toFixed(0)}% ·
        结论置信度 {((detail.review.confidence ?? 0) * 100).toFixed(0)}%
      </p>
    </section>
  );
}

export default function UpsetDetailDialog({ detail, onClose }: { detail: UpsetDetail; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); }, []);

  return (
    <div className="upset-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="upset-dialog" role="dialog" aria-modal="true" aria-labelledby="upset-detail-title">
        <header>
          <div>
            <span>{detail.event.official_match_code} · {detail.event.league_name}</span>
            <h2 id="upset-detail-title">
              {detail.event.home_team_name} {detail.event.full_home_goals}:{detail.event.full_away_goals} {detail.event.away_team_name}
            </h2>
          </div>
          <button ref={closeRef} type="button" className="fqp-btn" onClick={onClose} aria-label="关闭复盘">关闭</button>
        </header>

        <section>
          <h3>市场与赛果</h3>
          <div className="upset-signal-list">
            {detail.market_signals.map((signal) => (
              <article key={signal.id}>
                <strong>{PLAY_LABELS[signal.play_type] ?? signal.play_type}</strong>
                <span>实际结果 {signal.actual_outcome}</span>
                <span>临场概率 {(signal.actual_outcome_probability * 100).toFixed(1)}%</span>
                <span>开盘 {Object.entries(signal.opening_odds_json).map(([key, value]) => `${key}@${value}`).join(' · ')}</span>
                <span>临场 {Object.entries(signal.closing_odds_json).map(([key, value]) => `${key}@${value}`).join(' · ')}</span>
              </article>
            ))}
          </div>
        </section>

        <ReviewSection detail={detail} />
        <div className="upset-ticket-columns">
          <TicketRows title="用户实票影响" prefix="实票" tickets={detail.user_tickets} />
          <TicketRows title="Agent虚拟票影响" prefix="Agent票" tickets={detail.agent_tickets} />
        </div>
      </section>
    </div>
  );
}
