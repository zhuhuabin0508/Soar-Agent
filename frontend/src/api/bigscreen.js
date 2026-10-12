import request from './request'

export function getYunfangEmbedUrl() {
  return request('/bigscreen/embed-url')
}

export function getCimEmbedUrl() {
  return request('/bigscreen2/embed-url')
}

export default { getYunfangEmbedUrl, getCimEmbedUrl }
