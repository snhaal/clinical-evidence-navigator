import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig(async () => {
  const reactModule: any = await Function('return import("@vitejs/plugin-react")')();
  const react = reactModule.default || reactModule;
  return {
    plugins: [react()],
    test: {
      environment: 'jsdom',
      globals: true,
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './'),
      },
    },
  };
});
