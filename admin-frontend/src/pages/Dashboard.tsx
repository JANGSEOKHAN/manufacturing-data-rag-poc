import { useQuery } from '@tanstack/react-query'
import { 
  FileText, AlertCircle,
  CheckCircle2, Loader2
} from 'lucide-react'
import { adminApi } from '../api/client'
import QueryInterface from '../components/QueryInterface'

interface Status {
  total_documents: number
  files: Record<string, number>
}

export default function Dashboard() {
  // 시스템 상태 조회
  const { data: status, isLoading: statusLoading } = useQuery<Status>({
    queryKey: ['status'],
    queryFn: async () => {
      const response = await adminApi.getStatus()
      return response.data
    },
    refetchInterval: false, // 자동 갱신 비활성화 (성능 최적화)
    staleTime: 30000, // 30초간 캐시 유지
  })


  return (
    <div className="space-y-6">
      {/* 상태 카드 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg p-6 border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: '#6b7280' }}>등록된 청크</p>
              <p className="text-2xl font-bold mt-1" style={{ color: '#3b82f6' }}>
                {statusLoading ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : (
                  status?.total_documents || 0
                )}
              </p>
            </div>
            <FileText className="h-8 w-8" style={{ color: '#3b82f6' }} />
          </div>
        </div>

        <div className="bg-white rounded-lg p-6 border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: '#6b7280' }}>파일 수</p>
              <p className="text-2xl font-bold mt-1" style={{ color: '#3b82f6' }}>
                {statusLoading ? (
                  <Loader2 className="h-6 w-6 animate-spin" />
                ) : (
                  Object.keys(status?.files || {}).length
                )}
              </p>
            </div>
            <CheckCircle2 className="h-8 w-8" style={{ color: '#3b82f6' }} />
          </div>
        </div>

        <div className="bg-white rounded-lg p-6 border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: '#6b7280' }}>시스템 상태</p>
              <p className="text-lg font-bold mt-1 flex items-center space-x-1" style={{ color: '#1f2937' }}>
                {statusLoading ? (
                  <>
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span>확인 중...</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="h-5 w-5" style={{ color: '#3b82f6' }} />
                    <span>정상</span>
                  </>
                )}
              </p>
            </div>
            <AlertCircle className="h-8 w-8" style={{ color: '#3b82f6' }} />
          </div>
        </div>
      </div>

      {/* 질의응답 인터페이스 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold mb-4" style={{ color: '#1f2937' }}>질의응답하기</h3>
        <QueryInterface />
      </div>
    </div>
  )
}

