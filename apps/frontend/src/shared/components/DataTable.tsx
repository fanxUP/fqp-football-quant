import type { ReactNode } from 'react';
import LoadingSpinner from './LoadingSpinner';
import EmptyState from './EmptyState';

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
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export default function DataTable<T = any>({
  columns,
  rows,
  onRowClick,
  emptyText = '暂无数据',
  loading = false,
  rowKey,
}: DataTableProps<T>) {
  if (loading) {
    return <LoadingSpinner text="加载数据中..." />;
  }

  if (rows.length === 0) {
    return <EmptyState icon="📋" title={emptyText} />;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="fqp-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{ width: col.width, textAlign: col.align || 'left' }}>
                {col.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey ? rowKey(row) : i}
              className={onRowClick ? 'clickable' : undefined}
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
          ))}
        </tbody>
      </table>
    </div>
  );
}
