import type { OfficialOddsIndex } from '../../core/types';

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
  return (
    <nav aria-label="赔率日期索引" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <button
        type="button"
        className={`fqp-btn${scope === 'current' ? ' fqp-btn-primary' : ''}`}
        aria-pressed={scope === 'current'}
        onClick={onCurrent}
      >
        当前 ({index.current.count})
      </button>
      {index.history.map((item) => {
        const selected = scope === 'history' && businessDate === item.business_date;
        return (
          <button
            type="button"
            key={item.business_date}
            className={`fqp-btn${selected ? ' fqp-btn-primary' : ''}`}
            aria-pressed={selected}
            onClick={() => onHistory(item.business_date)}
          >
            {item.business_date.slice(5)} ({item.match_count})
          </button>
        );
      })}
    </nav>
  );
}
