const BEIJING_TIME_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/**
 * Format API timestamps in the product's Beijing-time business timezone.
 *
 * PostgreSQL audit columns are `timestamp without time zone` values stored in
 * UTC.  JSON therefore contains no suffix; append `Z` before parsing so the
 * browser does not mistake the value for its own local wall clock.
 */
export function formatTimestamp(value: string | unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '—';

  const raw = value.trim();
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const parsed = new Date(hasTimezone ? raw : `${raw}Z`);
  if (Number.isNaN(parsed.getTime())) return '—';

  const parts = Object.fromEntries(
    BEIJING_TIME_FORMATTER.formatToParts(parsed).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}
