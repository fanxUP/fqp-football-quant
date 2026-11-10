import { useState } from 'react';
import type { OddsMovementMatch } from '../../core/types';
import { formatTimestamp } from '../../shared/utils';
import { OddsSeriesChart } from '../../visualization';
import ChartFrame from '../../visualization/core/ChartFrame';
import OddsSnapshotHeatmap from './OddsSnapshotHeatmap';

const CAPTURE_LABELS: Record<string, string> = {
  running: '采集中', complete: '采集完整', partial: '部分缺失',
  not_offered: '官方未开售', failed: '采集失败',
};

const REFERENCE_BRANDS = [
  { id: 'betfair', label: 'Betfair' },
  { id: 'crown', label: '皇冠 Crown' },
  { id: 'ysb', label: '易胜博' },
  { id: 'macau', label: '澳门' },
  { id: 'ladbrokes', label: '立博 Ladbrokes' },
  { id: 'william_hill', label: '威廉希尔 William Hill' },
  { id: 'pinnacle', label: '平博 Pinnacle' },
  { id: 'bet365', label: 'bet365' },
];

interface OddsMatchCardProps {
  match: OddsMovementMatch;
  playType: string;
  playLabel: string;
  historical: boolean;
}

export default function OddsMatchCard({ match, playType, playLabel, historical }: OddsMatchCardProps) {
  const [showHistory, setShowHistory] = useState(false);
  const capture = match.capture_status;
  const captureText = capture ? CAPTURE_LABELS[capture.status] || capture.status : '待首次采集';
  const kickoff = match.kickoff_time.replace('T', ' ').slice(0, 16);
  const latest = match.series.reduce((time, point) => Math.max(time, Date.parse(point.snapshot_time)), -Infinity);
  const anomalyCount = match.anomalies.length;
  const title = `[${match.official_match_code}] ${match.home_team_name} VS ${match.away_team_name}`;
  const subtitle = `${match.league_name} · 开赛 ${kickoff} · ${playLabel} · ${captureText}`;
  const sources = [
    { id: 'sporttery', label: '中国体彩', snapshots: match.series },
    ...(playType === 'spf'
      ? REFERENCE_BRANDS.map(brand => ({ ...brand, reference: match.reference_1x2?.[brand.id] }))
      : []),
  ];
  return (
    <article aria-label={`${match.official_match_code} ${match.home_team_name} 对 ${match.away_team_name}`}>
      <ChartFrame
        title={title}
        subtitle={`${subtitle}${anomalyCount ? ` · 检出 ${anomalyCount} 次异常波动` : ''}`}
        controls={<div className="be-match-meta"><a href={`#/matches/${match.id}`}>查看赛事详情</a></div>}
      >
        <OddsSnapshotHeatmap sources={sources} playType={playType} historical={historical} />
        {match.series.length > 0 ? <>
          <p className="be-note">中国体彩最新源快照：{formatTimestamp(new Date(latest).toISOString())}</p>
          <details className="odds-heat-history" onToggle={event => setShowHistory(event.currentTarget.open)}>
            <summary>查看历史走势</summary>
            {showHistory && <OddsSeriesChart data={match.series} playType={playType} title="历史走势" subtitle={playLabel} />}
          </details>
        </> : <p className="be-note">中国体彩：{capture?.failure_reason || `该比赛暂无${playLabel}赔率快照`}</p>}
      </ChartFrame>
    </article>
  );
}
