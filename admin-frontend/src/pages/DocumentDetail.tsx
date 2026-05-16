import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, FileText, Loader2, XCircle, File, ExternalLink, Image as ImageIcon } from 'lucide-react'
import { adminApi } from '../api/client'
import React, { useState } from 'react'

// 여러 경로를 시도하는 이미지 컴포넌트
function ImageWithFallback({ paths, alt, originalPath }: { paths: string[], alt: string, originalPath: string }) {
  const [currentPathIndex, setCurrentPathIndex] = useState(0)
  const [hasError, setHasError] = useState(false)

  if (hasError && currentPathIndex >= paths.length) {
    return (
      <div className="text-sm text-gray-500 p-2 bg-gray-100 rounded">
        이미지를 불러올 수 없습니다: {originalPath}
      </div>
    )
  }

  return (
    <img
      src={paths[currentPathIndex]}
      alt={alt}
      className="max-w-full h-auto rounded-lg border border-gray-200 shadow-sm"
      onError={() => {
        if (currentPathIndex < paths.length - 1) {
          // 다음 경로 시도
          setCurrentPathIndex(currentPathIndex + 1)
        } else {
          // 모든 경로 실패
          setHasError(true)
        }
      }}
    />
  )
}

interface ChunkDetail {
  chunk_index: number
  content: string
  length: number
  metadata: Record<string, any>
}

interface ImageSummary {
  image_name: string
  summary: string
  length: number
  metadata: Record<string, any>
}

interface FileDetail {
  filename: string
  total_chunks: number
  total_images: number
  text_chunks: ChunkDetail[]
  image_summaries: ImageSummary[]
  md_path?: string
  html_path?: string
}

// 이미지 마크다운을 실제 이미지로 변환하는 함수
function renderChunkContent(content: string, filename: string) {
  // 파일명에서 확장자 제거
  const fileStem = filename.replace(/\.[^/.]+$/, '')
  
  // 이미지 마크다운 패턴: ![](images/xxx.jpg) 또는 ![](vlm/images/xxx.jpg) 등
  const imagePattern = /!\[([^\]]*)\]\(([^)]+)\)/g
  
  const parts: (string | React.ReactElement)[] = []
  let lastIndex = 0
  let match
  
  while ((match = imagePattern.exec(content)) !== null) {
    // 이미지 이전 텍스트 추가
    if (match.index > lastIndex) {
      const text = content.substring(lastIndex, match.index)
      if (text.trim()) {
        parts.push(<span key={`text-${lastIndex}`}>{text}</span>)
      }
    }
    
    const imagePath = match[2] // images/xxx.jpg 또는 vlm/images/xxx.jpg
    const altText = match[1] || '이미지'
    
    // 이미지 파일명 추출
    let imageFileName = ''
    if (imagePath.startsWith('images/')) {
      imageFileName = imagePath.replace('images/', '')
    } else if (imagePath.startsWith('vlm/images/')) {
      imageFileName = imagePath.replace('vlm/images/', '')
    } else if (imagePath.startsWith('ocr/images/')) {
      imageFileName = imagePath.replace('ocr/images/', '')
    } else if (imagePath.includes('/images/')) {
      const parts = imagePath.split('/images/')
      imageFileName = parts[parts.length - 1] // 마지막 부분이 파일명
    } else {
      imageFileName = imagePath
    }
    
    const encodedStem = encodeURIComponent(fileStem)
    const encodedFileName = encodeURIComponent(imageFileName)
    
    // 백엔드와 동일한 순서로 경로 시도: vlm, ocr, 루트 images
    const possiblePaths = [
      `/static/${encodedStem}/vlm/images/${encodedFileName}`,
      `/static/${encodedStem}/ocr/images/${encodedFileName}`,
      `/static/${encodedStem}/images/${encodedFileName}`,
    ]
    
    // 이미지 컴포넌트 추가 (여러 경로 시도)
    parts.push(
      <div key={`img-${match.index}`} className="my-4">
        <ImageWithFallback
          paths={possiblePaths}
          alt={altText}
          originalPath={imagePath}
        />
      </div>
    )
    
    lastIndex = match.index + match[0].length
  }
  
  // 마지막 텍스트 추가
  if (lastIndex < content.length) {
    const text = content.substring(lastIndex)
    if (text.trim()) {
      parts.push(<span key={`text-${lastIndex}`}>{text}</span>)
    }
  }
  
  return parts.length > 0 ? parts : [<span key="content">{content}</span>]
}

export default function DocumentDetail() {
  const { filename } = useParams<{ filename: string }>()
  const [activeTab, setActiveTab] = useState<'text' | 'image'>('text')

  const { data: document, isLoading, error } = useQuery<FileDetail>({
    queryKey: ['document', filename],
    queryFn: async () => {
      if (!filename) throw new Error('Filename is required')
      const response = await adminApi.getDocumentDetail(filename)
      return response.data
    },
    enabled: !!filename,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-primary-600" />
          <p className="mt-4 text-gray-600">문서 정보를 불러오는 중...</p>
        </div>
      </div>
    )
  }

  if (error || !document) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <XCircle className="h-8 w-8 mx-auto text-red-500" />
          <p className="mt-4 text-red-600">문서를 불러오는데 실패했습니다.</p>
          <Link
            to="/"
            className="mt-4 inline-block px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
          >
            목록으로 돌아가기
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* 헤더 */}
      <div className="flex items-center space-x-4">
        <Link
          to="/"
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <ArrowLeft className="h-5 w-5 text-gray-600" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold" style={{ color: '#1f2937' }}>{document.filename}</h1>
          <p className="mt-1" style={{ color: '#6b7280' }}>문서 상세 정보</p>
        </div>
      </div>

      {/* 통계 카드 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg p-4 border border-gray-200 shadow-sm">
          <div className="flex items-center space-x-3">
            <FileText className="h-8 w-8" style={{ color: '#3b82f6' }} />
            <div>
              <p className="text-sm font-medium" style={{ color: '#6b7280' }}>텍스트 청크</p>
              <p className="text-2xl font-bold" style={{ color: '#3b82f6' }}>{document.total_chunks}개</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg p-4 border border-gray-200 shadow-sm">
          <div className="flex items-center space-x-3">
            <ImageIcon className="h-8 w-8" style={{ color: '#f59e0b' }} />
            <div>
              <p className="text-sm font-medium" style={{ color: '#6b7280' }}>이미지 요약</p>
              <p className="text-2xl font-bold" style={{ color: '#f59e0b' }}>{document.total_images}개</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg p-4 border border-gray-200 shadow-sm">
          <div className="flex items-center space-x-3">
            <File className="h-8 w-8" style={{ color: '#3b82f6' }} />
            <div className="flex-1">
              <p className="text-sm font-medium mb-2" style={{ color: '#6b7280' }}>원본 파일</p>
              <a
                href={`/input/${encodeURIComponent(document.filename)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center space-x-1 text-sm font-medium transition-colors"
                style={{ color: '#3b82f6' }}
                onMouseEnter={(e: React.MouseEvent<HTMLAnchorElement>) => e.currentTarget.style.color = '#2563eb'}
                onMouseLeave={(e: React.MouseEvent<HTMLAnchorElement>) => e.currentTarget.style.color = '#3b82f6'}
              >
                <span>원본 파일 보기</span>
                <ExternalLink className="h-4 w-4" />
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* 탭 네비게이션 */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200">
        <div className="border-b border-gray-200">
          <div className="flex space-x-1 p-1">
            <button
              onClick={() => setActiveTab('text')}
              className={`flex-1 flex items-center justify-center space-x-2 px-4 py-3 font-medium transition-colors rounded-t-lg ${
                activeTab === 'text'
                  ? 'bg-blue-50 text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <FileText className="h-5 w-5" />
              <span>텍스트 청크 ({document.total_chunks}개)</span>
            </button>
            <button
              onClick={() => setActiveTab('image')}
              className={`flex-1 flex items-center justify-center space-x-2 px-4 py-3 font-medium transition-colors rounded-t-lg ${
                activeTab === 'image'
                  ? 'bg-amber-50 text-amber-600 border-b-2 border-amber-600'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
              }`}
            >
              <ImageIcon className="h-5 w-5" />
              <span>이미지 요약 ({document.total_images}개)</span>
            </button>
          </div>
        </div>

        {/* 텍스트 청크 탭 */}
        {activeTab === 'text' && (
          <div className="divide-y divide-gray-200">
            {document.text_chunks.length > 0 ? (
              document.text_chunks.map((chunk: ChunkDetail, idx: number) => (
                <div key={idx} className="p-6 hover:bg-gray-50 transition-colors">
                  <div className="flex justify-between items-start mb-3">
                    <h3 className="font-semibold text-gray-900">
                      청크 #{chunk.chunk_index} ({idx + 1}/{document.total_chunks})
                    </h3>
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                      {chunk.length}자
                    </span>
                  </div>
                  <div className="prose max-w-none">
                    <div className="text-gray-700 whitespace-pre-wrap leading-relaxed">
                      {renderChunkContent(chunk.content, document.filename)}
                    </div>
                  </div>
                  <details className="mt-4">
                    <summary className="text-sm text-gray-600 cursor-pointer hover:text-gray-900">
                      메타데이터 보기
                    </summary>
                    <pre className="mt-2 p-3 bg-gray-50 rounded text-xs overflow-x-auto">
                      {JSON.stringify(chunk.metadata, null, 2)}
                    </pre>
                  </details>
                </div>
              ))
            ) : (
              <div className="p-6 text-center text-gray-500">
                텍스트 청크가 없습니다.
              </div>
            )}
          </div>
        )}

        {/* 이미지 요약 탭 */}
        {activeTab === 'image' && (
          <div className="divide-y divide-gray-200">
            {document.image_summaries.length > 0 ? (
              document.image_summaries.map((imageSummary: ImageSummary, idx: number) => {
                // 이미지 경로 추출 (metadata에서)
                const imagePaths = imageSummary.metadata?.chunk_images || imageSummary.metadata?.image_paths || []
                const fileStem = document.filename.replace(/\.[^/.]+$/, '')
                const encodedStem = encodeURIComponent(fileStem)

                return (
                  <div key={idx} className="p-6 hover:bg-gray-50 transition-colors">
                    <div className="flex justify-between items-start mb-3">
                      <h3 className="font-semibold text-gray-900">
                        이미지 요약 #{idx + 1} ({idx + 1}/{document.total_images})
                      </h3>
                      <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                        {imageSummary.length}자
                      </span>
                    </div>
                    
                    {/* 이미지 표시 */}
                    {imagePaths.length > 0 && (
                      <div className="mb-4 space-y-2">
                        {imagePaths.map((imgPath: string, imgIdx: number) => {
                          // 이미지 파일명 추출
                          let imageFileName = ''
                          if (imgPath.includes('/images/')) {
                            const parts = imgPath.split('/images/')
                            imageFileName = parts[parts.length - 1]
                          } else if (imgPath.startsWith('images/')) {
                            imageFileName = imgPath.replace('images/', '')
                          } else {
                            imageFileName = imgPath
                          }
                          
                          const encodedFileName = encodeURIComponent(imageFileName)
                          const possiblePaths = [
                            `/static/${encodedStem}/vlm/images/${encodedFileName}`,
                            `/static/${encodedStem}/ocr/images/${encodedFileName}`,
                            `/static/${encodedStem}/images/${encodedFileName}`,
                          ]

                          return (
                            <div key={imgIdx} className="border border-gray-200 rounded-lg p-2 bg-gray-50">
                              <p className="text-xs text-gray-500 mb-2">이미지: {imageFileName}</p>
                              <ImageWithFallback
                                paths={possiblePaths}
                                alt={`이미지 ${imgIdx + 1}`}
                                originalPath={imgPath}
                              />
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* VLM 요약 내용 */}
                    <div className="prose max-w-none">
                      <div className="text-gray-700 whitespace-pre-wrap leading-relaxed bg-amber-50 p-4 rounded-lg border border-amber-200">
                        <p className="font-semibold text-amber-800 mb-2">[VLM 이미지 요약]</p>
                        <p className="text-gray-800">{imageSummary.summary}</p>
                      </div>
                    </div>

                    <details className="mt-4">
                      <summary className="text-sm text-gray-600 cursor-pointer hover:text-gray-900">
                        메타데이터 보기
                      </summary>
                      <pre className="mt-2 p-3 bg-gray-50 rounded text-xs overflow-x-auto">
                        {JSON.stringify(imageSummary.metadata, null, 2)}
                      </pre>
                    </details>
                  </div>
                )
              })
            ) : (
              <div className="p-6 text-center text-gray-500">
                이미지 요약이 없습니다.
              </div>
            )}
          </div>
        )}
      </div>

    </div>
  )
}

