import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { 
  FileText, Upload, Trash2, Loader2, XCircle, Image as ImageIcon
} from 'lucide-react'
import { adminApi } from '../api/client'
import FileUploadModal from '../components/FileUploadModal'

interface Document {
  filename: string
  total_chunks: number
  total_images: number
  text_chunks_preview: Array<{
    content: string
    chunk_index: number
    full_length: number
  }>
  image_summaries_preview: Array<{
    image_name: string
    summary: string
    full_length: number
  }>
}

export default function DataManagement() {
  const queryClient = useQueryClient()
  const [uploadModalOpen, setUploadModalOpen] = useState(false)

  // 문서 목록 조회
  const { data: documents, isLoading: docsLoading, error: docsError } = useQuery<Document[]>({
    queryKey: ['documents'],
    queryFn: async () => {
      try {
        const response = await adminApi.getDocuments()
        return response.data || []
      } catch (error: any) {
        console.error('[ERROR] 문서 목록 가져오기 실패:', error)
        throw error
      }
    },
    refetchInterval: false,
    staleTime: 0, // 캐시 즉시 만료 (캐시 쌓임 방지)
    gcTime: 0, // 가비지 컬렉션 즉시 실행
    refetchOnMount: false, // 마운트 시 refetch 비활성화
  })

  // 파일 삭제
  const deleteMutation = useMutation({
    mutationFn: (filename: string) => adminApi.deleteFile(filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex justify-between items-center">
          <div>
            <h2 className="text-2xl font-bold" style={{ color: '#1f2937' }}>데이터 관리</h2>
            <p className="mt-1" style={{ color: '#6b7280' }}>문서 업로드 및 관리</p>
          </div>
          <button
            onClick={() => setUploadModalOpen(true)}
            className="flex items-center space-x-2 px-5 py-3 text-white rounded-lg transition-colors font-medium"
            style={{ background: '#3b82f6' }}
            onMouseEnter={(e) => e.currentTarget.style.background = '#2563eb'}
            onMouseLeave={(e) => e.currentTarget.style.background = '#3b82f6'}
          >
            <Upload className="h-5 w-5" />
            <span>파일 업로드</span>
          </button>
        </div>
      </div>

      {/* 문서 목록 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-lg font-semibold" style={{ color: '#1f2937' }}>등록된 문서 목록</h3>
        </div>

        {docsLoading ? (
          <div className="p-12 text-center">
            <Loader2 className="h-8 w-8 animate-spin mx-auto" style={{ color: '#3b82f6' }} />
            <p className="mt-4" style={{ color: '#6b7280' }}>문서 목록을 불러오는 중...</p>
          </div>
        ) : docsError ? (
          <div className="p-12 text-center">
            <XCircle className="h-8 w-8 mx-auto text-red-500" />
            <p className="mt-4 text-red-600">문서 목록을 불러오는데 실패했습니다.</p>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ['documents'] })}
              className="mt-4 px-4 py-2 text-white rounded-lg font-medium"
              style={{ background: '#3b82f6' }}
              onMouseEnter={(e) => e.currentTarget.style.background = '#2563eb'}
              onMouseLeave={(e) => e.currentTarget.style.background = '#3b82f6'}
            >
              다시 시도
            </button>
          </div>
        ) : !documents || documents.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="h-12 w-12 mx-auto" style={{ color: '#9ca3af' }} />
            <p className="mt-4" style={{ color: '#6b7280' }}>등록된 문서가 없습니다.</p>
            <button
              onClick={() => setUploadModalOpen(true)}
              className="mt-4 px-4 py-2 text-white rounded-lg font-medium"
              style={{ background: '#3b82f6' }}
              onMouseEnter={(e) => e.currentTarget.style.background = '#2563eb'}
              onMouseLeave={(e) => e.currentTarget.style.background = '#3b82f6'}
            >
              파일 업로드하기
            </button>
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {documents.map((doc) => (
              <div key={doc.filename} className="p-6 hover:bg-gray-50 transition-colors">
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3 mb-3">
                      <FileText className="h-5 w-5" style={{ color: '#3b82f6' }} />
                      <Link
                        to={`/documents/${encodeURIComponent(doc.filename)}`}
                        className="text-lg font-semibold transition-colors"
                        style={{ color: '#1f2937' }}
                        onMouseEnter={(e) => e.currentTarget.style.color = '#3b82f6'}
                        onMouseLeave={(e) => e.currentTarget.style.color = '#1f2937'}
                      >
                        {doc.filename}
                      </Link>
                    </div>

                    <div className="flex flex-wrap gap-3 mb-4">
                      <span className="inline-flex items-center space-x-1 px-3 py-1 rounded-full text-sm" style={{ background: '#eff6ff', color: '#3b82f6' }}>
                        <FileText className="h-3 w-3" />
                        <span>텍스트 청크: {doc.total_chunks}개</span>
                      </span>
                      {doc.total_images > 0 && (
                        <span className="inline-flex items-center space-x-1 px-3 py-1 rounded-full text-sm" style={{ background: '#fff7ed', color: '#ea580c' }}>
                          <ImageIcon className="h-3 w-3" />
                          <span>이미지 요약: {doc.total_images}개</span>
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex flex-col space-y-2 ml-4">
                    <Link
                      to={`/documents/${encodeURIComponent(doc.filename)}`}
                      className="px-4 py-2 text-white rounded-lg transition-colors text-sm text-center font-medium"
                      style={{ background: '#3b82f6' }}
                      onMouseEnter={(e) => e.currentTarget.style.background = '#2563eb'}
                      onMouseLeave={(e) => e.currentTarget.style.background = '#3b82f6'}
                    >
                      상세보기
                    </Link>
                    <button
                      onClick={() => {
                        if (window.confirm(`"${doc.filename}" 파일을 삭제하시겠습니까?\n\n예: 삭제 진행\n아니오: 취소`)) {
                          deleteMutation.mutate(doc.filename)
                        }
                      }}
                      disabled={deleteMutation.isPending}
                      className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm disabled:opacity-50 font-medium"
                    >
                      {deleteMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin mx-auto" />
                      ) : (
                        '삭제'
                      )}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 파일 업로드 모달 */}
      {uploadModalOpen && (
        <FileUploadModal
          onClose={() => setUploadModalOpen(false)}
          onSuccess={() => {
            setUploadModalOpen(false)
            queryClient.invalidateQueries({ queryKey: ['documents'] })
            queryClient.invalidateQueries({ queryKey: ['status'] })
          }}
        />
      )}
    </div>
  )
}

