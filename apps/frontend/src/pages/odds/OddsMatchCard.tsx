import type { OddsMovementMatch } from '../../core/types';
import { OddsSeriesChart } from '../../visualization';

const CAPTURE_LABELS: Record<string, string> = {
  running: '采集中', complete: '采集完整', partial: '部分缺失',
  not_offered: '官方未开售', failed: '采集失败',
};

interface OddsMatchCardProps {
  match: OddsMovementMatch;
  playType: string;
  playLabel: string;
}

export default function OddsMatchCard({ match, playType, playLabel }: OddsMatchCardProps) {
  const capture = match.capture_status;
  const captureText = capture ? CAPTURE_LABELS[capture.status] || capture.status : '待首次采集';
  const kickoff = match.kickoff_time.replace('T', ' ').slice(0, 16);
  return (
    <article aria-label={`${match.official_match_code} ${match.home_team_name} 对 ${match.away_team_name}`}>
      <OddsSeriesChart
        data={match.series}
        playType={playType}
        title={`[${match.official_match_code}] ${match.home_team_name} vs ${match.away_team_name}`}
        subtitle={`${match.league_name} · 开赛 ${kickoff} · ${playLabel} · ${captureText}`}
        emptyReason={capture?.failure_reason || `该比赛暂无${playLabel}赔率快照`}
        anomalyCount={match.anomalies.length}
      />
    </article>
  );
}
