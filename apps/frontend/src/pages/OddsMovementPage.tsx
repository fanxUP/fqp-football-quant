/** Date-indexed official odds movements. One batch request renders every match. */

import { useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { OddsMovementMatch, OfficialOddsIndex } from '../core/types';
import { ApiError } from '../core/types';
import Card from '../shared/components/Card';
import EmptyState from '../shared/components/EmptyState';
import ErrorState from '../shared/components/ErrorState';
import LoadingSpinner from '../shared/components/LoadingSpinner';
import PageHeader from '../shared/components/PageHeader';
import OddsDateIndex from './odds/OddsDateIndex';
import OddsMatchCard from './odds/OddsMatchCard';

type PlayTab = 'spf' | 'rqspf' | 'bf' | 'zjq' | 'bqc';
type Scope = 'current' | 'history';

const PLAY_TABS: PlayTab[] = ['spf', 'rqspf', 'bf', 'zjq', 'bqc'];
const PLAY_LABELS: Record<PlayTab, string> = {
  spf: '胜平负', rqspf: '让球胜平负', bf: '比分', zjq: '总进球', bqc: '半全场',
};

export default function OddsMovementPage() {
  const [index, setIndex] = useState<OfficialOddsIndex | null>(null);
  const [scope, setScope] = useState<Scope>('current');
  const [businessDate, setBusinessDate] = useState<string>();
  const [activePlay, setActivePlay] = useState<PlayTab>('spf');
  const [matches, setMatches] = useState<OddsMovementMatch[]>([]);
  const [indexLoading, setIndexLoading] = useState(true);
  const [contentLoading, setContentLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.official.oddsIndex()
      .then(setIndex)
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : '加载赔率日期索引失败'))
      .finally(() => setIndexLoading(false));
  }, []);

  useEffect(() => {
    setContentLoading(true);
    setError(null);
    api.dashboard.oddsMovements({
      scope,
      business_date: scope === 'history' ? businessDate : undefined,
      play_type: activePlay,
      resolution: scope === 'history' ? 'hour' : 'raw',
      limit: 200,
    })
      .then((response) => setMatches(response.matches))
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : '加载赔率走势失败'))
      .finally(() => setContentLoading(false));
  }, [activePlay, businessDate, scope]);

  if (indexLoading) return <LoadingSpinner text="加载赔率日期索引..." size="lg" />;
  if (!index && error) return <ErrorState message={error} onRetry={() => window.location.reload()} />;

  return (
    <div>
      <PageHeader
        title="赔率走势"
        subtitle="按日期查看全部比赛；开盘后每 30 分钟采集，开赛时最后采集一次"
      />

      {index && (
        <Card style={{ marginBottom: 20 }}>
          <OddsDateIndex
            index={index}
            scope={scope}
            businessDate={businessDate}
            onCurrent={() => { setScope('current'); setBusinessDate(undefined); }}
            onHistory={(date) => { setScope('history'); setBusinessDate(date); }}
          />
          <div
            role="tablist"
            aria-label="赔率玩法"
            style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--fqp-border)' }}
          >
            {PLAY_TABS.map((play) => (
              <button
                type="button"
                role="tab"
                aria-selected={activePlay === play}
                key={play}
                className={`fqp-btn${activePlay === play ? ' fqp-btn-primary' : ''}`}
                onClick={() => setActivePlay(play)}
              >
                {PLAY_LABELS[play]}
              </button>
            ))}
          </div>
        </Card>
      )}

      {contentLoading ? (
        <LoadingSpinner text="加载全部比赛走势..." />
      ) : error ? (
        <ErrorState message={error} />
      ) : matches.length === 0 ? (
        <EmptyState
          icon="📉"
          title={scope === 'current' ? '当前没有开盘比赛' : '该日期暂无赔率记录'}
          description={scope === 'current' ? '赛程开盘后会自动出现在这里' : '请选择其他历史日期'}
        />
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          {matches.map((match) => (
            <OddsMatchCard key={match.id} match={match} playLabel={PLAY_LABELS[activePlay]} />
          ))}
        </div>
      )}
    </div>
  );
}
