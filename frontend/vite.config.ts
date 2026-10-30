import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // 项目规范：模块引用统一使用 @/ 路径别名
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
