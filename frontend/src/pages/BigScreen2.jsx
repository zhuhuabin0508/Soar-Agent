import { useCallback } from 'react'
import EmbedScreen from '../components/EmbedScreen'
import { getCimEmbedUrl } from '../api/bigscreen'

export default function BigScreen2() {
  const fetchUrl = useCallback(() => getCimEmbedUrl(), [])
  return (
    <EmbedScreen
      title="盾立方指挥大屏"
      subtitle="深治慧 CIM 城市大屏"
      perm="bigscreen2"
      fetchUrl={fetchUrl}
      loadLabel="重新登录"
    />
  )
}
