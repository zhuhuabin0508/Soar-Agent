import { useState } from 'react'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import {
  Section,
  TextInput,
} from '../components/property/FormControls'

// 个人中心：自助修改个人资料 + 修改密码
function Profile() {
  const user = useAuthStore((s) => s.user)
  const setAuth = useAuthStore((s) => s.setAuth)

  // 资料编辑
  const [profile, setProfile] = useState({
    display_name: user?.display_name || '',
    email: user?.email || '',
  })
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileMsg, setProfileMsg] = useState({ type: '', text: '' })

  // 修改密码
  const [pwd, setPwd] = useState({
    old_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [savingPwd, setSavingPwd] = useState(false)
  const [pwdMsg, setPwdMsg] = useState({ type: '', text: '' })

  const handleSaveProfile = async () => {
    setSavingProfile(true)
    setProfileMsg({ type: '', text: '' })
    try {
      const updated = await authApi.updateProfile({
        display_name: profile.display_name,
        email: profile.email,
      })
      // 同步更新本地 store 中的用户信息
      setAuth(useAuthStore.getState().token, updated)
      setProfileMsg({ type: 'ok', text: '个人资料已更新' })
    } catch (err) {
      setProfileMsg({
        type: 'err',
        text: `保存失败：${err.message || err}`,
      })
    } finally {
      setSavingProfile(false)
    }
  }

  const handleChangePwd = async () => {
    if (!pwd.old_password || !pwd.new_password) {
      setPwdMsg({ type: 'err', text: '请填写原密码与新密码' })
      return
    }
    if (pwd.new_password.length < 6) {
      setPwdMsg({ type: 'err', text: '新密码至少 6 位' })
      return
    }
    if (pwd.new_password !== pwd.confirm_password) {
      setPwdMsg({ type: 'err', text: '两次输入的新密码不一致' })
      return
    }
    if (pwd.old_password === pwd.new_password) {
      setPwdMsg({ type: 'err', text: '新密码不能与原密码相同' })
      return
    }
    setSavingPwd(true)
    setPwdMsg({ type: '', text: '' })
    try {
      await authApi.changePassword(pwd.old_password, pwd.new_password)
      setPwd({ old_password: '', new_password: '', confirm_password: '' })
      setPwdMsg({ type: 'ok', text: '密码修改成功' })
    } catch (err) {
      setPwdMsg({
        type: 'err',
        text: `修改失败：${err.message || err}`,
      })
    } finally {
      setSavingPwd(false)
    }
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-950 text-gray-100">
      <header className="flex items-center justify-between border-b border-gray-800 bg-gray-900/60 px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold">个人中心</h1>
          <span className="text-xs text-gray-500">
            {user?.username ? `@${user.username}` : ''}
          </span>
        </div>
      </header>

      <div className="flex-1 min-w-0 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {/* 当前账号信息卡片 */}
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-4">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-300">
              当前账号
            </div>
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-2xl font-bold text-white">
                {(user?.username || '?')[0].toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-base font-semibold text-gray-100">
                  {user?.display_name || user?.username}
                </div>
                <div className="text-sm text-gray-400">@{user?.username}</div>
                <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
                  <span className="rounded bg-brand-500/20 px-2 py-0.5 font-medium text-brand-300">
                    {user?.role || '-'}
                  </span>
                  {user?.is_active ? (
                    <span className="rounded bg-success-500/20 px-2 py-0.5 font-medium text-success-300">
                      启用
                    </span>
                  ) : (
                    <span className="rounded bg-gray-500/20 px-2 py-0.5 font-medium text-gray-400">
                      禁用
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* 修改个人资料 */}
          <Section title="个人资料">
            <TextInput
              label="显示名"
              value={profile.display_name}
              onChange={(v) => setProfile((p) => ({ ...p, display_name: v }))}
              placeholder="如：张三"
            />
            <TextInput
              label="邮箱"
              value={profile.email}
              onChange={(v) => setProfile((p) => ({ ...p, email: v }))}
              placeholder="user@example.com"
            />
            {profileMsg.text && (
              <div
                className={`rounded-md px-3 py-2 text-xs ${
                  profileMsg.type === 'ok'
                    ? 'border border-success-500/40 bg-success-500/10 text-success-300'
                    : 'border border-danger-500/40 bg-danger-500/10 text-red-300'
                }`}
              >
                {profileMsg.text}
              </div>
            )}
            <button
              type="button"
              onClick={handleSaveProfile}
              disabled={savingProfile}
              className="btn-primary"
            >
              {savingProfile ? '保存中…' : '保存资料'}
            </button>
          </Section>

          {/* 修改密码 */}
          <Section title="修改密码" hint="修改密码后需重新登录其他设备">
            <TextInput
              label="原密码"
              value={pwd.old_password}
              onChange={(v) => setPwd((p) => ({ ...p, old_password: v }))}
              placeholder="当前密码"
            />
            <TextInput
              label="新密码"
              value={pwd.new_password}
              onChange={(v) => setPwd((p) => ({ ...p, new_password: v }))}
              placeholder="至少 6 位"
            />
            <TextInput
              label="确认新密码"
              value={pwd.confirm_password}
              onChange={(v) => setPwd((p) => ({ ...p, confirm_password: v }))}
              placeholder="再次输入新密码"
            />
            {pwdMsg.text && (
              <div
                className={`rounded-md px-3 py-2 text-xs ${
                  pwdMsg.type === 'ok'
                    ? 'border border-success-500/40 bg-success-500/10 text-success-300'
                    : 'border border-danger-500/40 bg-danger-500/10 text-red-300'
                }`}
              >
                {pwdMsg.text}
              </div>
            )}
            <button
              type="button"
              onClick={handleChangePwd}
              disabled={savingPwd}
              className="btn-primary"
            >
              {savingPwd ? '修改中…' : '修改密码'}
            </button>
          </Section>
        </div>
      </div>
    </div>
  )
}

export default Profile
