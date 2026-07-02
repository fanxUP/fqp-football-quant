import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: {
      modules: {
        classNameStrategy: 'non-scoped',
      },
    },
    deps: {
      inline: ['echarts'],
    },
  },
});
