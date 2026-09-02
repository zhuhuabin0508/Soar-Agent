// React Flow 节点类型映射
// 目录中所有节点类型统一渲染为 CustomNode（图标 / 颜色 / 状态由 nodeCatalog + CustomNode 提供）
// 通过遍历 nodeCatalog 动态生成，新增节点类型无需再手动登记。
import CustomNode from './CustomNode'
import { nodeCatalog } from '../../constants/nodeCatalog'

export const nodeTypes = nodeCatalog.reduce((acc, def) => {
  acc[def.type] = CustomNode
  return acc
}, {})
