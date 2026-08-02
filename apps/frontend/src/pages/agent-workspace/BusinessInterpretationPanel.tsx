import { useState } from 'react';

type InterpretationResult = { task: { id: number; response: string } };

export default function BusinessInterpretationPanel({
  title, onRun,
}: { title: string; onRun: (focusQuestion: string) => Promise<InterpretationResult> }) {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<InterpretationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const run = async () => {
    setRunning(true); setError(null);
    try { setResult(await onRun(question.trim())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '解读生成失败'); }
    finally { setRunning(false); }
  };
  return <section className="business-interpretation" aria-label={title}>
    <div><strong>{title}</strong><span>仅在点击后调用一次模型，不影响预测、推荐、风控或结算。</span></div>
    <label className="fqp-label" htmlFor={`${title}-question`}>关注问题（可选）</label>
    <textarea id={`${title}-question`} className="fqp-input business-interpretation-input" maxLength={2000}
      value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：请说明数据缺口或信号冲突。" />
    <button type="button" className="fqp-btn fqp-btn-primary" disabled={running} onClick={() => void run()}>
      {running ? '生成中…' : `生成${title}`}
    </button>
    {error && <p className="business-interpretation-error" role="alert">{error}</p>}
    {result && <div className="business-interpretation-result"><b>模型输出仅供人工核验</b><pre>{result.task.response}</pre><small>已归档至智能工作台 · #{result.task.id}</small></div>}
  </section>;
}
