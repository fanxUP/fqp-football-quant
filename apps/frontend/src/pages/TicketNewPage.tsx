import { useState } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import Card from '../shared/components/Card';
import { toast } from '../shared/components/Toast';

interface ItemForm {
  match_id: string;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: string;
}

const PLAY_TYPES = ['spf', 'rqspf', 'zjq', 'bf', 'bqc'];

export default function TicketNewPage() {
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const [ticket, setTicket] = useState({
    total_amount: '',
    pass_type: 'single',
    multiple: '1',
    notes: '',
    linked_simulation_id: '',
  });

  const [items, setItems] = useState<ItemForm[]>([
    { match_id: '', play_type: 'spf', option_code: '3', option_name: '主胜', sp_value: '' },
  ]);

  const updateTicket = (field: string, value: string) => {
    setTicket((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => ({ ...prev, [field]: '' }));
  };

  const updateItem = (idx: number, field: keyof ItemForm, value: string) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, [field]: value } : it)),
    );
  };

  const addItem = () => {
    setItems((prev) => [
      ...prev,
      { match_id: '', play_type: 'spf', option_code: '3', option_name: '主胜', sp_value: '' },
    ]);
  };

  const removeItem = (idx: number) => {
    if (items.length <= 1) return;
    setItems((prev) => prev.filter((_, i) => i !== idx));
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!ticket.total_amount || Number(ticket.total_amount) <= 0) {
      errs.total_amount = '请输入有效的投注金额';
    }
    items.forEach((it, i) => {
      if (!it.sp_value || Number(it.sp_value) <= 0) {
        errs[`item_${i}_sp`] = '请输入有效赔率';
      }
    });
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setSubmitting(true);

    try {
      const body = {
        ticket: {
          total_amount: Number(ticket.total_amount),
          pass_type: ticket.pass_type,
          multiple: Number(ticket.multiple),
          notes: ticket.notes || null,
          linked_simulation_id: ticket.linked_simulation_id
            ? Number(ticket.linked_simulation_id)
            : null,
        },
        items: items.map((it) => ({
          match_id: it.match_id ? Number(it.match_id) : null,
          play_type: it.play_type,
          option_code: it.option_code,
          option_name: it.option_name,
          sp_value: Number(it.sp_value),
        })),
      };

      const result = await api.realTickets.create(body);
      if (result.status === 'ok') {
        toast.success(`实票 #${result.ticket_id} 录入成功`);
        navigate(`/tickets/${result.ticket_id}`);
      } else {
        toast.error('录入失败');
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : '提交失败，请检查后端服务');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: '800px' }}>
      <PageHeader title="录入实票" />

      {/* Ticket fields */}
      <Card title="票单信息" style={{ marginBottom: '20px' }}>
        <div className="fqp-form-row">
          <div className="fqp-form-group">
            <label className="fqp-label">投注金额 (¥)</label>
            <input
              className="fqp-input"
              type="number"
              min="0"
              step="1"
              value={ticket.total_amount}
              onChange={(e) => updateTicket('total_amount', e.target.value)}
              placeholder="如: 10"
            />
            {errors.total_amount && <div className="fqp-form-error">{errors.total_amount}</div>}
          </div>
          <div className="fqp-form-group">
            <label className="fqp-label">过关方式</label>
            <select
              className="fqp-select"
              value={ticket.pass_type}
              onChange={(e) => updateTicket('pass_type', e.target.value)}
            >
              <option value="single">单关</option>
              <option value="2x1">2串1</option>
              <option value="3x1">3串1</option>
              <option value="4x1">4串1</option>
            </select>
          </div>
        </div>
        <div className="fqp-form-row">
          <div className="fqp-form-group">
            <label className="fqp-label">倍数</label>
            <input
              className="fqp-input"
              type="number"
              min="1"
              step="1"
              value={ticket.multiple}
              onChange={(e) => updateTicket('multiple', e.target.value)}
            />
          </div>
          <div className="fqp-form-group">
            <label className="fqp-label">绑定推荐票单 (可选)</label>
            <input
              className="fqp-input"
              type="number"
              placeholder="模拟推荐票单ID"
              value={ticket.linked_simulation_id}
              onChange={(e) => updateTicket('linked_simulation_id', e.target.value)}
            />
          </div>
        </div>
        <div className="fqp-form-group">
          <label className="fqp-label">备注</label>
          <textarea
            className="fqp-textarea"
            value={ticket.notes}
            onChange={(e) => updateTicket('notes', e.target.value)}
            placeholder="赛事备注、购买渠道等..."
            rows={2}
          />
        </div>
      </Card>

      {/* Items */}
      <Card
        title={`投注项 (${items.length})`}
        action={
          <button className="fqp-btn fqp-btn-sm" onClick={addItem}>
            + 添加
          </button>
        }
        style={{ marginBottom: '20px' }}
      >
        {items.map((it, idx) => (
          <div
            key={idx}
            style={{
              display: 'flex',
              gap: '10px',
              alignItems: 'flex-start',
              marginBottom: '12px',
              padding: '12px',
              background: 'var(--fqp-panel)',
              borderRadius: 'var(--fqp-radius-sm)',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ minWidth: '100px' }}>
              <label className="fqp-label">比赛编号</label>
              <input
                className="fqp-input"
                type="number"
                placeholder="可选"
                value={it.match_id}
                onChange={(e) => updateItem(idx, 'match_id', e.target.value)}
              />
            </div>
            <div style={{ minWidth: '100px' }}>
              <label className="fqp-label">玩法</label>
              <select
                className="fqp-select"
                value={it.play_type}
                onChange={(e) => updateItem(idx, 'play_type', e.target.value)}
              >
                {PLAY_TYPES.map((pt) => (
                  <option key={pt} value={pt}>{pt.toUpperCase()}</option>
                ))}
              </select>
            </div>
            <div style={{ minWidth: '80px' }}>
              <label className="fqp-label">选项</label>
              <select
                className="fqp-select"
                value={it.option_code}
                onChange={(e) => updateItem(idx, 'option_code', e.target.value)}
              >
                <option value="3">主胜</option>
                <option value="1">平局</option>
                <option value="0">客胜</option>
              </select>
            </div>
            <div style={{ minWidth: '150px' }}>
              <label className="fqp-label">选项名称</label>
              <input
                className="fqp-input"
                value={it.option_name}
                onChange={(e) => updateItem(idx, 'option_name', e.target.value)}
              />
            </div>
            <div style={{ minWidth: '100px' }}>
              <label className="fqp-label">赔率</label>
              <input
                className="fqp-input"
                type="number"
                min="0"
                step="0.01"
                placeholder="如 2.50"
                value={it.sp_value}
                onChange={(e) => updateItem(idx, 'sp_value', e.target.value)}
              />
              {errors[`item_${idx}_sp`] && (
                <div className="fqp-form-error">{errors[`item_${idx}_sp`]}</div>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: '2px' }}>
              <button
                className="fqp-btn fqp-btn-danger fqp-btn-sm"
                onClick={() => removeItem(idx)}
                disabled={items.length <= 1}
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </Card>

      {/* Submit */}
      <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
        <button className="fqp-btn" onClick={() => navigate('/tickets')}>
          取消
        </button>
        <button
          className="fqp-btn fqp-btn-primary"
          onClick={handleSubmit}
          disabled={submitting}
        >
          {submitting ? '提交中...' : '提交实票'}
        </button>
      </div>
    </div>
  );
}
