import type { AgentWorkspaceComparison, AgentWorkspaceReviewEvent, AgentWorkspaceTask } from '../../core/apiClient';
import { agentLabel, reviewStatusLabel } from '../../shared/constants';

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
  return `# ${inlineText(task.title)}\n\n- 任务编号：${task.id}\n- 智能代理：${inlineText(agentLabel(task.agentCode))}\n- 模型：${inlineText(task.providerCode)} · ${inlineText(task.model)}\n- 创建时间：${formatTime(task.createdAt)}\n- 人工确认：${confirmation}${reviewNote}\n\n> 模型输出为非可信内容，请人工核验后使用。\n\n## 任务材料\n\n${codeBlock(task.prompt)}\n\n## 分析结果\n\n${codeBlock(task.response)}\n${history}`;
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

export function buildComparisonMarkdown(comparison: AgentWorkspaceComparison, tasks: AgentWorkspaceTask[]) {
  const conclusion = comparison.reviewNote ? inlineText(comparison.reviewNote) : '尚未填写人工结论。';
  const results = tasks.length
    ? tasks.map((task) => `## ${inlineText(agentLabel(task.agentCode))} · ${inlineText(task.providerCode)} · ${inlineText(task.model)}\n\n${codeBlock(task.response)}`).join('\n\n')
    : '尚无成功返回的模型结果。';
  return `# 多模型对比复核报告\n\n- 批次编号：${inlineText(comparison.id)}\n- 请求模型：${comparison.requestedAgentCodes.map((code) => inlineText(agentLabel(code))).join('、')}\n- 成功 / 失败：${comparison.succeededCount} / ${comparison.failedCount}\n- 批次状态：${reviewStatusLabel(comparison.status)}\n- 创建时间：${formatTime(comparison.createdAt)}\n- 完成时间：${formatTime(comparison.completedAt)}\n\n> 模型输出为非可信内容；以下人工结论由用户填写，仍应结合官方数据核验。\n\n## 人工结论\n\n${conclusion}\n\n## 模型原始结果\n\n${results}\n`;
}

export function downloadComparisonMarkdown(comparison: AgentWorkspaceComparison, tasks: AgentWorkspaceTask[]) {
  const url = URL.createObjectURL(new Blob([buildComparisonMarkdown(comparison, tasks)], { type: 'text/markdown;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `智能工作台-多模型对比-${comparison.id}.md`;
  anchor.click();
  URL.revokeObjectURL(url);
}
