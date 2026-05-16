import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { X, Upload, Loader2, CheckCircle2, AlertCircle } from 'lucide-react'
import { adminApi } from '../api/client'

interface FileUploadModalProps {
  onClose: () => void
  onSuccess: () => void
}

export default function FileUploadModal({ onClose, onSuccess }: FileUploadModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle')
  const [errorMessage, setErrorMessage] = useState<string>('')

  const uploadMutation = useMutation({
    mutationFn: (file: File) => adminApi.uploadFile(file),
    onSuccess: () => {
      setUploadStatus('success')
      setTimeout(() => {
        onSuccess()
      }, 1500)
    },
    onError: (error: any) => {
      setUploadStatus('error')
      setErrorMessage(error.response?.data?.detail || error.message || '업로드 실패')
    },
  })

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setUploadStatus('idle')
      setErrorMessage('')
    }
  }

  const handleUpload = () => {
    if (!selectedFile) return
    
    setUploadStatus('uploading')
    uploadMutation.mutate(selectedFile)
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
        <div className="flex justify-between items-center p-6 border-b border-gray-200">
          <h2 className="text-xl font-bold text-gray-900">파일 업로드</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              파일 선택 (DOCX, PPTX, XLSX)
            </label>
            <div className="mt-1 flex justify-center px-6 pt-5 pb-6 border-2 border-gray-300 border-dashed rounded-lg hover:border-primary-400 transition-colors">
              <div className="space-y-1 text-center">
                <Upload className="mx-auto h-12 w-12 text-gray-400" />
                <div className="flex text-sm text-gray-600">
                  <label className="relative cursor-pointer bg-white rounded-md font-medium text-primary-600 hover:text-primary-500 focus-within:outline-none focus-within:ring-2 focus-within:ring-offset-2 focus-within:ring-primary-500">
                    <span>파일 선택</span>
                    <input
                      type="file"
                      className="sr-only"
                      accept=".doc,.docx,.ppt,.pptx,.xls,.xlsx"
                      onChange={handleFileSelect}
                      disabled={uploadStatus === 'uploading'}
                    />
                  </label>
                  <p className="pl-1">또는 드래그 앤 드롭</p>
                </div>
                <p className="text-xs text-gray-500">Word, PowerPoint, Excel</p>
              </div>
            </div>
            {selectedFile && (
              <div className="mt-3 p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-700">
                  <span className="font-medium">선택된 파일:</span> {selectedFile.name}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  크기: {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                </p>
              </div>
            )}
          </div>

          {uploadStatus === 'uploading' && selectedFile && (
            <div className="flex items-center space-x-2 p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <Loader2 className="h-5 w-5 text-blue-600 animate-spin" />
              <p className="text-sm text-blue-800">해당 파일이 업로드 중입니다</p>
            </div>
          )}

          {uploadStatus === 'success' && (
            <div className="flex items-center space-x-2 p-3 bg-green-50 border border-green-200 rounded-lg">
              <CheckCircle2 className="h-5 w-5 text-green-600" />
              <p className="text-sm text-green-800">업로드가 완료되었습니다</p>
            </div>
          )}

          {uploadStatus === 'error' && (
            <div className="flex items-center space-x-2 p-3 bg-red-50 border border-red-200 rounded-lg">
              <AlertCircle className="h-5 w-5 text-red-600" />
              <p className="text-sm text-red-800">{errorMessage}</p>
            </div>
          )}

          <div className="flex space-x-3 pt-4">
            <button
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors"
              disabled={uploadStatus === 'uploading'}
            >
              취소
            </button>
            <button
              onClick={handleUpload}
              disabled={!selectedFile || uploadStatus === 'uploading' || uploadStatus === 'success'}
              className="flex-1 px-4 py-2 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center space-x-2 font-medium"
              style={{ background: '#3b82f6' }}
              onMouseEnter={(e) => !e.currentTarget.disabled && (e.currentTarget.style.background = '#2563eb')}
              onMouseLeave={(e) => !e.currentTarget.disabled && (e.currentTarget.style.background = '#3b82f6')}
            >
              {uploadStatus === 'uploading' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>업로드 중...</span>
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  <span>업로드</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
