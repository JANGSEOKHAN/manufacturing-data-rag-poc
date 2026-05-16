import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8902,
    host: 'localhost',
    allowedHosts: [
      'localhost'
    ],
    proxy: {
      '/api': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/input': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/status': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/upload_file': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/rag_query': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/delete_file': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/delete_all_files': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/rebuild_vectorstore': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
      '/chat_history': {
        target: 'http://localhost:8601',
        changeOrigin: true,
      },
    }
  }
})
