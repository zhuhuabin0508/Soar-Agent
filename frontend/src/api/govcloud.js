import { request } from './client'

function authHeader() {
  const token = localStorage.getItem('soar_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const govCloudApi = {
  meta: () => request('/govcloud/meta'),
  summary: () => request('/govcloud/summary'),
  list: (params = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
    })
    return request(`/govcloud/assets?${qs.toString()}`)
  },
  get: (resourceType, id) => request(`/govcloud/assets/${encodeURIComponent(resourceType)}/${id}`),
  consistency: (resource_type) => request(`/govcloud/consistency?resource_type=${encodeURIComponent(resource_type)}`),
  batches: (resource_type) => {
    const qs = resource_type ? `?resource_type=${encodeURIComponent(resource_type)}` : ''
    return request(`/govcloud/batches${qs}`)
  },
  importExcel: (file, resource_type, onProgress, mode = 'full') => new Promise((resolve, reject) => {
    const fd = new FormData()
    fd.append('file', file)
    const qs = new URLSearchParams()
    if (resource_type) qs.set('resource_type', resource_type)
    qs.set('mode', mode === 'incremental' ? 'incremental' : 'full')
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/v1/govcloud/import?${qs.toString()}`)
    const headers = authHeader()
    if (headers.Authorization) xhr.setRequestHeader('Authorization', headers.Authorization)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress({ phase: 'uploading', percent: Math.round((e.loaded / e.total) * 100) })
      }
    }
    xhr.upload.onload = () => {
      if (onProgress) onProgress({ phase: 'processing' })
    }
    xhr.onload = () => {
      let data = null
      try { data = JSON.parse(xhr.responseText) } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        if (onProgress) onProgress({ phase: 'done' })
        resolve(data)
      } else {
        if (onProgress) onProgress({ phase: 'error' })
        if (xhr.status === 401 && !window.location.pathname.startsWith('/login')) {
          localStorage.removeItem('soar_token')
          localStorage.removeItem('soar_user')
          setTimeout(() => { window.location.href = '/login' }, 100)
        }
        const detail = (data && (data.detail || data.message)) || `HTTP ${xhr.status}`
        reject(new Error(`导入失败：${detail}`))
      }
    }
    xhr.onerror = () => {
      if (onProgress) onProgress({ phase: 'error' })
      reject(new Error('网络错误，导入失败'))
    }
    xhr.send(fd)
  }),
}
