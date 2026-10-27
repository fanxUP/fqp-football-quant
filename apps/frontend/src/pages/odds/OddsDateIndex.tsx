import type { OfficialOddsIndex } from '../../core/types';
import './OddsDateIndex.css';

interface OddsDateIndexProps {
  index: OfficialOddsIndex;
  scope: 'current' | 'history';
  businessDate?: string;
  onCurrent: () => void;
  onHistory: (businessDate: string) => void;
}

export default function OddsDateIndex({
  index,
  scope,
  businessDate,
  onCurrent,
  onHistory,
}: OddsDateIndexProps) {
  const dates = index.history.map(item => item.business_date).sort();
  const selected = scope === 'history'
    ? index.history.find(item => item.business_date === businessDate)
    : undefined;

  return (
    <nav aria-label="赔率日期索引" className="odds-date-index">
      <button
        type="button"
        className={`fqp-btn${scope === 'current' ? ' fqp-btn-primary' : ''}`}
        aria-pressed={scope === 'current'}
        onClick={onCurrent}
      >
        当前 ({index.current.count})
      </button>
      <label className="odds-date-index-field">
        <span>历史日期</span>
        <input
          type="date"
          aria-label="赔率历史日期"
          className="fqp-input"
          value={scope === 'history' ? businessDate ?? '' : ''}
          min={dates[0]}
          max={dates[dates.length - 1]}
          disabled={dates.length === 0}
          onChange={event => {
            const date = event.target.value;
            if (date) onHistory(date);
            else onCurrent();
          }}
        />
      </label>
      <span className="odds-date-index-summary" role="status">
        {selected ? `${selected.business_date} · ${selected.match_count} 场`
          : dates.length > 0 ? `可查询 ${dates.length} 个历史日期` : '暂无历史赔率记录'}
      </span>
    </nav>
  );
}
