import { useEffect, useMemo, useState } from 'react';
import { useLanguage } from '../../app/LanguageContext';
import './ReviewDateIndex.css';

const DAYS_PER_PAGE = 7;
const CHINESE_WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
const ENGLISH_WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

interface ReviewDateIndexProps {
  dates: string[];
  selectedDate: string | null;
  onSelect: (date: string) => void;
}

function weekdayIndex(date: string): number {
  return new Date(`${date}T12:00:00Z`).getUTCDay();
}

export default function ReviewDateIndex({ dates, selectedDate, onSelect }: ReviewDateIndexProps) {
  const { language } = useLanguage();
  const orderedDates = useMemo(
    () => [...new Set(dates)].sort((left, right) => right.localeCompare(left)),
    [dates],
  );
  const pageCount = Math.max(1, Math.ceil(orderedDates.length / DAYS_PER_PAGE));
  const [page, setPage] = useState(0);

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount - 1));
  }, [pageCount]);

  const visibleDates = orderedDates.slice(page * DAYS_PER_PAGE, (page + 1) * DAYS_PER_PAGE);
  const isEnglish = language === 'en';

  return (
    <section className="review-date-index" aria-label={isEnglish ? 'Daily report date index' : '日报日期索引'}>
      <header className="review-date-index-header">
        <div>
          <h3>{isEnglish ? 'Date index' : '日期索引'}</h3>
          <p>{isEnglish ? `7 days per page · ${orderedDates.length} days` : `每周 7 天 · 共 ${orderedDates.length} 天`}</p>
        </div>
        <div className="review-date-index-pagination">
          <button
            type="button"
            className="review-date-index-arrow"
            aria-label={isEnglish ? 'View newer week' : '查看较新一周'}
            disabled={page === 0}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
          >
            ‹
          </button>
          <span aria-live="polite">
            {isEnglish ? `Week ${page + 1} / ${pageCount}` : `第 ${page + 1} / ${pageCount} 周`}
          </span>
          <button
            type="button"
            className="review-date-index-arrow"
            aria-label={isEnglish ? 'View older week' : '查看较早一周'}
            disabled={page >= pageCount - 1}
            onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
          >
            ›
          </button>
        </div>
      </header>

      <div className="review-date-index-viewport">
        <div className="review-date-index-list">
          {visibleDates.map((date) => {
            const selected = selectedDate === date;
            const day = weekdayIndex(date);
            return (
              <button
                key={date}
                type="button"
                className={`review-date-index-date${selected ? ' is-selected' : ''}`}
                aria-label={isEnglish ? `View daily report for ${date}` : `查看 ${date} 日报`}
                aria-pressed={selected}
                onClick={() => onSelect(date)}
              >
                <span>{isEnglish ? ENGLISH_WEEKDAYS[day] : CHINESE_WEEKDAYS[day]}</span>
                <time dateTime={date}>{date}</time>
                {selected && <small>{isEnglish ? 'Selected' : '已选'}</small>}
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
