import { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Database, Home, FolderOpen, Network } from 'lucide-react'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()

  const isActive = (path: string) => location.pathname === path

  return (
    <div className="min-h-screen bg-white">
      {/* 헤더 */}
      <header className="bg-white shadow-sm border-b border-gray-200 sticky top-0 z-50">
        <div className="w-full px-6">
          <div className="flex justify-between items-center h-20">
            <Link to="/" className="flex items-center space-x-3 hover:opacity-80 transition-opacity">
              <Network className="h-8 w-8" style={{ color: '#3b82f6' }} />
              <h1 className="text-2xl font-semibold" style={{ color: '#3b82f6', letterSpacing: '0.5px' }}>
                AI KnowledgeOps Admin
              </h1>
            </Link>
            <nav className="flex space-x-3">
              <Link
                to="/"
                className={`flex items-center space-x-2 px-5 py-3 rounded-lg text-base font-medium transition-colors ${
                  isActive('/')
                    ? 'text-white'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
                style={isActive('/') ? { background: '#3b82f6' } : {}}
              >
                <Home className="h-5 w-5" />
                <span>홈</span>
              </Link>
              <Link
                to="/data"
                className={`flex items-center space-x-2 px-5 py-3 rounded-lg text-base font-medium transition-colors ${
                  isActive('/data')
                    ? 'text-white'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
                style={isActive('/data') ? { background: '#3b82f6' } : {}}
              >
                <FolderOpen className="h-5 w-5" />
                <span>데이터 관리</span>
              </Link>
              <Link
                to="/qdrant"
                className={`flex items-center space-x-2 px-5 py-3 rounded-lg text-base font-medium transition-colors ${
                  isActive('/qdrant')
                    ? 'text-white'
                    : 'text-gray-700 hover:bg-gray-100'
                }`}
                style={isActive('/qdrant') ? { background: '#3b82f6' } : {}}
              >
                <Database className="h-5 w-5" />
                <span>Qdrant DB Page</span>
              </Link>
            </nav>
          </div>
        </div>
      </header>

      {/* 메인 컨텐츠 */}
      <main className="w-full px-6 py-8">
        {children}
      </main>
    </div>
  )
}
