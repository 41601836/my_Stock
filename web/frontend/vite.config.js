import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '::',       // dual-stack (IPv4+IPv6): Node 在 macOS/Linux 上默认 IPV6_V6ONLY=0，
                      // 同时接受 localhost(::1) 和 127.0.0.1 两种访问，解决
                      // Happy Eyeballs 竞态造成的"ERR_CONNECTION_REFUSED/OFFLINE"。
                      // 若目标环境禁止 dual-stack，Vite 会自动降级为 IPv4-only。
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false,
        timeout: 600000,
        proxyTimeout: 600000,
        configure: (proxy) => {
          proxy.on('error', (err, req, res) => {
            console.error(`[vite proxy] ${req.method} ${req.url} → ${err.code || err.message}`)
            if (res && !res.headersSent) {
              res.statusCode = 502
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ error: `上游无响应: ${err.code || err.message}` }))
            }
          })
        },
      }
    }
  },
  build: {
    target: 'es2020',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'charts': ['recharts'],
        }
      }
    }
  }
})
