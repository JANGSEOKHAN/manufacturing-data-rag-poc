import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Send, Loader2, FileText, Image as ImageIcon, ExternalLink } from 'lucide-react'
import { adminApi } from '../api/client'

export default function QueryInterface() {
  const [question, setQuestion] = useState('')
  const [lastAnswer, setLastAnswer] = useState<{
    answer: string
    sources: Array<{ filename: string; html_path?: string }>
    images: Array<{ filename: string; data_uri?: string; url?: string }>
  } | null>(null)

  const queryMutation = useMutation({
    mutationFn: async (q: string) => {
      try {
        const response = await adminApi.ragQuery(q)
        // 디버깅 로그 제거 (성능 최적화)
        return response
      } catch (error: any) {
        console.error('[ERROR] RAG 질의 실패:', error)
        throw error
      }
    },
    onSuccess: (response) => {
      setLastAnswer(response.data)
    },
    onError: (error: any) => {
      console.error('[ERROR] 질의 처리 실패:', error)
      alert(`질의 처리 실패: ${error.response?.data?.detail || error.message || '알 수 없는 오류'}`)
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim()) return
    queryMutation.mutate(question)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 키만 누르면 제출, Shift+Enter는 줄바꿈
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (question.trim()) {
        queryMutation.mutate(question)
      }
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-2" style={{ color: '#1f2937' }}>
            질문 입력
          </label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="예: NPM-D3 40008 에러 원인과 조치 알려줘 (Enter: 질문하기, Shift+Enter: 줄바꿈)"
            className="w-full px-4 py-3 border rounded-lg resize-none transition-colors"
            style={{ 
              borderColor: '#e5e7eb',
              background: '#f3f4f6',
              color: '#1f2937'
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = '#3b82f6'
              e.currentTarget.style.boxShadow = '0 0 0 3px rgba(59, 130, 246, 0.1)'
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = '#e5e7eb'
              e.currentTarget.style.boxShadow = 'none'
            }}
            rows={4}
          />
        </div>
        <button
          type="submit"
          disabled={!question.trim() || queryMutation.isPending}
          className="w-full flex items-center justify-center space-x-2 px-4 py-3 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          style={{ background: '#3b82f6' }}
          onMouseEnter={(e) => !e.currentTarget.disabled && (e.currentTarget.style.background = '#2563eb')}
          onMouseLeave={(e) => !e.currentTarget.disabled && (e.currentTarget.style.background = '#3b82f6')}
        >
          {queryMutation.isPending ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>처리 중...</span>
            </>
          ) : (
            <>
              <Send className="h-5 w-5" />
              <span>질문하기</span>
            </>
          )}
        </button>
      </form>

      {queryMutation.isError && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm text-red-800">
            질문 처리 중 오류가 발생했습니다: {queryMutation.error?.message}
          </p>
        </div>
      )}

      {lastAnswer && (
        <div className="space-y-4 mt-6">
          <div className="p-4 rounded-lg border" style={{ background: '#f3f4f6', borderColor: '#e5e7eb' }}>
            <h4 className="font-semibold mb-2" style={{ color: '#1f2937' }}>답변</h4>
            <p className="whitespace-pre-wrap" style={{ color: '#1f2937' }}>{lastAnswer.answer}</p>
          </div>

          {lastAnswer.images && lastAnswer.images.length > 0 && (
            <div>
              <h4 className="font-semibold mb-2 flex items-center space-x-2" style={{ color: '#1f2937' }}>
                <ImageIcon className="h-5 w-5" style={{ color: '#3b82f6' }} />
                <span>관련 이미지 ({lastAnswer.images.length}개)</span>
              </h4>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {lastAnswer.images.map((img, idx) => (
                  <div key={idx} className="border border-gray-200 rounded-lg overflow-hidden">
                    {img.data_uri ? (
                      <img
                        src={img.data_uri}
                        alt={img.filename}
                        className="w-full h-48 object-contain bg-gray-50"
                      />
                    ) : img.url ? (
                      <img
                        src={img.url}
                        alt={img.filename}
                        className="w-full h-48 object-contain bg-gray-50"
                      />
                    ) : (
                      <div className="w-full h-48 bg-gray-100 flex items-center justify-center">
                        <ImageIcon className="h-12 w-12 text-gray-400" />
                      </div>
                    )}
                    <p className="p-2 text-xs text-gray-600 truncate">{img.filename}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {lastAnswer.sources && lastAnswer.sources.length > 0 && (
            <div>
              <h4 className="font-semibold mb-2 flex items-center space-x-2" style={{ color: '#1f2937' }}>
                <FileText className="h-5 w-5" style={{ color: '#3b82f6' }} />
                <span>참조 문서 ({lastAnswer.sources.length}개)</span>
              </h4>
              <div className="space-y-2">
                {lastAnswer.sources.map((source, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between p-3 rounded-lg border"
                    style={{ background: '#f9fafb', borderColor: '#e5e7eb' }}
                  >
                    <div className="flex items-center space-x-2">
                      <FileText className="h-4 w-4" style={{ color: '#6b7280' }} />
                      <span className="text-sm" style={{ color: '#1f2937' }}>{source.filename}</span>
                    </div>
                    {source.html_path && (
                      <a
                        href={`/static/${source.html_path}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: '#3b82f6' }}
                        onMouseEnter={(e) => e.currentTarget.style.color = '#2563eb'}
                        onMouseLeave={(e) => e.currentTarget.style.color = '#3b82f6'}
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

