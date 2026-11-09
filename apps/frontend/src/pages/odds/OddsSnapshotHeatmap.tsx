import { useMemo, type CSSProperties } from 'react';
import type { OddsMovementPoint } from '../../core/types';
import { arrangeScoreOdds } from '../../features/betting-terminal/scoreOddsLayout';
import { formatTimestamp } from '../../shared/utils';
import './OddsSnapshotHeatmap.css';

const OPTION_ORDER: Record<string, string[]> = {
  spf: ['h', 'd', 'a'],
  rqspf: ['h', 'd', 'a'],
  zjq: ['0', '1', '2', '3', '4', '5', '6', '7'],
  bqc: ['33', '31', '30', '13', '11', '10', '03', '01', '00'],
};
const spFormat = new Intl.NumberFormat('zh-CN', { useGrouping: false, minimumFractionDigits: 2, maximumFractionDigits: 4 });

type Snapshot = { point: OddsMovementPoint; time: number };
type Range = { first: Snapshot; last: Snapshot };
type OddsSource = { id: string; label: string; snapshots: readonly OddsMovementPoint[] };

function buildOptionRanges(data: readonly OddsMovementPoint[], playType: string) {
  const options = new Map<string, { latest: Range; lines: Map<number | null, Range> }>();
  for (const point of data) {
    const time = Date.parse(point.snapshot_time);
    const snapshot = { point, time };
    const line = playType === 'rqspf' ? point.handicap ?? null : null;
    const existing = options.get(point.option_code);
    const range = existing?.lines.get(line) ?? { first: snapshot, last: snapshot };
    if (time < range.first.time || (time === range.first.time && point.snapshot_id > range.first.point.snapshot_id)) range.first = snapshot;
    if (isLater(snapshot, range.last)) range.last = snapshot;
    if (existing) {
      existing.lines.set(line, range);
      if (isLater(range.last, existing.latest.last)) existing.latest = range;
    } else {
      options.set(point.option_code, { latest: range, lines: new Map([[line, range]]) });
    }
  }

  return new Map(Array.from(options, ([code, { latest }]) => [code, latest]));
}

function buildComparison(sources: readonly OddsSource[], playType: string) {
  const options = new Map<string, OddsMovementPoint>();
  const rows = sources.map(source => {
    const ranges = buildOptionRanges(source.snapshots, playType);
    for (const [code, { last }] of ranges) {
      if (!options.has(code)) options.set(code, last.point);
    }
    return { id: source.id, label: source.label, ranges };
  });
  const columns = playType === 'bf'
    ? arrangeScoreOdds([...options.values()]).map(({ option, label }) => ({ code: option.option_code, label }))
    : [...new Set([...(OPTION_ORDER[playType] ?? []), ...options.keys()])].flatMap(code => {
      const option = options.get(code);
      return option ? [{ code, label: option.option_name || code }] : [];
    });
  return { columns, rows };
}

function isLater(candidate: Snapshot, reference: Snapshot) {
  return candidate.time > reference.time
    || (candidate.time === reference.time && candidate.point.snapshot_id > reference.point.snapshot_id);
}

function change(first: Snapshot, last: Snapshot, comparable: boolean) {
  if (first.time === last.time || !comparable) return { direction: 'flat', strength: 0, label: comparable ? '仅一笔' : '盘口未知' };
  // SP is stored to four decimal places; compare integer units at the tier boundaries.
  const opening = Math.round(first.point.sp_value * 10_000);
  const delta = Math.round(last.point.sp_value * 10_000) - opening;
  if (!delta) return { direction: 'flat', strength: 0, label: '持平' };
  const scaledDelta = Math.abs(delta) * 100;
  const magnitude = scaledDelta / opening;
  return {
    direction: delta > 0 ? 'up' : 'down',
    strength: scaledDelta >= opening * 15 ? 3 : scaledDelta >= opening * 5 ? 2 : 1,
    label: `${delta > 0 ? '↑' : '↓'} ${magnitude < 0.1 ? '<0.1' : magnitude.toFixed(1)}%`,
  };
}

export function OddsHeatmapLegend({ historical }: { historical: boolean }) {
  return (
    <div className="odds-heat-legend">
      <div className="odds-heat-key">
        <strong>赔率热力图</strong>
        <span className="odds-heat-cell" data-direction="down" data-strength="2">↓ 下调</span>
        <span className="odds-heat-cell" data-direction="flat">— 持平 / 无法比较</span>
        <span className="odds-heat-cell" data-direction="up" data-strength="2">↑ 上调</span>
      </div>
      <p>每个选项内：初始赔率 → {historical ? '最终赔率' : '最新赔率'}。颜色越深，变动越大：&lt;5%、5% 至不足 15%、≥15%。{historical
        ? '历史按小时采样，初始与最终取可用记录的首末。最终不代表已核实停售赔率。'
        : '初始与最新取已采集记录的首末。'}让球赔率只比较同一盘口。</p>
    </div>
  );
}

function OddsOptionCell({ range: { first, last }, showHandicap, latestLabel }: {
  range: Range;
  showHandicap: boolean;
  latestLabel: string;
}) {
  const { handicap } = last.point;
  const hasLine = typeof handicap === 'number' && Number.isFinite(handicap);
  const movement = change(first, last, !showHandicap || hasLine);
  return (
    <td>
      {showHandicap && hasLine && <small className="odds-heat-line">{handicap > 0 ? '+' : ''}{handicap} 球</small>}
      <div className="odds-heat-pair">
        <span className="odds-heat-opening" title={`初始快照：${formatTimestamp(first.point.snapshot_time)}`}>
          <span className="odds-heat-sr-only">初始赔率：</span>{spFormat.format(first.point.sp_value)}
        </span>
        <span className="odds-heat-arrow" aria-hidden="true">→</span>
        <div className="odds-heat-cell" data-direction={movement.direction} data-strength={movement.strength}
          title={`末次快照：${formatTimestamp(last.point.snapshot_time)}`}>
          <span className="odds-heat-sr-only">{latestLabel}：</span>
          <strong>{spFormat.format(last.point.sp_value)}</strong>
          <span>{movement.label}</span>
        </div>
      </div>
    </td>
  );
}

export default function OddsSnapshotHeatmap({ sources, playType, historical }: {
  sources: readonly OddsSource[];
  playType: string;
  historical: boolean;
}) {
  const { columns, rows } = useMemo(() => buildComparison(sources, playType), [sources, playType]);
  const latestLabel = historical ? '最终赔率' : '最新赔率';

  return (
    <div className="odds-heat-scroll" role="region" aria-label="各来源赔率对照，可横向滚动" tabIndex={0}>
      <table className="odds-heat-table" aria-label="赔率快照对照" style={{ '--odds-option-count': columns.length } as CSSProperties}>
        <colgroup><col className="odds-heat-source-col" />{columns.map(({ code }) => <col key={code} />)}</colgroup>
        <thead><tr><th scope="col">赔率来源</th>{columns.map(({ code, label }) => <th key={code} scope="col">{label}</th>)}</tr></thead>
        <tbody>{rows.map(({ id, label, ranges }) => (
          <tr key={id}>
            <th scope="row">{label}</th>
            {columns.map(({ code }) => {
              const range = ranges.get(code);
              return range
                ? <OddsOptionCell key={code} range={range} showHandicap={playType === 'rqspf'} latestLabel={latestLabel} />
                : <td key={code} className="odds-heat-missing"><span aria-hidden="true">—</span><span className="odds-heat-sr-only">暂无快照</span></td>;
            })}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
