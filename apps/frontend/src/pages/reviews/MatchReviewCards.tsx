import { useEffect, useState } from 'react';
import { api } from '../../core/apiClient';
import type { MatchReviewCard } from '../../core/types';
import { modelNameLabel, optionLabel, playTypeLabel } from '../../shared/constants';
import EmptyState from '../../shared/components/EmptyState';
import ErrorState from '../../shared/components/ErrorState';
import LoadingSpinner from '../../shared/components/LoadingSpinner';
import './MatchReviewCards.css';

interface MatchReviewCardsProps {
  reviewDate: string;
}

function score(card: MatchReviewCard): string {
  const { homeGoals, awayGoals } = card.result;
  return homeGoals == null || awayGoals == null ? '待确认' : `${homeGoals} : ${awayGoals}`;
}

function percent(value: number | null): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export default function MatchReviewCards({ reviewDate }: MatchReviewCardsProps) {
  const [cards, setCards] = useState<MatchReviewCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.reviews.matchCards(reviewDate)
      .then((response) => {
        if (active) setCards(response.cards);
      })
      .catch(() => {
        if (active) setError('单场复盘数据加载失败');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [reviewDate]);

  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  if (!cards.length) {
    return <EmptyState title="暂无已确认赛果" description="此日期没有可用于单场复盘的官方已确认赛果。" />;
  }

  return (
    <section className="match-review-section" aria-label="单场复盘">
      <div className="match-review-section-title">
        <div>
          <h3>单场复盘</h3>
          <p>仅比较开赛前模型与赔率快照；新闻资料须保留来源并由人工核验。</p>
        </div>
        <span className="match-review-evidence-note">外部资料：需人工核验</span>
      </div>
      <div className="match-review-list">
        {cards.map((card) => (
          <article className="match-review-card" key={card.matchId}>
            <header className="match-review-card-header">
              <div>
                <span className="match-review-code">{card.officialCode}</span>
                <span className="match-review-league">{card.leagueName}</span>
              </div>
              <strong className="match-review-score">{score(card)}</strong>
            </header>
            <h4>{card.homeTeamName} <span>VS</span> {card.awayTeamName}</h4>
            <div className="match-review-columns">
              <section>
                <h5>赛前模型信号</h5>
                {card.modelSignals.length ? card.modelSignals.slice(0, 6).map((signal, index) => (
                  <div className="match-review-row" key={`${signal.modelName}-${signal.playType}-${signal.optionCode}-${index}`}>
                    <span>{modelNameLabel(signal.modelName)}</span>
                    <b>{playTypeLabel(signal.playType)} · {optionLabel(signal.playType, signal.optionCode)}</b>
                    <em>{percent(signal.modelProbability)}</em>
                  </div>
                )) : <p className="match-review-empty">未找到开赛前有效模型预测</p>}
              </section>
              <section>
                <h5>休市前赔率</h5>
                {card.oddsSignals.length ? card.oddsSignals.slice(0, 6).map((signal, index) => (
                  <div className="match-review-row" key={`${signal.playType}-${signal.optionCode}-${index}`}>
                    <span>{playTypeLabel(signal.playType)}</span>
                    <b>{signal.optionName || optionLabel(signal.playType, signal.optionCode)}</b>
                    <em>{signal.spValue?.toFixed(2) ?? '—'}</em>
                  </div>
                )) : <p className="match-review-empty">未找到休市前官方赔率快照</p>}
              </section>
              <section>
                <h5>赛前/赛后资料</h5>
                {card.evidence.length ? card.evidence.slice(0, 4).map((item, index) => (
                  <a className="match-review-evidence" key={`${item.sourceUrl}-${index}`} href={item.sourceUrl} target="_blank" rel="noreferrer">
                    <span>{item.phase === 'pre_match' ? '赛前' : '赛后'} · {item.sourceName}</span>
                    <b>{item.headline}</b>
                  </a>
                )) : <p className="match-review-empty">{card.evidenceStatus}</p>}
              </section>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
