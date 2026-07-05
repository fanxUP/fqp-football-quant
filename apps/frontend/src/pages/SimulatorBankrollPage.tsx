import { useCallback, useEffect, useState } from 'react';
import { api } from '../core/apiClient';
import type { BankrollSummary, BankrollTransaction } from '../core/types';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import DataTable, { type Column } from '../shared/components/DataTable';
import ErrorState from '../shared/components/ErrorState';
import { useToast } from '../shared/components/Toast';
import { formatTimestamp } from '../shared/utils';

const TXN_TYPE_LABELS: Record<string, string> = {
  stake: '投注扣款',
  refund: '退款',
  prize: '中奖入账',
  deposit: '充值',
  reset: '重置',
  settlement: '结算',
};

export default function SimulatorBankrollPage() {
  const toast = useToast();
  const [summary, setSummary] = useState<BankrollSummary | null>(null);
  const [transactions, setTransactions] = useState<BankrollTransaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const fetchAll = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.simulator.bankroll.summary(),
      api.simulator.bankroll.transactions(50),
    ])
      .then(([summaryRes, txnRes]) => {
        setSummary(summaryRes);
        setTransactions(txnRes.transactions);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : '加载失败');
        setLoading(false);
      });
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleReset = async () => {
    setResetting(true);
    try {
      const res = await api.simulator.bankroll.reset();
      toast.success(`资金已重置，当前余额 ¥${res.balance.toLocaleString()}`);
      setShowResetConfirm(false);
      fetchAll();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '重置失败');
    } finally {
      setResetting(false);
    }
  };

  const pnlColor = summary
    ? summary.profit_loss >= 0
      ? 'var(--fqp-success)'
      : 'var(--fqp-danger)'
    : 'var(--fqp-text)';

  const columns: Column<BankrollTransaction>[] = [
    {
      key: 'id',
      title: 'ID',
      width: '60px',
      render: (v) => <span className="fqp-mono">#{String(v)}</span>,
    },
    {
      key: 'transaction_type',
      title: '类型',
      width: '90px',
      render: (v) => {
        const t = String(v);
        const colors: Record<string, string> = {
          stake: 'var(--fqp-danger)',
          refund: 'var(--fqp-success)',
          prize: 'var(--fqp-accent)',
        };
        return (
          <span style={{ color: colors[t] || 'var(--fqp-text)', fontSize: '12px' }}>
            {TXN_TYPE_LABELS[t] || t}
          </span>
        );
      },
    },
    {
      key: 'amount',
      title: '金额',
      width: '100px',
      render: (v) => {
        const amt = Number(v);
        const isPositive = amt > 0;
        return (
          <span
            className="fqp-mono"
            style={{
              fontWeight: 600,
              color: isPositive ? 'var(--fqp-success)' : 'var(--fqp-danger)',
            }}
          >
            {isPositive ? '+' : ''}¥{amt.toFixed(2)}
          </span>
        );
      },
    },
    {
      key: 'balance_after',
      title: '余额',
      width: '100px',
      render: (v) => (
        <span className="fqp-mono">¥{Number(v).toFixed(2)}</span>
      ),
    },
    {
      key: 'remark',
      title: '备注',
      width: '180px',
      render: (v) => <span style={{ fontSize: '12px' }}>{String(v) || '---'}</span>,
    },
    {
      key: 'transaction_time',
      title: '时间',
      width: '140px',
      render: (v) => (
        <span style={{ fontSize: '12px' }}>{formatTimestamp(v)}</span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="💰 虚拟资金" />
      <p style={{ color: 'var(--fqp-text-muted)', fontSize: '14px', marginTop: '-8px', marginBottom: '16px' }}>
        初始资金 ¥100,000.00 — 用于模拟投注练习
      </p>

      {showResetConfirm && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.5)', display: 'flex',
          alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: 'var(--fqp-bg-primary)', padding: '24px',
            borderRadius: '8px', maxWidth: '400px', width: '90%',
            border: '1px solid var(--fqp-border)',
          }}>
            <h3 style={{ margin: '0 0 12px' }}>⚠️ 确认重置资金</h3>
            <p style={{ fontSize: '14px', color: 'var(--fqp-text-muted)', marginBottom: '16px' }}>
              将清空所有交易记录，资金恢复为 ¥100,000.00。此操作不可撤销！
            </p>
            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <button className="fqp-btn fqp-btn-sm" onClick={() => setShowResetConfirm(false)}>
                取消
              </button>
              <button
                className="fqp-btn fqp-btn-primary"
                style={{ background: 'var(--fqp-danger)' }}
                onClick={handleReset}
                disabled={resetting}
              >
                {resetting ? '重置中...' : '确认重置'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Summary cards — staggered entrance */}
      {summary && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '12px',
          marginBottom: '16px',
        }}>
          <Card entranceDelay={0}>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">当前余额</div>
              <div className="fqp-stat-value" style={{ fontSize: '28px', color: 'var(--fqp-accent)' }}>
                ¥{summary.current_balance.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </Card>
          <Card entranceDelay={80}>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">累计投注</div>
              <div className="fqp-stat-value" style={{ fontSize: '28px' }}>
                ¥{summary.total_staked.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </Card>
          <Card entranceDelay={160}>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">累计中奖</div>
              <div className="fqp-stat-value" style={{ fontSize: '28px', color: 'var(--fqp-success)' }}>
                ¥{summary.total_won.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </Card>
          <Card entranceDelay={240}>
            <div style={{ textAlign: 'center' }}>
              <div className="fqp-stat-label">盈亏</div>
              <div className="fqp-stat-value" style={{ fontSize: '28px', color: pnlColor }}>
                {summary.profit_loss >= 0 ? '+' : ''}¥{summary.profit_loss.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
              </div>
              <div className="fqp-stat-sub" style={{ color: pnlColor }}>
                ROI: {(summary.roi * 100).toFixed(2)}%
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        <button className="fqp-btn fqp-btn-sm" onClick={fetchAll}>
          🔄 刷新
        </button>
        <button
          className="fqp-btn fqp-btn-sm"
          style={{ color: 'var(--fqp-danger)' }}
          onClick={() => setShowResetConfirm(true)}
        >
          🔃 重置资金
        </button>
      </div>

      {/* Transactions */}
      {error ? (
        <ErrorState message={error} onRetry={fetchAll} />
      ) : (
        <Card title="交易记录">
          <DataTable
            columns={columns}
            rows={transactions}
            rowKey={(r) => String(r.id)}
            emptyText="暂无交易记录"
            loading={loading}
          />
        </Card>
      )}
    </div>
  );
}
