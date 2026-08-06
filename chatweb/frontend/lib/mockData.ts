/**
 * mockData.ts - 已接真实后端,mock 已移除。仅保留 newId(供 ChatContext 生成消息 id)。
 * 数据类型见 lib/types.ts;事件 reducer 见 lib/events.ts。
 */
export function newId(prefix = "m"): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}
