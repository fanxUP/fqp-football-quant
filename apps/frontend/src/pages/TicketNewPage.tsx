import { useState, useRef } from 'react';
import { api } from '../core/apiClient';
import { navigate } from '../core/router';
import { ApiError } from '../core/types';
import PageHeader from '../shared/components/PageHeader';
import DisclaimerBanner, { PAGE_DEFAULTS } from '../shared/components/DisclaimerBanner';
import Card from '../shared/components/Card';
import StatusBadge from '../shared/components/StatusBadge';
import { toast } from '../shared/components/Toast';

interface ItemForm {
  match_id: string;
  play_type: string;
  option_code: string;
  option_name: string;
  sp_value: string;
}

interface OcrResult {
  success: boolean;
  ticket_no: string;
  pass_type: string;
  multiple: number;
  total_amount: number;
  items: {
    match_code: string;
    home_team: string;
    away_team: string;
    play_type: string;
    option_code: string;
    option_name: string;
    sp_value: number;
    handicap: string;
  }[];
  raw_text: string;
  ocr_engine: string;
  confidence: number;
  warnings: string[];
  filename: string;
  size_bytes: number;
}

const PLAY_TYPES = ['spf', 'rqspf', 'zjq', 'bf', 'bqc'];

export default function TicketNewPage() {
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // OCR state
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrResult, setOcrResult] = useState<OcrResult | null>(null);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  // ---- File handling ----

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate
    const allowed = ['image/png', 'image/jpeg', 'image/webp'];
    if (!allowed.includes(file.type)) {
      setOcrError('不支持的文件格式，请选择 PNG、JPG 或 WEBP 图片');
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setOcrError('文件过大，最大支持 10MB');
      return;
    }

    setSelectedFile(file);
    setOcrError(null);
    setOcrResult(null);

    // Generate preview
    const url = URL.createObjectURL(file);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(url);
  };

  // ---- OCR trigger ----

  const handleOcr = async () => {
    if (!selectedFile) return;

    setOcrLoading(true);
    setOcrError(null);
    setOcrResult(null);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 30000);

      const res = await fetch('/api/tickets/ocr', {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new Error(body || `HTTP ${res.status}`);
      }

      const data: OcrResult = await res.json();
      setOcrResult(data);

      if (data.success && data.items.length > 0) {
        // Auto-fill form from OCR results
        setTicket((prev) => ({
          ...prev,
          total_amount: String(data.total_amount || prev.total_amount || ''),
          pass_type: data.pass_type || prev.pass_type,
          multiple: String(data.multiple || prev.multiple || '1'),
          notes: data.ticket_no ? `票号: ${data.ticket_no}` : prev.notes,
        }));

        setItems(
          data.items.map((it) => ({
            match_id: it.match_code || '',
            play_type: it.play_type || 'spf',
            option_code: it.option_code || '',
            option_name: it.option_name || `${it.home_team} vs ${it.away_team}`.trim() || '',
            sp_value: String(it.sp_value || ''),
          })),
        );

        toast.success(`OCR 识别成功：${data.items.length} 场比赛`);
      } else {
        toast.warning('OCR 未能识别到完整比赛信息，请手动录入');
      }
    } catch (e) {
      const msg = (e as Error).name === 'AbortError'
        ? 'OCR 处理超时（30秒），请检查网络'
        : (e as Error).message || 'OCR 处理失败';
      setOcrError(msg);
      toast.error(msg);
    } finally {
      setOcrLoading(false);
    }
  };

  // ---- Validation ----

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

  // ---- Submit ----

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
      <DisclaimerBanner text={PAGE_DEFAULTS.tickets} type="page" />

      {/* ---- OCR Upload Section ---- */}
      <Card title="📷 拍照/截图识别（可选）" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {/* Upload area */}
          <div style={{ flex: '1', minWidth: '200px' }}>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
            <div
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: '2px dashed var(--fqp-border)',
                borderRadius: '8px',
                padding: '24px',
                textAlign: 'center',
                cursor: 'pointer',
                minHeight: '120px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'border-color 0.2s',
                background: selectedFile ? 'rgba(99,102,241,0.05)' : 'transparent',
              }}
            >
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt="票据预览"
                  style={{ maxWidth: '100%', maxHeight: '180px', borderRadius: '4px', objectFit: 'contain' }}
                />
              ) : (
                <>
                  <div style={{ fontSize: '28px', marginBottom: '8px' }}>📸</div>
                  <div style={{ fontSize: '13px', color: 'var(--fqp-text)', marginBottom: '4px' }}>
                    点击上传票据照片
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)' }}>
                    支持 PNG / JPG / WEBP，最大 10MB
                  </div>
                </>
              )}
            </div>
            {selectedFile && (
              <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--fqp-text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>{selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                <button
                  className="fqp-btn fqp-btn-sm"
                  onClick={() => {
                    setSelectedFile(null);
                    setPreviewUrl(null);
                    setOcrResult(null);
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                  style={{ fontSize: '11px' }}
                >
                  清除
                </button>
              </div>
            )}
          </div>

          {/* OCR trigger */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: '120px' }}>
            <button
              className="fqp-btn fqp-btn-primary"
              onClick={handleOcr}
              disabled={!selectedFile || ocrLoading}
              style={{ width: '100%' }}
            >
              {ocrLoading ? '⏳ 识别中...' : '🔍 开始识别'}
            </button>
            <div style={{ fontSize: '11px', color: 'var(--fqp-text-muted)', textAlign: 'center' }}>
              识别后请仔细核对
            </div>
          </div>
        </div>

        {/* OCR error */}
        {ocrError && (
          <div style={{
            marginTop: '12px',
            padding: '8px 12px',
            background: 'rgba(248,113,113,0.1)',
            border: '1px solid rgba(248,113,113,0.3)',
            borderRadius: '4px',
            fontSize: '12px',
            color: 'var(--fqp-red-neon)',
          }}>
            ❌ {ocrError}
          </div>
        )}

        {/* OCR result summary */}
        {ocrResult && (
          <div style={{
            marginTop: '12px',
            padding: '12px',
            background: ocrResult.success ? 'rgba(52,211,153,0.08)' : 'rgba(252,186,3,0.08)',
            border: `1px solid ${ocrResult.success ? 'rgba(52,211,153,0.3)' : 'rgba(252,186,3,0.3)'}`,
            borderRadius: '6px',
            fontSize: '12px',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <StatusBadge
                status={ocrResult.success ? 'ok' : 'warning'}
                label={ocrResult.success ? `识别成功 (${ocrResult.items.length} 场比赛)` : '部分识别'}
                dot
              />
              <span style={{ color: 'var(--fqp-text-muted)', fontSize: '11px' }}>
                引擎: {ocrResult.ocr_engine} | 置信度: {(ocrResult.confidence * 100).toFixed(0)}%
              </span>
            </div>
            {ocrResult.warnings.length > 0 && (
              <div style={{ fontSize: '11px', color: 'var(--fqp-warning)' }}>
                {ocrResult.warnings.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}
            {ocrResult.success && (
              <div style={{ fontSize: '11px', color: 'var(--fqp-success)', marginTop: '4px' }}>
                ✅ 表单已自动填充，请核对后提交
              </div>
            )}
          </div>
        )}
      </Card>

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
