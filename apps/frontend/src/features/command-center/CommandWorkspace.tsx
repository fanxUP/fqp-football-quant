import { lazy, Suspense, useState } from 'react';
import MatchOverview from './MatchOverview';
const ExecutionCenter = lazy(() => import('./ExecutionCenter'));
export default function CommandWorkspace() {
  const [mode, setMode] = useState<'matches' | 'executions'>('matches');
  return <div className="cc-command-workspace"><div className="cc-workspace-tabs" aria-label="指挥台视图"><button type="button" aria-pressed={mode === 'matches'} onClick={() => setMode('matches')}>比赛概览</button><button type="button" aria-pressed={mode === 'executions'} onClick={() => setMode('executions')}>Agent 与管线</button></div>{mode === 'matches' ? <MatchOverview /> : <Suspense fallback={<p role="status">加载任务工作台…</p>}><ExecutionCenter /></Suspense>}</div>;
}
