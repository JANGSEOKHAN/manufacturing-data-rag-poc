import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 8901,
    host: 'localhost',
    allowedHosts: [
      'localhost'
    ],
    proxy: {
      '/api': {
        target: 'http://localhost:8601',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
