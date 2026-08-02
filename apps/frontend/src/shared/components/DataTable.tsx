import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import LoadingSpinner from './LoadingSpinner';
import EmptyState from './EmptyState';
import { useLanguage } from '../../app/LanguageContext';

const ROW_ENTER_DELAY_STEP_MS = 30;
const ROW_ENTER_MAX_DELAY_MS = 300;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export interface Column<T = any> {
  key: string;
  title: string;
  render?: (value: unknown, row: T) => ReactNode;
  width?: string;
  align?: 'left' | 'right' | 'center';
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
interface DataTableProps<T = any> {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: (row: T) => void;
  emptyText?: string;
  loading?: boolean;
  rowKey?: (row: T) => string | number;
  selectedRowKey?: string | number | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function DataTable<T = any>({
  columns,
  rows,
  onRowClick,
  emptyText = '暂无数据',
  loading = false,
  rowKey,
  selectedRowKey,
}: DataTableProps<T>) {
  const { translate } = useLanguage();
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    requestAnimationFrame(() => setMounted(true));
  }, []);

  // Reset stagger when rows change
  useEffect(() => {
    setMounted(false);
    requestAnimationFrame(() => setMounted(true));
  }, [rows.length]);

  if (loading) {
    return <LoadingSpinner text={translate('加载数据中...')} />;
  }

  if (rows.length === 0) {
    return <EmptyState icon="📋" title={translate(emptyText)} />;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="fqp-table">
        <colgroup>
          {columns.map((col) => (
            <col key={col.key} style={{ width: col.width }} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{ width: col.width, textAlign: col.align || 'left' }}>
                {translate(col.title)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = rowKey ? rowKey(row) : i;
            const isSelected = selectedRowKey != null && String(key) === String(selectedRowKey);
            const entranceDelay = Math.min(i * ROW_ENTER_DELAY_STEP_MS, ROW_ENTER_MAX_DELAY_MS);
            return (
              <tr
                key={key}
                className={onRowClick ? 'clickable' : undefined}
                data-selected={isSelected ? 'true' : undefined}
                onClick={() => onRowClick?.(row)}
                style={{
                  animation: isSelected ? 'none' : undefined,
                  opacity: mounted ? 1 : 0,
                  transform: mounted ? 'translateX(0)' : 'translateX(-12px)',
                  transition: `opacity 0.25s ease ${entranceDelay}ms, transform 0.25s ease ${entranceDelay}ms`,
                }}
              >
                {columns.map((col) => {
                  const value = (row as Record<string, unknown>)[col.key];
                  return (
                    <td key={col.key} style={{ textAlign: col.align || 'left' }}>
                      {col.render ? col.render(value, row) : String(value ?? '')}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
