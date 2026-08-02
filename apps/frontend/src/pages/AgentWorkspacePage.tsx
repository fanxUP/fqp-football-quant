import PageHeader from '../shared/components/PageHeader';
import AgentWorkspace from './agent-workspace/AgentWorkspace';

/** Manual, non-persistent workspace for bounded model-assisted research tasks. */
export default function AgentWorkspacePage() {
  return (
    <div className="settings-page">
      <PageHeader
        title="智能工作台"
        subtitle="人工发起任务，模型仅提供分析结果，不会自动修改业务数据"
      />
      <AgentWorkspace />
    </div>
  );
}
