// React Flow 节点类型映射
// 目录类型统一渲染为 CustomNode（图标 / 颜色由 nodeCatalog 提供）
import CustomNode from './CustomNode'

export const nodeTypes = {
  webhook_trigger: CustomNode,
  condition_branch: CustomNode,
  http_request: CustomNode,
  ai_agent: CustomNode,
  llm: CustomNode,
  block_ip: CustomNode,
  device_action: CustomNode,
  send_notification: CustomNode,
  tool: CustomNode,
  human_review: CustomNode,
  code_execute: CustomNode,
  loop: CustomNode,
  iteration: CustomNode,
  end: CustomNode,
}
