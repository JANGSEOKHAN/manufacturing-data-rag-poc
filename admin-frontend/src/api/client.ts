import axios from 'axios'

// 외부 접속 시 Vite proxy를 통해 접속 (8902 포트)
const getApiBaseUrl = () => {
  // 환경 변수가 있으면 사용
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL
  }
  
  // 개발 환경에서는 localhost의 백엔드 포트 직접 사용
  const hostname = window.location.hostname
  if (hostname === 'localhost') {
    return 'http://localhost:8601'
  }
  
  // 외부 접속 시 Vite proxy 사용 (상대 경로로 요청하면 Vite가 8601로 프록시)
  // 빈 문자열을 사용하면 현재 origin(8902)을 사용하고, Vite proxy가 백엔드로 전달
  return ''
}

export const apiClient = axios.create({
  baseURL: getApiBaseUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
})

// API 엔드포인트
export const adminApi = {
  // 문서 목록
  getDocuments: () => apiClient.get('/api/admin/documents'),
  
  // 문서 상세
  getDocumentDetail: (filename: string) => 
    apiClient.get(`/api/admin/documents/${encodeURIComponent(filename)}`),
  
  // 시스템 상태
  getStatus: () => apiClient.get('/status'),
  
  // 파일 업로드
  uploadFile: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiClient.post('/upload_file', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  
  // 파일 삭제
  deleteFile: (filename: string) => 
    apiClient.delete(`/delete_file/${encodeURIComponent(filename)}`),
  
  // 모든 파일 삭제
  deleteAllFiles: () => apiClient.delete('/delete_all_files'),
  
  // RAG 질의
  ragQuery: (question: string) => 
    apiClient.post('/rag_query', { question }),
  
  // HTML 미리보기
  getHtmlPreview: (filename: string) => 
    apiClient.get(`/view_html/${encodeURIComponent(filename)}`, {
      responseType: 'text',
    }),
  
  // 벡터 스토어 재구성
  rebuildVectorstore: () => apiClient.post('/rebuild_vectorstore'),
}
