import { ExternalLink, Database } from 'lucide-react'

export default function QdrantPage() {
  // Qdrant Web UI URL (환경변수 또는 기본값)
  const qdrantUrl = import.meta.env.VITE_QDRANT_URL || 'http://localhost:6333'
  const qdrantDashboardUrl = `${qdrantUrl}/dashboard`

  const handleOpenQdrant = () => {
    window.open(qdrantDashboardUrl, '_blank')
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="text-center">
          <Database className="h-16 w-16 mx-auto mb-4" style={{ color: '#3b82f6' }} />
          <h2 className="text-2xl font-bold mb-2" style={{ color: '#1f2937' }}>Qdrant DB Page</h2>
          <p className="mb-6" style={{ color: '#6b7280' }}>
            Qdrant 벡터 데이터베이스의 Web UI로 이동합니다.
          </p>
          <button
            onClick={handleOpenQdrant}
            className="flex items-center space-x-2 px-6 py-3 text-white rounded-lg transition-colors mx-auto font-medium"
            style={{ background: '#3b82f6' }}
            onMouseEnter={(e) => e.currentTarget.style.background = '#2563eb'}
            onMouseLeave={(e) => e.currentTarget.style.background = '#3b82f6'}
          >
            <ExternalLink className="h-5 w-5" />
            <span>Qdrant Web UI 열기</span>
          </button>
        </div>
      </div>
    </div>
  )
}
