import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8006';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 8066,
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/health': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
});
