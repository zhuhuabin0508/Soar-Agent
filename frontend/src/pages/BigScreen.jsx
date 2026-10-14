import { useCallback } from 'react'
import EmbedScreen from '../components/EmbedScreen'
import { getYunfangEmbedUrl } from '../api/bigscreen'

export default function BigScreen() {
  const fetchUrl = useCallback(() => getYunfangEmbedUrl(), [])
  return (
    <EmbedScreen
      title="盾立方W"
      subtitle="云防御态势感知指挥平台"
      perm="bigscreen"
      fetchUrl={fetchUrl}
      loadLabel="重新登录"
    />
  )
}
