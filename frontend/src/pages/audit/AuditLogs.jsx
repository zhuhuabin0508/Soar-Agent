// 审计日志独立页（系统管理入口）：设备/接收器/数据源条目/解析模板等配置变更的
// 完整审计记录，管理员只读，支持按对象/操作人/时间/IP 多维筛选与 CSV 导出
import { ClipboardList } from 'lucide-react'
import { PageContainer, PageHeader } from '../../components/ui'
import AuditLogsPanel from '../../components/audit/AuditLogsPanel'

export default function AuditLogs() {
  return (
    <PageContainer>
      <PageHeader
        title="审计日志"
        description="记录设备、接收器、数据源条目、解析模板等配置的增删改与登录操作：操作人、对象、变更内容、来源 IP 全量留痕（只读，满足等保审计要求）"
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full bg-muted-foreground/15 px-3 py-1 text-xs text-muted-foreground">
            <ClipboardList className="h-3.5 w-3.5" />
            管理员只读
          </span>
        }
      />
      <AuditLogsPanel />
    </PageContainer>
  )
}
