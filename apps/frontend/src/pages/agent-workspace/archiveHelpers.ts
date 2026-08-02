import type { AgentWorkspaceTask } from '../../core/apiClient';

export function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '时间未知';
}

export function downloadTaskMarkdown(task: AgentWorkspaceTask) {
  const confirmation = task.reviewedAt ? `已人工确认：${formatTime(task.reviewedAt)}` : '待人工确认';
  const reviewNote = task.reviewNote ? `\n- 核验备注：${task.reviewNote}` : '';
  const content = `# ${task.title}\n\n- 任务编号：${task.id}\n- Agent：${task.agentCode}\n- 模型：${task.providerCode} · ${task.model}\n- 创建时间：${formatTime(task.createdAt)}\n- 人工确认：${confirmation}${reviewNote}\n\n> 模型输出为非可信内容，请人工核验后使用。\n\n## 任务材料\n\n${task.prompt}\n\n## 分析结果\n\n${task.response}\n`;
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `智能工作台-${task.id}-${task.title.replace(/[^\u4e00-\u9fa5a-zA-Z0-9_-]/g, '_').slice(0, 32)}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
