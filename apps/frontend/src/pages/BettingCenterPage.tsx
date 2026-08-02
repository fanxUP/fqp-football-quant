import { useEffect, useState } from 'react';
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
  { code: 'tickets', label: '彩票', description: '我的彩票与智能代理的彩票，按日期归档' },
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
      >
        {TABS.map((tab) => {
          const selected = tab.code === activeTab;
          return (
            <button
              key={tab.code}
              type="button"
              role="tab"
              aria-selected={selected}
              className="fqp-btn betting-center-tab"
              data-active={selected}
              onClick={() => switchTab(tab.code)}
            >
              <span className="betting-center-tab-label">
                {tab.label}
              </span>
              <span className="betting-center-tab-description">
                {tab.description}
              </span>
              <span className="betting-center-tab-action" aria-hidden="true">
                点击进入 <span>→</span>
              </span>
            </button>
          );
        })}
      </div>

      {activeTab === 'bet-slip' && <BettingTerminalPage />}
      {activeTab === 'tickets' && <TicketsPage />}
      {activeTab === 'competition' && <CompetitionPage />}
    </div>
  );
}
