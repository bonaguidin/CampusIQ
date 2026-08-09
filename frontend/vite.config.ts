import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // This value is consumed only by the Node-based Vite development proxy. It is
  // deliberately not VITE_-prefixed and is never exposed to browser modules.
  const env = loadEnv(mode, '..', 'GRADUSIQ_')
  const proxySecret = env.GRADUSIQ_PROXY_SECRET

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          ...(proxySecret
            ? { headers: { 'X-GradusIQ-Proxy-Secret': proxySecret } }
            : {}),
        },
      },
    },
  }
})
