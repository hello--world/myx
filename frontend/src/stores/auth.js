import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const isAuthenticated = ref(false)

  const login = async (username, password) => {
    try {
      const response = await api.post('/auth/login/', { username, password })
      if (response.data && response.data.user) {
        user.value = response.data.user
        isAuthenticated.value = true
        return { success: true }
      } else {
        return {
          success: false,
          message: '登录响应格式错误'
        }
      }
    } catch (error) {
      console.error('登录错误:', error)
      return {
        success: false,
        message: error.response?.data?.message || error.message || '登录失败'
      }
    }
  }

  const logout = async () => {
    try {
      await api.post('/auth/logout/')
    } catch (error) {
      console.error('登出失败:', error)
    } finally {
      user.value = null
      isAuthenticated.value = false
    }
  }

  const fetchUser = async () => {
    try {
      const response = await api.get('/auth/user/')
      user.value = response.data
      isAuthenticated.value = true
    } catch (error) {
      isAuthenticated.value = false
      user.value = null
    }
  }

  return {
    user,
    isAuthenticated,
    login,
    logout,
    fetchUser
  }
})

