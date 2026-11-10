import { useMemo, type CSSProperties } from 'react';
import type { OddsMarketReference, OddsMovementPoint } from '../../core/types';
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
type OddsSource = {
  id: string;
  label: string;
  snapshots?: readonly OddsMovementPoint[];
  reference?: OddsMarketReference;
};
const SPF_COLUMNS = [
  { code: 'h', label: '主胜' }, { code: 'd', label: '平局' }, { code: 'a', label: '客胜' },
];

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
    const ranges = buildOptionRanges(source.snapshots ?? [], playType);
    for (const [code, { last }] of ranges) {
      if (!options.has(code)) options.set(code, last.point);
    }
    return { ...source, ranges, reference: playType === 'spf' ? source.reference : undefined };
  });
  const columns = playType === 'spf'
    ? SPF_COLUMNS
    : playType === 'bf'
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

function change(first: number, last: number) {
  // SP is stored to four decimal places; compare integer units at the tier boundaries.
  const opening = Math.round(first * 10_000);
  const delta = Math.round(last * 10_000) - opening;
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
        ? '体彩历史按小时采样，初始与最终取可用记录的首末。最终不代表已核实停售赔率。'
        : '体彩初始与最新取已采集记录的首末。'}让球赔率只比较同一盘口。</p>
    </div>
  );
}

function OddsOptionCell({ opening, latest, openingTime, latestTime, handicap, showHandicap, latestLabel }: {
  opening: number | null;
  latest: number | null;
  openingTime?: string;
  latestTime?: string;
  handicap?: number | null;
  showHandicap: boolean;
  latestLabel: string;
}) {
  const hasLine = typeof handicap === 'number' && Number.isFinite(handicap);
  const unavailable = opening == null ? '缺初始值'
    : latest == null ? '缺末次值'
    : showHandicap && !hasLine ? '盘口未知'
    : openingTime && latestTime && Date.parse(openingTime) === Date.parse(latestTime) ? '仅一笔'
    : null;
  const movement = opening != null && latest != null && !unavailable
    ? change(opening, latest)
    : { direction: 'flat', strength: 0, label: unavailable };
  return (
    <td>
      {showHandicap && hasLine && <small className="odds-heat-line">{handicap > 0 ? '+' : ''}{handicap} 球</small>}
      <div className="odds-heat-pair">
        <span className="odds-heat-opening" title={openingTime && `初始快照：${formatTimestamp(openingTime)}`}>
          <span className="odds-heat-sr-only">初始赔率：</span>{opening == null ? '—' : spFormat.format(opening)}
        </span>
        <span className="odds-heat-arrow" aria-hidden="true">→</span>
        {latest == null ? <span className="odds-heat-missing"><span className="odds-heat-sr-only">缺末次赔率</span>—</span> : <div className="odds-heat-cell" data-direction={movement.direction} data-strength={movement.strength}
          title={latestTime && `末次快照：${formatTimestamp(latestTime)}`}>
          <span className="odds-heat-sr-only">{latestLabel}：</span>
          <strong>{spFormat.format(latest)}</strong>
          <span>{movement.label}</span>
        </div>}
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
  const columnCount = Math.max(1, columns.length);

  return (
    <div className="odds-heat-scroll" role="region" aria-label="各来源赔率对照，可横向滚动" tabIndex={0}>
      <table className="odds-heat-table" aria-label="赔率快照对照" style={{ '--odds-option-count': columnCount } as CSSProperties}>
        <colgroup><col className="odds-heat-source-col" />{columns.length ? columns.map(({ code }) => <col key={code} />) : <col />}</colgroup>
        <thead><tr><th scope="col">赔率来源</th>{columns.length ? columns.map(({ code, label }) => <th key={code} scope="col">{label}</th>) : <th scope="col">赔率</th>}</tr></thead>
        <tbody>{rows.map(({ id, label, ranges, reference }) => (
          <tr key={id}>
            <th scope="row">{label}</th>
            {!ranges.size && !reference ? <td colSpan={columnCount} className="odds-heat-missing">暂无快照</td> : columns.map(({ code }, index) => {
              const range = ranges.get(code);
              if (range) return <OddsOptionCell key={code} opening={range.first.point.sp_value} latest={range.last.point.sp_value}
                openingTime={range.first.point.snapshot_time} latestTime={range.last.point.snapshot_time}
                handicap={range.last.point.handicap} showHandicap={playType === 'rqspf'} latestLabel={latestLabel} />;
              const opening = reference?.opening?.[index] ?? null;
              const latest = reference?.latest?.[index] ?? null;
              return opening != null || latest != null
                ? <OddsOptionCell key={code} opening={opening} latest={latest} showHandicap={false} latestLabel="末次赔率" />
                : <td key={code} className="odds-heat-missing"><span aria-hidden="true">—</span><span className="odds-heat-sr-only">暂无快照</span></td>;
            })}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}
