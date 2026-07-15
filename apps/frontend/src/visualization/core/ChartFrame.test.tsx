import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChartFrame from './ChartFrame';

describe('ChartFrame', () => {
  it('显示图表标题、上下文与更新时间', () => {
    render(
      <ChartFrame title="赔率走势" subtitle="胜平负 · SP" updatedAt="18:00">
        <div>图表内容</div>
      </ChartFrame>,
    );

    expect(screen.getByRole('heading', { name: '赔率走势' })).toBeInTheDocument();
    expect(screen.getByText('胜平负 · SP')).toBeInTheDocument();
    expect(screen.getByText('更新 18:00')).toBeInTheDocument();
    expect(screen.getByText('图表内容')).toBeInTheDocument();
  });

  it('空数据时不渲染图表内容', () => {
    render(
      <ChartFrame title="赔率走势" empty emptyReason="暂无官方快照">
        <div>不应显示</div>
      </ChartFrame>,
    );

    expect(screen.getByRole('status')).toHaveTextContent('暂无官方快照');
    expect(screen.queryByText('不应显示')).not.toBeInTheDocument();
  });

  it('错误时提供可读状态', () => {
    render(
      <ChartFrame title="赔率走势" error="赔率加载失败">
        <div />
      </ChartFrame>,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('赔率加载失败');
  });
});
