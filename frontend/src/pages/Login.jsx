// 登录页：左右分栏 + 品牌展示 + 玻璃态卡片 + 动态科技背景
//
// 设计要点：
// - 桌面端：左侧品牌大图 + 核心能力介绍；右侧登录表单
// - 移动端：居中卡片，保证响应式
// - 表单：输入框带图标、密码显隐、记住用户名、忘记密码弹窗
// - 交互：实时校验、字段级错误、加载状态、错误抖动、成功过渡、Enter 切换/提交
// - 已登录会话有效时自动跳转首页
// - 右侧背景加入网格光晕（避免纯黑平面）
// - 验证码 CSS 反色适配深色主题
// - Logo 通过 CSS filter 转为青色系，与主色统一
// - 登录按钮 Hover 光扫 + 卖点卡片 Hover 上浮
// - 多登录方式：可插拔注册表 LOGIN_METHOD_REGISTRY 驱动顶部 Tab（账号密码 / 动态验证码），
//   Tab 数据源为后端 /auth/login-methods（按用户名还可过滤）；
//   SSO 不进 Tab，走卡片下方「提供商区」（/auth/sso/providers）
// - 密码登录后的 OTP 两步验证（MFA 弹层）属于 password 方式的增强，逻辑保持不变
//
// 说明：扫码登录等更多方式需后端配合，接入时在 LOGIN_METHOD_REGISTRY 注册组件即可。
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RefreshCw, User, Lock, ShieldCheck, Eye, EyeOff, Loader2,
  AlertCircle, CheckCircle2, ChevronRight, Zap, Workflow, ShieldAlert,
  BookOpen, LifeBuoy, ShieldQuestion, FileText, X, Megaphone, ExternalLink,
  Building2, MessageCircle, Bird, KeyRound, Globe,
} from 'lucide-react'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import { useThemeStore } from '../store/themeStore'
import { toast } from '../store/toastStore'
import { Modal } from '../components/Dialog'

// 记住用户名持久化 key
const REMEMBER_KEY = 'soar_remember_username'

// 核心能力亮点（左侧品牌区）
const FEATURES = [
  {
    icon: Workflow,
    title: '智能编排',
    desc: '可视化拖拽工作流，AI 智能体协同响应安全事件',
    color: 'from-cyan-400/80 to-blue-500/80',
  },
  {
    icon: Zap,
    title: '自动化响应',
    desc: 'Webhook / 定时 / 事件多触发方式，秒级处置告警',
    color: 'from-amber-400/80 to-orange-500/80',
  },
  {
    icon: ShieldAlert,
    title: '安全运营',
    desc: '符合等保 2.0 安全设计要求，全程审计可追溯',
    color: 'from-emerald-400/80 to-teal-500/80',
  },
]

// 系统公告（可配置，预留从 system_config 读取的能力）
const ANNOUNCEMENT = {
  visible: false, // 设为 true 显示公告条
  type: 'info', // info | warning | success
  text: '系统将于 2026-08-15 02:00-04:00 进行例行维护，请提前保存工作',
}

// 全屏共享背景层：连续渐变（左深蓝 → 右极深蓝黑）+ 全屏网格 + 跨边界粒子 + 交界径向光晕
// 设计：左右两侧共用同一背景，从颜色上消除硬边界
function SharedBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* 1. 全屏连续渐变底色：左深蓝 → 品牌蓝 → 右极深蓝黑（参考用户建议的色谱） */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'linear-gradient(90deg, #0a1929 0%, #0d1f33 45%, rgba(13,31,51,0.6) 65%, rgba(6,11,20,0.95) 80%, #05080c 100%)',
        }}
      />

      {/* 2. 竖向雾化过渡带：在左右交界处（55%-90%）叠加渐变，把硬边柔化成自然雾化 */}
      <div
        className="absolute inset-y-0 left-[55%] w-[35%]"
        style={{
          background:
            'linear-gradient(90deg, rgba(10,25,41,0) 0%, rgba(10,25,41,0.4) 40%, rgba(5,8,12,0.8) 100%)',
        }}
      />

      {/* 3. 交界径向光晕：在分界处偏左放一个大模糊青蓝色光斑，把左右两侧「粘」在一起 */}
      <div
        className="absolute"
        style={{
          left: '50%',
          top: '40%',
          width: '800px',
          height: '800px',
          transform: 'translate(-50%, -50%)',
          background:
            'radial-gradient(circle, rgba(0,210,210,0.10) 0%, rgba(0,150,200,0.04) 40%, transparent 70%)',
          filter: 'blur(60px)',
        }}
      />

      {/* 4. 全屏网格底纹：左侧浓右侧淡，用 mask 自然衰减（跨边界，不在右侧突兀消失） */}
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(to right, #67e8f9 1px, transparent 1px), linear-gradient(to bottom, #67e8f9 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage:
            'linear-gradient(90deg, rgba(0,0,0,1) 0%, rgba(0,0,0,0.5) 60%, rgba(0,0,0,0.15) 85%, transparent 100%)',
          WebkitMaskImage:
            'linear-gradient(90deg, rgba(0,0,0,1) 0%, rgba(0,0,0,0.5) 60%, rgba(0,0,0,0.15) 85%, transparent 100%)',
        }}
      />

      {/* 5. 左侧主光晕（品牌区氛围） */}
      <div className="absolute -left-32 -top-32 h-[28rem] w-[28rem] rounded-full bg-cyan-500/15 blur-3xl animate-pulse-slow" />
      <div className="absolute -bottom-40 left-1/4 h-[32rem] w-[32rem] rounded-full bg-blue-600/12 blur-3xl animate-pulse-slow [animation-delay:1.5s]" />
      <div className="absolute left-1/4 top-1/4 h-72 w-72 rounded-full bg-violet-500/8 blur-3xl animate-pulse-slow [animation-delay:3s]" />

      {/* 6. 右侧点缀光晕（让右侧不空洞） */}
      <div className="absolute right-0 top-0 h-64 w-64 rounded-full bg-cyan-500/6 blur-3xl" />
      <div className="absolute -bottom-20 right-1/4 h-72 w-72 rounded-full bg-blue-600/5 blur-3xl" />

      {/* 7. 跨边界粒子点阵：运动轨迹横跨中间区域，在右侧逐渐变暗变小 */}
      {Array.from({ length: 22 }).map((_, i) => {
        const isRightSide = i % 3 === 0
        return (
          <span
            key={i}
            className="absolute rounded-full animate-float-particle"
            style={{
              left: `${(i * 37) % 100}%`,
              top: `${(i * 53) % 100}%`,
              width: isRightSide ? '2px' : '3px',
              height: isRightSide ? '2px' : '3px',
              backgroundColor: isRightSide ? 'rgba(103,232,249,0.2)' : 'rgba(103,232,249,0.45)',
              animationDelay: `${(i % 6) * 0.8}s`,
              animationDuration: `${8 + (i % 5)}s`,
            }}
          />
        )
      })}
    </div>
  )
}

// 左侧品牌展示区（桌面端可见，背景透明，由共享层提供）
function BrandPanel({ platformName }) {
  return (
    <div className="relative flex h-full flex-col justify-between overflow-hidden p-12">
      {/* 左侧局部光晕点缀（增强品牌区氛围，不影响整体过渡） */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-20 -top-20 h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl animate-pulse-slow" />
        <div className="absolute -bottom-32 left-1/4 h-80 w-80 rounded-full bg-blue-600/8 blur-3xl animate-pulse-slow [animation-delay:1.5s]" />
      </div>
      {/* Logo + 名称 */}
      <div className="relative flex items-center gap-3 animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
        <img
          src="/favicon.svg"
          alt="Logo"
          className="h-10 w-10 drop-shadow-[0_0_12px_rgba(34,211,238,0.4)]"
        />
        <span className="text-lg font-semibold tracking-wide text-cyan-50">
          {platformName}
        </span>
      </div>

      {/* 主标语 + 能力亮点 */}
      <div className="relative">
        <h1 className="text-4xl font-bold leading-tight text-white animate-fade-in-up" style={{ animationDelay: '0.4s' }}>
          智能编排
          <span className="mx-2 bg-gradient-to-r from-cyan-300 to-blue-400 bg-clip-text text-transparent">
            ·
          </span>
          自动化响应
          <span className="mx-2 bg-gradient-to-r from-cyan-300 to-blue-400 bg-clip-text text-transparent">
            ·
          </span>
          安全运营
        </h1>
        <p className="mt-3 text-base text-cyan-100/70 animate-fade-in-up" style={{ animationDelay: '0.5s' }}>
          一体化安全运营编排平台，让威胁响应更敏捷、更智能、更可控
        </p>

        <div className="mt-10 space-y-5">
          {FEATURES.map((f, idx) => (
            <div
              key={f.title}
              className="group flex items-start gap-4 rounded-xl p-2 transition-all duration-300 hover:-translate-y-0.5 hover:bg-white/5 animate-fade-in-up"
              style={{ animationDelay: `${0.6 + idx * 0.12}s` }}
            >
              <div
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${f.color} shadow-lg shadow-cyan-500/20 transition-transform duration-300 group-hover:scale-110 group-hover:shadow-cyan-400/40`}
              >
                <f.icon className="h-5 w-5 text-white" />
              </div>
              <div>
                <div className="text-base font-semibold text-white transition-colors group-hover:text-cyan-200">
                  {f.title}
                </div>
                <div className="text-sm text-cyan-100/60">{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 底部版本信息 */}
      <div className="relative flex items-center gap-2 text-xs text-cyan-100/40 animate-fade-in-up" style={{ animationDelay: '1s' }}>
        <ShieldCheck className="h-3.5 w-3.5" />
        <span>符合等保 2.0 安全设计要求 · 端到端加密 · 全程审计可追溯</span>
      </div>
    </div>
  )
}

// 输入框字段（带图标 + 错误提示 + 聚焦发光；disabled 用于提交中锁定全部输入）
function Field({
  icon: Icon, type = 'text', value, onChange, placeholder, autoComplete,
  error, autoFocus, inputRef, onEnter, trailing, disabled, inputMode, maxLength,
}) {
  const [focused, setFocused] = useState(false)
  return (
    <div>
      <div
        className={`group relative flex items-center rounded-lg border bg-muted/60 transition-all ${
          focused
            ? 'border-primary/80 ring-2 ring-primary/30 shadow-[0_0_0_4px_rgba(34,211,238,0.08)]'
            : error
            ? 'border-destructive/70'
            : 'border-border hover:border-primary/40'
        } ${disabled ? 'opacity-60' : ''}`}
      >
        {Icon && (
          <div className={`pointer-events-none absolute left-3 ${focused ? 'text-primary' : error ? 'text-destructive' : 'text-muted-foreground/70'}`}>
            <Icon className="h-4 w-4" />
          </div>
        )}
        <input
          ref={inputRef}
          type={type}
          value={value}
          onChange={onChange}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && onEnter) onEnter()
          }}
          autoComplete={autoComplete}
          placeholder={placeholder}
          autoFocus={autoFocus}
          disabled={disabled}
          inputMode={inputMode}
          maxLength={maxLength}
          className={`w-full bg-transparent py-3 text-sm text-foreground placeholder-muted-foreground/60 outline-none ${
            Icon ? 'pl-10' : 'pl-3.5'
          } pr-10`}
        />
        {trailing}
      </div>
      {error && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-destructive">
          <AlertCircle className="h-3 w-3" />
          <span>{error}</span>
        </div>
      )}
    </div>
  )
}

// 忘记密码弹窗
function ForgotPasswordModal({ open, onClose }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="找回密码"
      maxWidth="max-w-md"
      footer={
        <button type="button" onClick={onClose} className="btn-primary btn-sm">
          我知道了
        </button>
      }
    >
      <div className="space-y-3 text-sm text-muted-foreground">
        <p>如忘记密码，请通过以下方式重置：</p>
        <ul className="ml-5 list-disc space-y-1.5">
          <li>联系系统管理员重置密码（管理员可在「用户管理」中操作）</li>
          <li>拨打运维支持电话：<span className="text-primary">400-xxx-xxxx</span></li>
          <li>发送邮件至：<a href="mailto:soar-admin@company.com" className="text-primary hover:underline">soar-admin@company.com</a></li>
        </ul>
        <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-xs text-warning/80">
          出于安全考虑，本平台暂不支持自助密码找回。管理员重置后，您首次登录将需要修改密码。
        </div>
      </div>
    </Modal>
  )
}

// 帮助弹窗
function HelpModal({ open, onClose }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="使用帮助"
      maxWidth="max-w-lg"
      footer={
        <button type="button" onClick={onClose} className="btn-primary btn-sm">
          关闭
        </button>
      }
    >
      <div className="space-y-3 text-sm text-muted-foreground">
        <div className="rounded-md border border-border bg-secondary/50 p-3">
          <div className="mb-1 font-medium text-foreground">默认管理员账号</div>
          <div className="font-mono text-xs">用户名：admin　密码：admin123</div>
          <div className="mt-1 text-xs text-warning/80">请登录后立即修改默认密码</div>
        </div>
        <div className="rounded-md border border-border bg-secondary/50 p-3">
          <div className="mb-1 font-medium text-foreground">浏览器兼容性</div>
          <div className="text-xs">推荐使用 Chrome 90+ / Edge 90+ / Firefox 88+ 浏览器，启用 JavaScript 与 Cookie</div>
        </div>
        <div className="rounded-md border border-border bg-secondary/50 p-3">
          <div className="mb-1 font-medium text-foreground">登录问题排查</div>
          <ul className="ml-4 list-disc text-xs space-y-1">
            <li>验证码区分大小写，可点击图片刷新</li>
            <li>连续失败 5 次账户将锁定 15 分钟</li>
            <li>会话过期后请重新登录，系统会保留原访问路径</li>
          </ul>
        </div>
      </div>
    </Modal>
  )
}

// SSO 提供商图标映射（id → lucide 图标，未命中回退 Globe）
const SSO_PROVIDER_ICONS = {
  wecom: Building2,
  dingtalk: MessageCircle,
  feishu: Bird,
  ldap: KeyRound,
  oidc: Globe,
  keycloak: Globe,
  authentik: Globe,
  google: Globe,
}

// 按提供商 id 取图标（大小写不敏感）
const getSsoProviderIcon = (id) => SSO_PROVIDER_ICONS[String(id || '').toLowerCase()] || Globe

// ============ 登录方式表单组件 ============
// 共享 props 约定（由父级 Login 提供，切换方式时保留 username / remember）：
//   username/onUsernameChange      共享用户名
//   remember/onRememberChange      共享「记住用户名」
//   persistRemember                提交时持久化记住用户名
//   loading/setLoading/success     共享加载与成功动画状态
//   errors/setErrors/validateField 共享字段级错误（username 等）
//   onServerError                  设置顶部错误横幅 serverError
//   onShake                        触发卡片抖动动画
//   onLoginSuccess                 统一登录成功处理（setAuth + 成功动画 + 跳转）
//   onRequiresOtp                  密码正确但需 MFA 二次验证（进入 otpStep）

// 账号密码登录表单（自原 Login 抽取，保留全部现有行为：
// 记住用户名、错误横幅、字段校验、抖动动画、验证码刷新、Enter 焦点切换、Hover 光扫）
function PasswordLoginForm({
  username, onUsernameChange, remember, onRememberChange, persistRemember,
  loading, setLoading, success, errors, setErrors, validateField,
  onServerError, onShake, onRequiresOtp, onLoginSuccess, onForgotPassword,
}) {
  // 方式专属字段（切换登录方式时组件卸载自动清空）
  const [password, setPassword] = useState('')
  const [captchaCode, setCaptchaCode] = useState('')
  const [captchaId, setCaptchaId] = useState('')
  const [captchaImage, setCaptchaImage] = useState('')
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  // 输入框引用（用于 Enter 切换焦点）
  const usernameRef = useRef(null)
  const passwordRef = useRef(null)
  const captchaRef = useRef(null)

  // 加载图形验证码
  // keepError=true 时保留 serverError（登录失败自动刷新验证码后仍显示错误提示，
  // 避免 setServerError('') 在同一批处理中覆盖掉刚设置的登录错误消息）
  const refreshCaptcha = useCallback(async (keepError = false) => {
    setCaptchaLoading(true)
    if (!keepError) onServerError('')
    try {
      const data = await authApi.getCaptcha()
      setCaptchaId(data.captcha_id)
      setCaptchaImage(data.image)
      setCaptchaCode('')
    } catch {
      onServerError('验证码加载失败，请刷新页面重试')
    } finally {
      setCaptchaLoading(false)
    }
  }, [onServerError])

  useEffect(() => {
    refreshCaptcha()
  }, [refreshCaptcha])

  // 挂载后自动聚焦（已记住用户名则聚焦密码框；仅在挂载时执行一次，避免抢焦点）
  useEffect(() => {
    const t = setTimeout(() => {
      if (username) passwordRef.current?.focus()
      else usernameRef.current?.focus()
    }, 100)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 整表校验（username 走共享校验器，password/captcha 为本方式专属）
  const validateAll = useCallback(() => {
    const u = validateField('username', username)
    const p = validateField('password', password)
    const c = validateField('captcha', captchaCode)
    return u && p && c
  }, [username, password, captchaCode, validateField])

  const handleSubmit = async (e) => {
    if (e) e.preventDefault()
    onServerError('')
    if (!validateAll()) {
      onShake()
      return
    }
    setLoading(true)
    try {
      // 记住用户名（不存储密码）
      persistRemember()

      const res = await authApi.login(
        username.trim(),
        password,
        captchaId,
        captchaCode.trim(),
      )

      // OTP 两步验证：密码正确但需 OTP 二次验证
      if (res.requires_otp && res.otp_pending_token) {
        onRequiresOtp(res.otp_pending_token)
        return
      }

      onLoginSuccess(res)
    } catch (err) {
      const msg = err.message || '登录失败，请重试'
      onServerError(msg)
      onShake()
      // 登录失败后刷新验证码（验证码已一次性消费）；保留错误提示
      refreshCaptcha(true)
      // 验证码错误时高亮验证码字段
      if (/验证码/.test(msg)) {
        setErrors((prev) => ({ ...prev, captcha: '验证码错误，请重新输入' }))
      }
      // 提示账号锁定等特定错误
      if (/锁定/.test(msg)) {
        setErrors((prev) => ({ ...prev, password: '账户已被锁定，请稍后重试' }))
      }
    } finally {
      setLoading(false)
    }
  }

  // Enter 键焦点切换
  const handleEnterUsername = () => passwordRef.current?.focus()
  const handleEnterPassword = () => captchaRef.current?.focus()
  const handleEnterCaptcha = () => handleSubmit()

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {/* 用户名 */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          用户名
        </label>
        <Field
          icon={User}
          type="text"
          value={username}
          onChange={(e) => {
            onUsernameChange(e.target.value)
            if (errors.username) validateField('username', e.target.value)
          }}
          placeholder="请输入用户名"
          autoComplete="username"
          error={errors.username}
          inputRef={usernameRef}
          onEnter={handleEnterUsername}
          disabled={loading || success}
        />
      </div>

      {/* 密码 */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          密码
        </label>
        <Field
          icon={Lock}
          type={showPassword ? 'text' : 'password'}
          value={password}
          onChange={(e) => {
            setPassword(e.target.value)
            if (errors.password) validateField('password', e.target.value)
          }}
          placeholder="请输入密码"
          autoComplete="current-password"
          error={errors.password}
          inputRef={passwordRef}
          onEnter={handleEnterPassword}
          disabled={loading || success}
          trailing={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              title={showPassword ? '隐藏密码' : '显示密码'}
              className="absolute right-3 text-muted-foreground/70 transition hover:text-foreground"
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          }
        />
      </div>

      {/* 验证码 */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          验证码
        </label>
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <Field
              icon={ShieldCheck}
              type="text"
              value={captchaCode}
              onChange={(e) => {
                setCaptchaCode(e.target.value)
                if (errors.captcha) validateField('captcha', e.target.value)
              }}
              placeholder="请输入图中字符"
              autoComplete="off"
              error={errors.captcha}
              inputRef={captchaRef}
              onEnter={handleEnterCaptcha}
              disabled={loading || success}
            />
          </div>
          <button
            type="button"
            onClick={refreshCaptcha}
            disabled={captchaLoading || loading || success}
            title="点击刷新验证码"
            className="group relative flex h-[46px] w-[140px] shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-muted/60 transition hover:border-primary/60 hover:bg-secondary disabled:opacity-60"
          >
            {captchaImage && !captchaLoading ? (
              <>
                {/* 验证码图片：CSS 反色适配深色主题 */}
                <img
                  src={captchaImage}
                  alt="验证码"
                  className="h-full w-full object-cover [filter:invert(1)_hue-rotate(180deg)_brightness(0.9)_contrast(1.1)]"
                />
                {/* Hover 显示刷新图标蒙层 */}
                <div className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 transition-opacity group-hover:opacity-100">
                  <RefreshCw className="h-4 w-4 text-cyan-300" />
                </div>
              </>
            ) : (
              <RefreshCw className={`h-4 w-4 text-muted-foreground ${captchaLoading ? 'animate-spin' : ''}`} />
            )}
          </button>
        </div>
        <button
          type="button"
          onClick={refreshCaptcha}
          disabled={captchaLoading || loading || success}
          className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground/60 transition hover:text-primary"
        >
          <RefreshCw className={`h-3 w-3 ${captchaLoading ? 'animate-spin' : ''}`} />
          <span>看不清？点击刷新验证码</span>
        </button>
      </div>

      {/* 记住用户名 + 忘记密码 */}
      <div className="flex items-center justify-between text-xs">
        <label className="flex cursor-pointer select-none items-center gap-2 text-muted-foreground">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => onRememberChange(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          <span>记住用户名</span>
        </label>
        <button
          type="button"
          onClick={onForgotPassword}
          className="font-medium text-primary transition hover:text-primary/80"
        >
          忘记密码？
        </button>
      </div>

      {/* 登录按钮（Hover 光扫 + 点击下沉） */}
      <button
        type="submit"
        disabled={loading || success}
        className={`group relative mt-2 flex h-11 w-full items-center justify-center gap-2 overflow-hidden rounded-lg text-sm font-medium transition-all ${
          success
            ? 'bg-success text-white'
            : 'bg-primary text-primary-foreground hover:shadow-[0_4px_20px_-4px_rgba(34,211,238,0.4)] active:scale-[0.98]'
        } disabled:cursor-not-allowed disabled:opacity-70`}
      >
        {/* Hover 光扫效果 */}
        {!loading && !success && (
          <span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
        )}
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            登录中...
          </>
        ) : success ? (
          <>
            <CheckCircle2 className="h-4 w-4" />
            登录成功
          </>
        ) : (
          <>
            登 录
            <ChevronRight className="h-4 w-4" />
          </>
        )}
      </button>
    </form>
  )
}

// 动态验证码登录表单（邮箱 OTP 直登）：输入用户名 → 获取验证码 → 输入 6 位码登录
function OtpLoginForm({
  username, onUsernameChange, remember, onRememberChange, persistRemember,
  loading, setLoading, success, errors, setErrors, validateField,
  onServerError, onShake, onLoginSuccess,
}) {
  // 方式专属字段（切换登录方式时组件卸载自动清空）
  const [otpCode, setOtpCode] = useState('')
  const [codeError, setCodeError] = useState('')
  const [sending, setSending] = useState(false)
  const [countdown, setCountdown] = useState(0)

  const usernameRef = useRef(null)
  const codeRef = useRef(null)

  // 获取验证码 60s 倒计时（组件卸载时清理定时器）
  useEffect(() => {
    if (countdown <= 0) return undefined
    const timer = setInterval(() => {
      setCountdown((c) => (c > 0 ? c - 1 : 0))
    }, 1000)
    return () => clearInterval(timer)
  }, [countdown > 0])

  // 挂载后自动聚焦（已记住用户名则聚焦验证码框）
  useEffect(() => {
    const t = setTimeout(() => {
      if (username) codeRef.current?.focus()
      else usernameRef.current?.focus()
    }, 100)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 发送动态验证码
  const handleSendOtp = async () => {
    const name = username.trim()
    if (!name) {
      validateField('username', '')
      usernameRef.current?.focus()
      return
    }
    if (sending || countdown > 0) return
    setSending(true)
    try {
      const res = await authApi.otpSend(name)
      if (res?.sent) {
        toast.success('验证码已发送')
        // 邮件未配置时后端返回 dev_code 兜底，直接提示给用户
        if (res.dev_code) toast.info(`开发模式验证码：${res.dev_code}`)
        setCountdown(60)
      }
    } catch (err) {
      const msg = err.message || '验证码发送失败'
      // 429=60s 内重复发送（验证码其实已发出）；400=不支持或未配置邮箱
      if (/429|频繁|稍后|too many/i.test(msg)) {
        toast.error('验证码已发送，请稍后再试')
      } else {
        toast.error(msg)
      }
    } finally {
      setSending(false)
    }
  }

  const handleSubmit = async (e) => {
    if (e) e.preventDefault()
    onServerError('')
    const name = username.trim()
    const code = otpCode.trim()
    // 校验：用户名非空 + 验证码为 6 位数字
    const userOk = validateField('username', name)
    const codeOk = /^\d{6}$/.test(code)
    setCodeError(codeOk ? '' : '请输入 6 位数字验证码')
    if (!userOk || !codeOk) {
      onShake()
      return
    }
    setLoading(true)
    try {
      // 记住用户名（与密码登录一致）
      persistRemember()
      const res = await authApi.otpDirectLogin(name, code)
      onLoginSuccess(res)
    } catch (err) {
      // 401=用户名或验证码错误，其余为后端具体原因，统一走顶部错误横幅
      onServerError(err.message || '用户名或验证码错误')
      onShake()
      setCodeError('验证码错误，请重试')
    } finally {
      setLoading(false)
    }
  }

  // Enter 键焦点切换
  const handleEnterUsername = () => codeRef.current?.focus()
  const handleEnterCode = () => handleSubmit()

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {/* 用户名（共享，切换方式时保留） */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          用户名
        </label>
        <Field
          icon={User}
          type="text"
          value={username}
          onChange={(e) => {
            onUsernameChange(e.target.value)
            if (errors.username) validateField('username', e.target.value)
          }}
          placeholder="用户名 / 手机号 / 邮箱"
          autoComplete="username"
          error={errors.username}
          inputRef={usernameRef}
          onEnter={handleEnterUsername}
          disabled={loading || success}
        />
      </div>

      {/* 动态验证码 + 获取验证码按钮 */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          动态验证码
        </label>
        <div className="flex gap-2">
          <div className="min-w-0 flex-1">
            <Field
              icon={ShieldCheck}
              type="text"
              inputMode="numeric"
              maxLength={6}
              value={otpCode}
              onChange={(e) => {
                setOtpCode(e.target.value.replace(/\D/g, ''))
                if (codeError) setCodeError('')
              }}
              placeholder="6 位数字验证码"
              autoComplete="one-time-code"
              error={codeError}
              inputRef={codeRef}
              onEnter={handleEnterCode}
              disabled={loading || success}
            />
          </div>
          <button
            type="button"
            onClick={handleSendOtp}
            disabled={sending || countdown > 0 || loading || success}
            className={`flex h-[46px] w-[130px] shrink-0 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-all ${
              countdown > 0
                ? 'cursor-not-allowed bg-muted text-muted-foreground'
                : 'bg-primary text-primary-foreground hover:shadow-[0_4px_20px_-4px_rgba(34,211,238,0.4)] active:scale-[0.98]'
            } disabled:cursor-not-allowed disabled:opacity-70`}
          >
            {sending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                发送中...
              </>
            ) : countdown > 0 ? (
              `${countdown}s 后重新获取`
            ) : (
              '获取验证码'
            )}
          </button>
        </div>
        <div className="mt-1.5 text-[11px] text-muted-foreground/60">
          验证码将发送至该账号绑定的邮箱
        </div>
      </div>

      {/* 记住用户名（与密码登录共享） */}
      <div className="flex items-center justify-between text-xs">
        <label className="flex cursor-pointer select-none items-center gap-2 text-muted-foreground">
          <input
            type="checkbox"
            checked={remember}
            onChange={(e) => onRememberChange(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-primary"
          />
          <span>记住用户名</span>
        </label>
      </div>

      {/* 登录按钮（Hover 光扫 + 点击下沉，与密码登录一致） */}
      <button
        type="submit"
        disabled={loading || success}
        className={`group relative mt-2 flex h-11 w-full items-center justify-center gap-2 overflow-hidden rounded-lg text-sm font-medium transition-all ${
          success
            ? 'bg-success text-white'
            : 'bg-primary text-primary-foreground hover:shadow-[0_4px_20px_-4px_rgba(34,211,238,0.4)] active:scale-[0.98]'
        } disabled:cursor-not-allowed disabled:opacity-70`}
      >
        {!loading && !success && (
          <span className="pointer-events-none absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/25 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
        )}
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            登录中...
          </>
        ) : success ? (
          <>
            <CheckCircle2 className="h-4 w-4" />
            登录成功
          </>
        ) : (
          <>
            登 录
            <ChevronRight className="h-4 w-4" />
          </>
        )}
      </button>
    </form>
  )
}

// 登录方式注册表：新增方式只需注册组件，Tab 自动渲染
// key 对应后端 login-methods 返回的 method id（sso 不进 Tab，走下方提供商区）
const LOGIN_METHOD_REGISTRY = {
  password: { label: '账号密码', icon: Lock, Component: PasswordLoginForm },
  otp: { label: '动态验证码', icon: ShieldCheck, Component: OtpLoginForm },
}

function Login() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  const [username, setUsername] = useState('')
  const [loading, setLoading] = useState(false)
  const [serverError, setServerError] = useState('')
  const [platformName, setPlatformName] = useState('SOAR 平台')
  const [version, setVersion] = useState('')

  // 登录方式 Tab：password / otp（由 LOGIN_METHOD_REGISTRY 驱动渲染）
  const [loginTab, setLoginTab] = useState('password')
  // 系统启用的登录方式（默认 ['password'] 避免加载期间闪烁；接口返回后更新）
  const [methods, setMethods] = useState(['password'])
  const [methodsLoaded, setMethodsLoaded] = useState(false)
  // 按用户名过滤后的可用方式（null=未过滤，展示系统全集）
  const [userMethods, setUserMethods] = useState(null)

  // SSO 提供商列表（空数组=未启用，整个 SSO 区不渲染）
  const [providers, setProviders] = useState([])
  const [providersLoaded, setProvidersLoaded] = useState(false)
  // 正在跳转授权的提供商 id（防止重复点击）
  const [ssoRedirecting, setSsoRedirecting] = useState('')

  // OTP 两步验证状态（密码登录正确后的 MFA 二次验证，属于 password 方式的增强）
  const [otpStep, setOtpStep] = useState(false) // 是否进入 OTP 第二步
  const [otpPendingToken, setOtpPendingToken] = useState('')
  const [otpCode, setOtpCode] = useState('')
  const otpRef = useRef(null)

  // 交互状态
  const [remember, setRemember] = useState(false)
  const [shake, setShake] = useState(false)
  const [success, setSuccess] = useState(false)
  const [forgotOpen, setForgotOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [announcement, setAnnouncement] = useState(ANNOUNCEMENT)

  // 字段级错误（username 共享；password/captcha/otp 由对应方式表单写入）
  const [errors, setErrors] = useState({ username: '', password: '', captcha: '', otp: '' })

  // 已登录会话有效则直接跳转首页（避免重复登录）
  useEffect(() => {
    if (isAuthenticated()) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, navigate])

  // 登录页固定暗色主题：不跟随用户/系统偏好，避免浅色偏好下白字变黑
  useEffect(() => {
    const root = document.documentElement
    root.classList.add('dark')
    root.style.colorScheme = 'dark'
    return () => {
      // 离开登录页后恢复用户主题偏好（主应用由 themeStore 接管）
      const { resolved } = useThemeStore.getState()
      if (resolved === 'light') {
        root.classList.remove('dark')
        root.style.colorScheme = 'light'
      }
    }
  }, [])

  // 加载平台名称、版本号与公告（无需认证）+ 登录方式 / SSO 提供商 + 处理 SSO 回调
  useEffect(() => {
    fetch('/api/v1/version')
      .then((r) => r.json())
      .then((d) => {
        if (d.platform_name) {
          setPlatformName(d.platform_name)
          document.title = `${d.platform_name} · 登录`
        }
        if (d.version) setVersion(d.version)
        // 预留：若后端返回 login_announcement 则覆盖
        if (d.login_announcement) {
          setAnnouncement({ visible: true, type: 'info', text: d.login_announcement })
        }
      })
      .catch(() => {})

    // 系统启用的登录方式（与 SSO 提供商并行请求）
    authApi.loginMethods()
      .then((res) => {
        // 只保留前端注册表支持的方式（后端未启用 / 前端未实现的不进 Tab）
        const list = (res?.methods || []).filter((m) => LOGIN_METHOD_REGISTRY[m])
        setMethods(list)
      })
      .catch(() => {
        // 接口失败：按未开放处理（若 SSO 提供商也为空则显示空状态）
        setMethods([])
      })
      .finally(() => setMethodsLoaded(true))

    // SSO 提供商列表（空数组=未启用）
    authApi.ssoProviders()
      .then((res) => {
        setProviders(Array.isArray(res?.providers) ? res.providers : [])
      })
      .catch(() => {
        // SSO 未开启或配置不完整，静默处理
        setProviders([])
      })
      .finally(() => setProvidersLoaded(true))

    // 处理 SSO 回调：URL 参数中携带 sso_token 时自动登录
    const params = new URLSearchParams(window.location.search)
    const ssoToken = params.get('sso_token')
    if (ssoToken) {
      // 清除 URL 参数
      window.history.replaceState({}, '', window.location.pathname)
      // 用 sso_token 获取用户信息并登录
      fetch('/api/v1/auth/me', {
        headers: { Authorization: `Bearer ${ssoToken}` },
      })
        .then((r) => r.ok ? r.json() : Promise.reject(new Error('SSO 令牌无效')))
        .then((user) => {
          setAuth(ssoToken, user)
          setSuccess(true)
          setTimeout(() => navigate('/dashboard', { replace: true }), 400)
        })
        .catch(() => {
          setServerError('SSO 登录失败，请重试')
          triggerShake()
        })
    }
  }, [])

  // 恢复「记住用户名」
  useEffect(() => {
    try {
      const saved = localStorage.getItem(REMEMBER_KEY)
      if (saved) {
        setUsername(saved)
        setRemember(true)
      }
    } catch {
      /* ignore */
    }
  }, [])

  // 实时校验（username 共享；password/captcha 由密码表单复用）
  const validateField = useCallback((field, value) => {
    let msg = ''
    if (field === 'username') {
      if (!value.trim()) msg = '请输入用户名'
    } else if (field === 'password') {
      if (!value) msg = '请输入密码'
    } else if (field === 'captcha') {
      if (!value.trim()) msg = '请输入验证码'
    }
    setErrors((prev) => ({ ...prev, [field]: msg }))
    return !msg
  }, [])

  // 触发抖动动画
  const triggerShake = useCallback(() => {
    setShake(true)
    setTimeout(() => setShake(false), 500)
  }, [])

  // 持久化「记住用户名」（各登录方式提交时统一调用，不存储密码）
  const persistRemember = useCallback(() => {
    try {
      if (remember) localStorage.setItem(REMEMBER_KEY, username.trim())
      else localStorage.removeItem(REMEMBER_KEY)
    } catch {
      /* ignore */
    }
  }, [remember, username])

  // 统一登录成功处理：setAuth + 重置过期标志 + 成功动画 + 跳转 dashboard
  const handleLoginSuccess = useCallback((res) => {
    setAuth(res.access_token, res.user)
    // 登录成功：重置认证过期标志（之前可能因 token 过期被设置）
    if (window.__SOAR_AUTH_EXPIRED__) window.__SOAR_AUTH_EXPIRED__ = false
    if (window.__SOAR_REFRESHING__) window.__SOAR_REFRESHING__ = false
    // 成功过渡动画后跳转
    setSuccess(true)
    setTimeout(() => navigate('/dashboard', { replace: true }), 400)
  }, [setAuth, navigate])

  // 密码正确但需 OTP 两步验证（MFA）：进入第二步弹层
  const handleRequiresOtp = useCallback((pendingToken) => {
    setOtpPendingToken(pendingToken)
    setOtpStep(true)
    setServerError('')
    setLoading(false)
    // 自动聚焦 OTP 输入框
    setTimeout(() => otpRef.current?.focus(), 100)
  }, [])

  // 用户名输入防抖 500ms：按用户过滤可用登录方式（用户名为空则恢复系统全集）
  useEffect(() => {
    const name = username.trim()
    if (!name) {
      setUserMethods(null)
      return undefined
    }
    const timer = setTimeout(() => {
      authApi.userLoginMethods(name)
        .then((res) => {
          // 只保留前端注册表支持的方式；接口失败静默忽略（Tab 保持现状）
          const list = (res?.methods || []).filter((m) => LOGIN_METHOD_REGISTRY[m])
          setUserMethods(list)
        })
        .catch(() => {})
    }, 500)
    return () => clearTimeout(timer)
  }, [username])

  // 实际可用的登录方式：用户级过滤优先，未过滤时用系统全集
  const availableMethods = useMemo(
    () => (userMethods ?? methods).filter((m) => LOGIN_METHOD_REGISTRY[m]),
    [userMethods, methods],
  )

  // 当前选中方式被过滤掉时，自动切到第一个可用方式
  useEffect(() => {
    if (availableMethods.length > 0 && !availableMethods.includes(loginTab)) {
      setLoginTab(availableMethods[0])
    }
  }, [availableMethods, loginTab])

  // 切换登录方式 Tab：保留 username / remember（方式专属字段随组件卸载自动清空）
  const handleTabChange = (key) => {
    if (key === loginTab) return
    setLoginTab(key)
    setServerError('')
    setErrors({ username: '', password: '', captcha: '', otp: '' })
  }

  // OTP 第二步验证提交（密码登录后的 MFA）
  const handleOtpSubmit = async (e) => {
    if (e) e.preventDefault()
    setServerError('')
    if (!otpCode.trim() || otpCode.trim().length !== 6) {
      setErrors((prev) => ({ ...prev, otp: '请输入 6 位动态验证码' }))
      triggerShake()
      return
    }
    setLoading(true)
    try {
      const res = await authApi.loginOtp(otpPendingToken, otpCode.trim())
      handleLoginSuccess(res)
    } catch (err) {
      const msg = err.message || '动态验证码错误'
      setServerError(msg)
      setErrors((prev) => ({ ...prev, otp: '动态验证码错误，请重试' }))
      triggerShake()
    } finally {
      setLoading(false)
    }
  }

  // SSO 提供商跳转：获取 authorize_url 后当前页跳转
  // （LDAP 或指向本站 /login 的地址同样是 location.href，不新开窗口）
  const handleSsoProvider = async (provider) => {
    if (ssoRedirecting) return
    setSsoRedirecting(provider.id)
    try {
      const res = await authApi.ssoAuthorize(provider.id, window.location.origin + '/login')
      if (res?.authorize_url) {
        window.location.href = res.authorize_url
      } else {
        toast.error('SSO 配置不完整，请联系管理员')
      }
    } catch (err) {
      toast.error(err.message || 'SSO 登录暂时不可用')
    } finally {
      setSsoRedirecting('')
    }
  }

  // 返回密码登录（从 MFA OTP 步骤返回；密码表单重新挂载会自动刷新验证码并聚焦）
  const handleBackToPassword = () => {
    setOtpStep(false)
    setOtpPendingToken('')
    setOtpCode('')
    setErrors((prev) => ({ ...prev, otp: '' }))
    setServerError('')
  }

  // 无任何可用登录方式：系统全集为空 / 全被用户过滤，且无 SSO 提供商
  const noMethods = methodsLoaded && providersLoaded
    && availableMethods.length === 0 && providers.length === 0

  // 当前年份（页脚版权）
  const year = useMemo(() => new Date().getFullYear(), [])

  // 公告条样式
  const announcementStyle = {
    info: 'border-primary/40 bg-primary/10 text-primary',
    warning: 'border-warning/40 bg-warning/10 text-warning',
    success: 'border-success/40 bg-success/10 text-success',
  }[announcement.type] || 'border-primary/40 bg-primary/10 text-primary'

  return (
    <div className="relative flex h-screen w-screen overflow-hidden bg-background animate-page-fade-in">
      {/* 全屏共享背景层：连续渐变 + 全屏网格 + 跨边界粒子 + 交界径向光晕 */}
      <SharedBackground />

      {/* 左侧品牌区（桌面端，lg 及以上显示，从左侧滑入） */}
      <div className="relative hidden lg:block lg:w-1/2 xl:w-3/5 animate-slide-in-left">
        <BrandPanel platformName={platformName} />
      </div>

      {/* 右侧登录区（从右侧滑入） */}
      <div className="relative flex w-full flex-col items-center justify-center px-4 py-8 sm:px-6 lg:w-1/2 xl:w-2/5 animate-slide-in-right">

        {/* 公告条 */}
        {announcement.visible && (
          <div className={`relative mb-4 flex w-full max-w-md items-start gap-2 rounded-lg border px-3.5 py-2.5 text-xs ${announcementStyle}`}>
            <Megaphone className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="flex-1">{announcement.text}</span>
            <button
              type="button"
              onClick={() => setAnnouncement((a) => ({ ...a, visible: false }))}
              className="opacity-70 transition hover:opacity-100"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* 移动端品牌头（lg 以下显示） */}
        <div className="relative mb-8 flex items-center gap-3 lg:hidden animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
          <img
            src="/favicon.svg"
            alt="Logo"
            className="h-9 w-9"
          />
          <div>
            <div className="text-base font-semibold text-foreground">{platformName}</div>
            <div className="text-xs text-muted-foreground">智能编排 · 自动化响应 · 安全运营</div>
          </div>
        </div>

        {/* 登录卡片（毛玻璃，左侧青色轮廓光呼应品牌色，融入背景） */}
        <div
          className={`relative w-full max-w-md rounded-2xl p-7 backdrop-blur-2xl transition-all sm:p-8 animate-fade-in-up ${
            shake ? 'animate-shake' : ''
          } ${success ? 'scale-[0.98] opacity-90' : ''}`}
          style={{
            animationDelay: '0.4s',
            // 半透明深色背景 + 极细白色内描边 + 左侧青色轮廓光 + 整体外发光
            background: 'rgba(8, 12, 18, 0.7)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderLeft: '1px solid rgba(0, 210, 210, 0.3)',
            boxShadow:
              '0 0 60px rgba(0,210,210,0.05), 0 10px 40px -10px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(255,255,255,0.04)',
          }}
        >
          {/* 顶部细高光 */}
          <div className="pointer-events-none absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-primary/40 to-transparent" />

          {/* 卡片头部 */}
          <div className="mb-6 flex items-center gap-3 lg:hidden animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
            <img
              src="/favicon.svg"
              alt="Logo"
              className="h-9 w-9"
            />
            <span className="text-base font-semibold text-foreground">{platformName}</span>
          </div>
          <div className="mb-6 hidden lg:block animate-fade-in-up" style={{ animationDelay: '0.3s' }}>
            <h2 className="text-xl font-semibold text-foreground">欢迎登录</h2>
            <p className="mt-1 text-sm text-muted-foreground">请使用账号登录以继续</p>
          </div>

          {/* 服务器错误提示 */}
          {serverError && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-3.5 py-2.5 text-xs text-destructive">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="flex-1">{serverError}</span>
              <button
                type="button"
                onClick={() => setServerError('')}
                className="text-destructive/70 hover:text-destructive"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          {/* 成功提示 */}
          {success && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-success/40 bg-success/10 px-3.5 py-2.5 text-xs text-success">
              <CheckCircle2 className="h-4 w-4" />
              <span>登录成功，正在进入系统...</span>
            </div>
          )}

          {/* 登录方式 Tab（注册表 + 后端 login-methods 驱动，多于一种方式时显示） */}
          {!otpStep && availableMethods.length > 1 && (
            <div className="mb-4 flex gap-1 rounded-lg bg-secondary/40 p-1">
              {availableMethods.map((key) => {
                const method = LOGIN_METHOD_REGISTRY[key]
                return (
                  <button
                    key={key}
                    type="button"
                    onClick={() => handleTabChange(key)}
                    className={`flex-1 rounded-md py-1.5 text-xs font-medium transition ${
                      loginTab === key
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    <method.icon className="mr-1 inline h-3.5 w-3.5" />
                    {method.label}
                  </button>
                )
              })}
            </div>
          )}

          {/* OTP 第二步验证 */}
          {otpStep ? (
            <form onSubmit={handleOtpSubmit} className="flex flex-col gap-4" noValidate>
              {/* OTP 提示 */}
              <div className="flex items-start gap-2 rounded-lg border border-primary/40 bg-primary/10 px-3.5 py-2.5 text-xs text-primary">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <div className="flex-1">
                  <div className="font-medium">请输入动态验证码</div>
                  <div className="mt-0.5 text-primary/70">请打开 Authenticator 应用，输入 6 位动态码完成验证</div>
                </div>
              </div>
              {/* OTP 输入框 */}
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  动态验证码
                </label>
                <input
                  ref={otpRef}
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={otpCode}
                  onChange={(e) => {
                    setOtpCode(e.target.value.replace(/\D/g, ''))
                    if (errors.otp) setErrors((prev) => ({ ...prev, otp: '' }))
                  }}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleOtpSubmit(e) }}
                  placeholder="000000"
                  autoComplete="one-time-code"
                  autoFocus
                  className={`w-full rounded-lg border bg-muted/60 py-3 text-center text-2xl font-bold tracking-[0.5em] text-foreground outline-none transition ${
                    errors.otp ? 'border-destructive/70' : 'border-border focus:border-primary/80 focus:ring-2 focus:ring-primary/30'
                  }`}
                />
                {errors.otp && (
                  <div className="mt-1.5 flex items-center gap-1 text-xs text-destructive">
                    <AlertCircle className="h-3 w-3" />
                    <span>{errors.otp}</span>
                  </div>
                )}
              </div>
              {/* 提交按钮 */}
              <button
                type="submit"
                disabled={loading || success}
                className={`group relative mt-2 flex h-11 w-full items-center justify-center gap-2 overflow-hidden rounded-lg text-sm font-medium transition-all ${
                  success
                    ? 'bg-success text-white'
                    : 'bg-primary text-primary-foreground hover:shadow-[0_4px_20px_-4px_rgba(34,211,238,0.4)] active:scale-[0.98]'
                } disabled:cursor-not-allowed disabled:opacity-70`}
              >
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    验证中...
                  </>
                ) : success ? (
                  <>
                    <CheckCircle2 className="h-4 w-4" />
                    登录成功
                  </>
                ) : (
                  <>
                    <ShieldCheck className="h-4 w-4" />
                    验证并登录
                  </>
                )}
              </button>
              {/* 返回密码登录 */}
              <button
                type="button"
                onClick={handleBackToPassword}
                className="text-xs text-muted-foreground transition hover:text-primary"
              >
                ← 返回重新登录
              </button>
            </form>
          ) : noMethods ? (
            /* 空状态：系统未开放任何登录方式（login-methods 为空/失败且无 SSO 提供商） */
            <div className="flex flex-col items-center gap-3 py-10">
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-muted/60">
                <Lock className="h-7 w-7 text-muted-foreground" />
              </div>
              <div className="text-sm text-muted-foreground">当前系统未开放登录，请联系管理员</div>
            </div>
          ) : availableMethods.length > 0 ? (
            /* 当前登录方式表单：key 切换触发淡入过渡，方式专属字段随组件卸载自动清空 */
            <div key={loginTab} className="animate-fade-in-up" style={{ animationDuration: '0.3s' }}>
              {(() => {
                const { Component } = LOGIN_METHOD_REGISTRY[loginTab] || {}
                if (!Component) return null
                return (
                  <Component
                    username={username}
                    onUsernameChange={setUsername}
                    remember={remember}
                    onRememberChange={setRemember}
                    persistRemember={persistRemember}
                    loading={loading}
                    setLoading={setLoading}
                    success={success}
                    errors={errors}
                    setErrors={setErrors}
                    validateField={validateField}
                    onServerError={setServerError}
                    onShake={triggerShake}
                    onRequiresOtp={handleRequiresOtp}
                    onLoginSuccess={handleLoginSuccess}
                    onForgotPassword={() => setForgotOpen(true)}
                  />
                )
              })()}
            </div>
          ) : null}

          {/* SSO 提供商区（providers 为空则整区不渲染，也不显示分隔标题） */}
          {!otpStep && providers.length > 0 && (
            <div className="mt-5">
              {/* 分隔标题：横线 + 灰字 + 横线（存在表单登录方式时才显示「或」） */}
              {availableMethods.length > 0 && (
                <div className="flex items-center gap-3">
                  <div className="h-px flex-1 bg-border/70" />
                  <span className="text-xs text-muted-foreground/70">或通过以下方式登录</span>
                  <div className="h-px flex-1 bg-border/70" />
                </div>
              )}
              {/* 提供商按钮：圆角卡片，hover 边框青色 + 微上移；点击跳转授权地址 */}
              <div className={`flex flex-wrap justify-center gap-3 ${availableMethods.length > 0 ? 'mt-4' : ''}`}>
                {providers.map((provider) => {
                  const ProviderIcon = getSsoProviderIcon(provider.id)
                  const redirecting = ssoRedirecting === provider.id
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => handleSsoProvider(provider)}
                      disabled={!!ssoRedirecting}
                      title={`使用 ${provider.name} 登录`}
                      className="flex items-center gap-2 rounded-xl border border-border bg-muted/30 px-4 py-3 text-sm text-foreground transition-all hover:-translate-y-0.5 hover:border-primary hover:shadow-[0_4px_16px_-6px_rgba(34,211,238,0.35)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {redirecting ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      ) : (
                        <ProviderIcon className="h-4 w-4 text-primary" />
                      )}
                      <span>{provider.name}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 安全提示（缩小字号、降低对比度） */}
          <div className="mt-4 flex items-center justify-center gap-1.5 text-[10px] text-muted-foreground/40">
            <ShieldCheck className="h-3 w-3 shrink-0" />
            <span>本系统受安全策略保护，登录行为均被审计记录</span>
          </div>
        </div>

        {/* 页脚 */}
        <div className="relative mt-6 w-full max-w-md px-2">
          <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-xs text-muted-foreground/70">
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              className="flex items-center gap-1 transition hover:text-foreground"
            >
              <LifeBuoy className="h-3 w-3" />
              使用帮助
            </button>
            <a
              href="mailto:soar-admin@company.com"
              className="flex items-center gap-1 transition hover:text-foreground"
            >
              <BookOpen className="h-3 w-3" />
              联系管理员
            </a>
            <a
              href="https://docs.example.com/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 transition hover:text-foreground"
            >
              <ShieldQuestion className="h-3 w-3" />
              隐私协议
              <ExternalLink className="h-2.5 w-2.5 opacity-60" />
            </a>
            <a
              href="https://docs.example.com/terms"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 transition hover:text-foreground"
            >
              <FileText className="h-3 w-3" />
              服务条款
              <ExternalLink className="h-2.5 w-2.5 opacity-60" />
            </a>
          </div>
          <div className="mt-3 text-center text-[11px] text-muted-foreground/50">
            © {year} {platformName}
            {version && <span className="ml-1">· v{version} · 安全增强版</span>}
          </div>
        </div>
      </div>

      {/* 弹窗 */}
      <ForgotPasswordModal open={forgotOpen} onClose={() => setForgotOpen(false)} />
      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />

      {/* 动画样式（局部注入，避免污染全局） */}
      <style>{`
        @keyframes pulse-slow {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.05); }
        }
        .animate-pulse-slow {
          animation: pulse-slow 6s ease-in-out infinite;
        }
        @keyframes float-particle {
          0% { transform: translate(0, 0); opacity: 0; }
          20% { opacity: 1; }
          80% { opacity: 1; }
          100% { transform: translate(20px, -60px); opacity: 0; }
        }
        .animate-float-particle {
          animation: float-particle 10s linear infinite;
        }
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20% { transform: translateX(-8px); }
          40% { transform: translateX(8px); }
          60% { transform: translateX(-6px); }
          80% { transform: translateX(4px); }
        }
        .animate-shake {
          animation: shake 0.45s ease-in-out;
        }
        /* 页面整体淡入 */
        @keyframes page-fade-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        .animate-page-fade-in {
          animation: page-fade-in 0.6s ease-out both;
        }
        /* 左侧文案从左侧滑入 + 淡入 */
        @keyframes slide-in-left {
          from { opacity: 0; transform: translateX(-40px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .animate-slide-in-left {
          animation: slide-in-left 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        /* 登录卡片从右侧滑入 + 淡入 */
        @keyframes slide-in-right {
          from { opacity: 0; transform: translateX(40px); }
          to { opacity: 1; transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
        }
        /* 子元素逐项淡入上浮 */
        @keyframes fade-in-up {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fade-in-up {
          animation: fade-in-up 0.5s ease-out both;
        }
      `}</style>
    </div>
  )
}

export default Login
