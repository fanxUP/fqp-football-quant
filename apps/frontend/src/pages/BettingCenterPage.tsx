import { useEffect, useMemo, useState } from 'react';
import PageHeader from '../shared/components/PageHeader';
import BettingTerminalPage from './BettingTerminalPage';
import TicketsPage from './TicketsPage';
import CompetitionPage from './CompetitionPage';

type BettingTab = 'bet-slip' | 'tickets' | 'competition';

interface BettingCenterPageProps {
  initialTab?: BettingTab;
}

const TABS: Array<{ code: BettingTab; label: string; description: string }> = [
  { code: 'bet-slip', label: '投注台', description: '官方赛事选号、混合过关、倍数、注数与理论奖金' },
  { code: 'tickets', label: '彩票', description: '我的彩票与 Agent 的彩票，按日期归档' },
  { code: 'competition', label: '比赛结果', description: '结算后的盈亏、ROI、命中与趋势视图' },
];

function readTabFromHash(): BettingTab | null {
  const [, query = ''] = window.location.hash.split('?');
  const tab = new URLSearchParams(query).get('tab');
  return TABS.some((item) => item.code === tab) ? (tab as BettingTab) : null;
}

export default function BettingCenterPage({ initialTab = 'bet-slip' }: BettingCenterPageProps) {
  const [activeTab, setActiveTab] = useState<BettingTab>(() => readTabFromHash() ?? initialTab);

  useEffect(() => {
    const syncFromHash = () => {
      setActiveTab(readTabFromHash() ?? initialTab);
    };
    window.addEventListener('hashchange', syncFromHash);
    return () => window.removeEventListener('hashchange', syncFromHash);
  }, [initialTab]);

  const activeMeta = useMemo(
    () => TABS.find((tab) => tab.code === activeTab) ?? TABS[0],
    [activeTab],
  );

  const switchTab = (tab: BettingTab) => {
    setActiveTab(tab);
    window.location.hash = `/betting?tab=${tab}`;
  };

  return (
    <div className="betting-center-page">
      <PageHeader
        title="投注中心"
        subtitle="投注台生成票，彩票管理票，比赛结果看结算与盈亏"
      />

      <div
        className="betting-center-tabs"
        role="tablist"
        aria-label="投注中心视图"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: '8px',
          margin: '16px 0',
        }}
      >
        {TABS.map((tab) => {
          const selected = tab.code === activeTab;
          return (
            <button
              key={tab.code}
              type="button"
              role="tab"
              aria-selected={selected}
              className="fqp-btn"
              onClick={() => switchTab(tab.code)}
              style={{
                minHeight: '64px',
                padding: '10px 12px',
                textAlign: 'left',
                borderColor: selected ? 'var(--fqp-accent)' : 'var(--fqp-border)',
                background: selected ? 'rgba(34, 197, 94, 0.12)' : 'var(--fqp-card-bg)',
              }}
            >
              <span style={{ display: 'block', fontWeight: 700, color: 'var(--fqp-text)' }}>
                {tab.label}
              </span>
              <span style={{ display: 'block', marginTop: '4px', fontSize: '12px', color: 'var(--fqp-text-muted)' }}>
                {tab.description}
              </span>
            </button>
          );
        })}
      </div>

      <div
        className="fqp-card betting-center-context"
        style={{
          marginBottom: '16px',
          padding: '12px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          gap: '12px',
          alignItems: 'center',
        }}
      >
        <div>
          <div style={{ color: 'var(--fqp-text)', fontWeight: 700 }}>{activeMeta.label}</div>
          <div style={{ color: 'var(--fqp-text-muted)', fontSize: '12px', marginTop: '2px' }}>
            {activeMeta.description}
          </div>
        </div>
        <div style={{ color: 'var(--fqp-text-muted)', fontSize: '12px' }}>
          投注确认 · 彩票台账 · 比赛结果
        </div>
      </div>

      {activeTab === 'bet-slip' && <BettingTerminalPage />}
      {activeTab === 'tickets' && <TicketsPage />}
      {activeTab === 'competition' && <CompetitionPage />}
    </div>
  );
}
