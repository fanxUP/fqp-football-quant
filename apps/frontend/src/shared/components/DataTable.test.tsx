import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DataTable, { type Column } from './DataTable';

interface Row {
  id: number;
  name: string;
}

describe('DataTable', () => {
  it('uses one colgroup model for headers and body columns', () => {
    const columns: Column<Row>[] = [
      { key: 'id', title: '编号', width: '80px' },
      { key: 'name', title: '名称', width: '180px' },
    ];

    const { container } = render(
      <DataTable
        columns={columns}
        rows={[{ id: 1, name: '上海海港' }]}
      />,
    );

    expect(screen.getByText('编号')).toBeInTheDocument();
    expect(screen.getByText('上海海港')).toBeInTheDocument();
    expect(container.querySelectorAll('colgroup col')).toHaveLength(2);
    expect(container.querySelector('colgroup col')?.getAttribute('style')).toContain('width: 80px');
  });
});
