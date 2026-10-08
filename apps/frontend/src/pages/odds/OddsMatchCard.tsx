import type { OddsMovementMatch } from '../../core/types';
import { formatTimestamp } from '../../shared/utils';
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
  const snapshotTimes = match.series.map(point => Date.parse(point.snapshot_time)).filter(Number.isFinite);
  const latest = snapshotTimes.length ? new Date(snapshotTimes.reduce((a, b) => Math.max(a, b))).toISOString() : null;
  return (
    <article aria-label={`${match.official_match_code} ${match.home_team_name} 对 ${match.away_team_name}`}>
      <div className="be-match-meta"><span>最新源快照：{latest ? formatTimestamp(latest) : '—'}</span><a href={`#/matches/${match.id}`}>查看赛事详情</a></div>
      <OddsSeriesChart
        data={match.series}
        playType={playType}
        title={`[${match.official_match_code}] ${match.home_team_name} VS ${match.away_team_name}`}
        subtitle={`${match.league_name} · 开赛 ${kickoff} · ${playLabel} · ${captureText}`}
        emptyReason={capture?.failure_reason || `该比赛暂无${playLabel}赔率快照`}
        anomalyCount={match.anomalies.length}
      />
    </article>
  );
}
