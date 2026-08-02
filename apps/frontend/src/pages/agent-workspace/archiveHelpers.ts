import type { AgentWorkspaceReviewEvent, AgentWorkspaceTask } from '../../core/apiClient';

export function formatTime(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value)) : '时间未知';
}

function inlineText(value: string) {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/([`*_{}\[\]<>()[\]#+\-.!|])/g, '\\$1')
    .replace(/\r?\n/g, ' ');
}

function codeBlock(value: string) {
  const longestFence = Math.max(2, ...Array.from(value.matchAll(/`+/g), (match) => match[0].length));
  const fence = '`'.repeat(longestFence + 1);
  return `${fence}\n${value}\n${fence}`;
}

export function buildTaskMarkdown(task: AgentWorkspaceTask, reviewEvents: AgentWorkspaceReviewEvent[] = []) {
  const confirmation = task.reviewedAt ? `已人工确认：${formatTime(task.reviewedAt)}` : '待人工确认';
  const reviewNote = task.reviewNote ? `\n- 核验备注：${inlineText(task.reviewNote)}` : '';
  const history = reviewEvents.length
    ? `\n## 核验历史\n\n${reviewEvents.map((event) => `- ${event.action === 'confirmed' ? '已确认' : '已撤销确认'}：${formatTime(event.createdAt)}${event.reviewNote ? ` · ${inlineText(event.reviewNote)}` : ''}`).join('\n')}\n`
    : '\n## 核验历史\n\n- 尚无核验历史。\n';
  return `# ${inlineText(task.title)}\n\n- 任务编号：${task.id}\n- Agent：${inlineText(task.agentCode)}\n- 模型：${inlineText(task.providerCode)} · ${inlineText(task.model)}\n- 创建时间：${formatTime(task.createdAt)}\n- 人工确认：${confirmation}${reviewNote}\n\n> 模型输出为非可信内容，请人工核验后使用。\n\n## 任务材料\n\n${codeBlock(task.prompt)}\n\n## 分析结果\n\n${codeBlock(task.response)}\n${history}`;
}

export function downloadTaskMarkdown(task: AgentWorkspaceTask, reviewEvents: AgentWorkspaceReviewEvent[] = []) {
  const content = buildTaskMarkdown(task, reviewEvents);
  const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `智能工作台-${task.id}-${task.title.replace(/[^\u4e00-\u9fa5a-zA-Z0-9_-]/g, '_').slice(0, 32)}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
