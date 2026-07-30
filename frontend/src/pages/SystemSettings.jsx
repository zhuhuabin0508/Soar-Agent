import { useEffect, useState, useCallback } from 'react'
import { systemConfigApi } from '../api/systemConfig'
import { hasPermission } from '../utils/permissions'
import {
  Section,
  TextInput,
  TextArea,
  NumberInput,
  CheckRow,
} from '../components/property/FormControls'

// 安全策略默认值（与后端 DEFAULT_SECURITY_POLICY 对应）
const DEFAULT_SECURITY_POLICY = {
  'security.session_timeout_minutes': 480,
  'security.max_login_attempts': 5,
  'security.lockout_duration_minutes': 15,
  'security.password_min_length': 8,
  'security.password_require_uppercase': true,
  'security.password_require_lowercase': true,
  'security.password_require_digit': true,
  'security.password_require_special': true,
}

// 系统设置页面：基础配置（平台名称/Logo/主题色/CORS/Webhook限流）+ 安全设置（等保策略）
function SystemSettings() {
  const [activeTab, setActiveTab] = useState('basic') // 'basic' | 'security'

  // 基础配置状态
  const [configs, setConfigs] = useState({})
  const [origConfigs, setOrigConfigs] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  // 安全策略状态
  const [security, setSecurity] = useState({ ...DEFAULT_SECURITY_POLICY })
  const [origSecurity, setOrigSecurity] = useState({ ...DEFAULT_SECURITY_POLICY })
  const [securityLoading, setSecurityLoading] = useState(false)
  const [securitySaving, setSecuritySaving] = useState(false)
  const [securityLoaded, setSecurityLoaded] = useState(false)
  const [securityError, setSecurityError] = useState('')

  const canView = hasPermission('system_config', 'view')
  const canEdit = hasPermission('system_config', 'edit')

  const load = useCallback(async () => {
    if (!canView) {
      setError('您没有查看系统配置的权限')
      setLoading(false)
      return
    }
    try {
      const data = await systemConfigApi.list()
      const map = {}
      ;(Array.isArray(data) ? data : []).forEach((c) => {
        map[c.key] = c.value || ''
      })
      setConfigs(map)
      setOrigConfigs(map)
      setError('')
    } catch (err) {
      setError(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [canView])

  // 加载等保安全策略
  const loadSecurity = useCallback(async () => {
    if (!canView) {
      setSecurityError('您没有查看系统配置的权限')
      return
    }
    setSecurityLoading(true)
    try {
      const data = await systemConfigApi.getSecurity()
      // 后端返回 { policy: { "security.xxx": ... } }
      const policy = { ...DEFAULT_SECURITY_POLICY, ...(data?.policy || {}) }
      setSecurity(policy)
      setOrigSecurity(policy)
      setSecurityError('')
      setSecurityLoaded(true)
    } catch (err) {
      setSecurityError(err.message || '加载安全策略失败')
    } finally {
      setSecurityLoading(false)
    }
  }, [canView])

  useEffect(() => {
    load()
  }, [load])

  // 切换到「安全设置」Tab 时懒加载策略（仅首次）
  useEffect(() => {
    if (activeTab === 'security' && !securityLoaded) {
      loadSecurity()
    }
  }, [activeTab, securityLoaded, loadSecurity])

  const setField = (key) => (value) => {
    setConfigs((prev) => ({ ...prev, [key]: value }))
    setSuccessMsg('')
  }

  const setSecurityField = (key) => (value) => {
    setSecurity((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    // 只提交有变更的字段
    const changed = {}
    Object.keys(configs).forEach((k) => {
      if (configs[k] !== origConfigs[k]) {
        changed[k] = configs[k]
      }
    })
    if (Object.keys(changed).length === 0) {
      window.alert('没有需要保存的变更')
      return
    }
    setSaving(true)
    setSuccessMsg('')
    try {
      await systemConfigApi.update(changed)
      setOrigConfigs({ ...configs })
      setSuccessMsg(`已保存 ${Object.keys(changed).length} 项配置`)
      // 若改了主题色，立即应用到页面
      if (changed.primary_color) {
        applyThemeColor(changed.primary_color)
      }
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSaving(false)
    }
  }

  // 保存安全策略（只提交有变更的字段）
  const handleSaveSecurity = async () => {
    const changed = {}
    Object.keys(security).forEach((k) => {
      if (security[k] !== origSecurity[k]) {
        changed[k] = security[k]
      }
    })
    if (Object.keys(changed).length === 0) {
      window.alert('没有需要保存的变更')
      return
    }
    setSecuritySaving(true)
    try {
      await systemConfigApi.updateSecurity(changed)
      setOrigSecurity({ ...security })
      window.alert(`安全策略已保存（共 ${Object.keys(changed).length} 项）`)
    } catch (err) {
      window.alert(`保存失败：${err.message || err}`)
    } finally {
      setSecuritySaving(false)
    }
  }

  // 应用主题色到 CSS 变量
  const applyThemeColor = (color) => {
    try {
      document.documentElement.style.setProperty('--brand-color', color)
    } catch {
      // ignore
    }
  }

  // 各 Tab 的未保存变更检测
  const basicDirty = Object.keys(configs).some(
    (k) => configs[k] !== origConfigs[k]
  )
  const securityDirty = Object.keys(security).some(
    (k) => security[k] !== origSecurity[k]
  )
  const dirty = activeTab === 'security' ? securityDirty : basicDirty
  const isSaving = activeTab === 'security' ? securitySaving : saving
  const tabError = activeTab === 'security' ? securityError : error

  // 顶部「刷新 / 保存变更」按钮按当前 Tab 分发
  const handleRefresh = () => {
    if (activeTab === 'security') {
      loadSecurity()
    } else {
      load()
    }
  }
  const handleSaveClick = () => {
    if (activeTab === 'security') {
      handleSaveSecurity()
    } else {
      handleSave()
    }
  }

  const tabs = [
    { key: 'basic', label: '基础配置' },
    { key: 'security', label: '安全设置' },
  ]

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">系统设置</h1>
          <span className="text-xs text-gray-500">
            {activeTab === 'security'
              ? '等保安全策略配置'
              : `平台级配置（共 ${Object.keys(configs).length} 项）`}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            className="btn-secondary btn-sm"
          >
            刷新
          </button>
          {canEdit && (
            <button
              type="button"
              onClick={handleSaveClick}
              disabled={isSaving || !dirty}
              className="btn-primary btn-sm"
            >
              {isSaving ? '保存中…' : '保存变更'}
            </button>
          )}
        </div>
      </header>

      {/* Tab 切换：基础配置 / 安全设置 */}
      <div className="flex items-center gap-1 border-b border-gray-800 bg-gray-900/30 px-6">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition ${
              activeTab === t.key
                ? 'border-brand-500 text-white'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        {tabError && (
          <div className="mb-4 w-full rounded-md border border-danger-500/40 bg-danger-500/10 px-4 py-2 text-sm text-red-300">
            {tabError}
          </div>
        )}
        {successMsg && activeTab === 'basic' && (
          <div className="mb-4 w-full rounded-md border border-success-500/40 bg-success-500/10 px-4 py-2 text-sm text-success-300">
            {successMsg}
          </div>
        )}

        {/* 基础配置 Tab */}
        {activeTab === 'basic' &&
          (loading ? (
            <div className="flex h-40 items-center justify-center text-sm text-gray-500">
              加载中...
            </div>
          ) : (
            <div className="mx-auto flex max-w-2xl flex-col gap-4">
              <Section title="平台基础" hint="控制顶栏品牌显示">
                <TextInput
                  label="平台名称"
                  value={configs.platform_name || ''}
                  onChange={setField('platform_name')}
                  placeholder="如：SOAR 平台"
                />
                <TextInput
                  label="Logo URL"
                  value={configs.logo_url || ''}
                  onChange={setField('logo_url')}
                  placeholder="https://example.com/logo.png"
                  hint="留空则使用默认文字 Logo"
                />
              </Section>

              <Section title="主题色" hint="应用于按钮、链接等强调色">
                <div className="flex items-center gap-4">
                  <input
                    type="color"
                    value={configs.primary_color || '#6366f1'}
                    onChange={(e) => setField('primary_color')(e.target.value)}
                    className="h-10 w-16 cursor-pointer rounded border border-gray-700 bg-gray-800"
                  />
                  <input
                    className="flex-1 rounded-md border border-gray-700 bg-gray-800 px-2.5 py-1.5 text-sm text-white outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
                    value={configs.primary_color || ''}
                    onChange={(e) => setField('primary_color')(e.target.value)}
                    placeholder="#6366f1"
                  />
                </div>
              </Section>

              <Section title="安全配置" hint="修改 CORS 白名单后需重启后端生效">
                <TextArea
                  label="CORS 白名单"
                  value={configs.cors_origins || ''}
                  onChange={setField('cors_origins')}
                  rows={3}
                  placeholder="http://localhost:8080,http://localhost:5173"
                  hint="逗号分隔的源地址列表"
                />
                <TextInput
                  label="Webhook 限流（次/分钟）"
                  value={configs.webhook_rate_limit || ''}
                  onChange={setField('webhook_rate_limit')}
                  placeholder="30"
                  hint="每个工作流 webhook 触发的频率上限"
                />
              </Section>

              {basicDirty && canEdit && (
                <div className="rounded-md border border-warning-500/40 bg-warning-500/10 px-4 py-2 text-xs text-amber-300">
                  您有未保存的变更，点击右上角「保存变更」生效。
                </div>
              )}
            </div>
          ))}

        {/* 安全设置 Tab */}
        {activeTab === 'security' && (
          <div className="mx-auto flex max-w-2xl flex-col gap-4">
            {securityLoading ? (
              <div className="flex h-40 items-center justify-center text-sm text-gray-500">
                加载中...
              </div>
            ) : (
              <>
                <Section title="登录与会话" hint="控制登录失败锁定与 Session 超时">
                  <NumberInput
                    label="Session 超时（分钟）"
                    value={security['security.session_timeout_minutes']}
                    onChange={setSecurityField('security.session_timeout_minutes')}
                    min={1}
                    hint="用户无操作超过该时长后自动登出"
                  />
                  <NumberInput
                    label="最大登录失败次数"
                    value={security['security.max_login_attempts']}
                    onChange={setSecurityField('security.max_login_attempts')}
                    min={1}
                    hint="超过该次数后账户将被锁定"
                  />
                  <NumberInput
                    label="账户锁定时长（分钟）"
                    value={security['security.lockout_duration_minutes']}
                    onChange={setSecurityField('security.lockout_duration_minutes')}
                    min={1}
                    hint="达到最大登录失败次数后的锁定时长"
                  />
                </Section>

                <Section title="密码策略" hint="控制新密码与修改密码时的复杂度要求">
                  <NumberInput
                    label="密码最小长度"
                    value={security['security.password_min_length']}
                    onChange={setSecurityField('security.password_min_length')}
                    min={1}
                  />
                  <div className="rounded-md border border-gray-800 bg-gray-800/40 p-2.5">
                    <div className="mb-1.5 block text-xs font-medium text-gray-400">
                      密码复杂度要求
                    </div>
                    <div className="flex flex-col gap-2">
                      <CheckRow
                        label="必须包含大写字母"
                        checked={security['security.password_require_uppercase']}
                        onChange={setSecurityField('security.password_require_uppercase')}
                      />
                      <CheckRow
                        label="必须包含小写字母"
                        checked={security['security.password_require_lowercase']}
                        onChange={setSecurityField('security.password_require_lowercase')}
                      />
                      <CheckRow
                        label="必须包含数字"
                        checked={security['security.password_require_digit']}
                        onChange={setSecurityField('security.password_require_digit')}
                      />
                      <CheckRow
                        label="必须包含特殊字符"
                        checked={security['security.password_require_special']}
                        onChange={setSecurityField('security.password_require_special')}
                      />
                    </div>
                  </div>
                </Section>

                {securityDirty && canEdit && (
                  <div className="rounded-md border border-warning-500/40 bg-warning-500/10 px-4 py-2 text-xs text-amber-300">
                    您有未保存的安全策略变更，点击右上角「保存变更」生效。
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default SystemSettings
