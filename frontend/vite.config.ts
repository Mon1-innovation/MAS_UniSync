import {defineConfig} from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = 'http://127.0.0.1:8000'
const spaRouteBypass = (req: {headers: Record<string, string | string[] | undefined>}) => {
  const accept = req.headers.accept
  const acceptHeader = Array.isArray(accept) ? accept.join(',') : accept || ''
  return acceptHeader.includes('text/html') ? '/index.html' : undefined
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/login': {target: backendTarget, bypass: spaRouteBypass},
      '/logout': {target: backendTarget, bypass: spaRouteBypass},
      '/account': {target: backendTarget, bypass: spaRouteBypass},
      '/admin': {target: backendTarget, bypass: spaRouteBypass},
      '/v1': {target: backendTarget, bypass: spaRouteBypass},
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: true,
    exclude: ['node_modules', 'dist', 'e2e'],
  },
})
