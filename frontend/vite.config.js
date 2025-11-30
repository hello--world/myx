import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  // 加载环境变量
  // Vite 默认从项目根目录（frontend/）查找 .env 文件
  // 但我们希望从项目根目录（../）加载
  const env = loadEnv(mode, resolve(__dirname, '..'), '')
  
  // 从环境变量读取配置
  const allowedHosts = env.VITE_ALLOWED_HOSTS
    ? env.VITE_ALLOWED_HOSTS.split(',').map(h => h.trim()).filter(Boolean)
    : []

  console.log('Vite allowedHosts:', allowedHosts.length > 0 ? allowedHosts : '未配置')

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src')
      }
    },
    server: {
      host: '0.0.0.0', // 监听所有网络接口，允许从其他设备访问
      port: 5173,
      // 允许的主机列表（从环境变量读取）
      allowedHosts: allowedHosts.length > 0 ? allowedHosts : undefined,
      proxy: {
        '/api': {
          target: env.VITE_API_URL || 'http://localhost:8000',
          changeOrigin: true
        }
      }
    }
  }
})

