import type { ReactNode } from 'react';
import LoadingSpinner from './LoadingSpinner';
import EmptyState from './EmptyState';
import { useLanguage } from '../../app/LanguageContext';

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
  if (loading) {
    return <LoadingSpinner text={translate('加载数据中...')} />;
  }

  if (rows.length === 0) {
    return <EmptyState icon="📋" title={translate(emptyText)} />;
  }

  return (
    <div className="fqp-table-scroll" role="region" aria-label={translate("数据表格")} tabIndex={0}>
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
            return (
              <tr
                key={key}
                className={onRowClick ? 'clickable' : undefined}
                data-selected={isSelected ? 'true' : undefined}
                onClick={() => onRowClick?.(row)}
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
