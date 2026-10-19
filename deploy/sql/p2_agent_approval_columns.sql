-- approval_tickets：Agent 高危工具确认字段（P2 阶段 6a）
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS kind VARCHAR(16) NOT NULL DEFAULT 'workflow';
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS tool_name VARCHAR(128);
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS tool_arguments TEXT;
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS agent_id INTEGER;
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS session_id VARCHAR(128);
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS requested_by INTEGER;
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS dedup_key VARCHAR(64);
ALTER TABLE approval_tickets ADD COLUMN IF NOT EXISTS result TEXT;

CREATE INDEX IF NOT EXISTS ix_approval_tickets_kind ON approval_tickets (kind);
CREATE INDEX IF NOT EXISTS ix_approval_tickets_tool_name ON approval_tickets (tool_name);
CREATE INDEX IF NOT EXISTS ix_approval_tickets_session_id ON approval_tickets (session_id);
CREATE INDEX IF NOT EXISTS ix_approval_tickets_dedup_key ON approval_tickets (dedup_key);
