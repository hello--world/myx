import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 获取 CSRF token
let csrfToken = null

const getCsrfToken = async () => {
  if (!csrfToken) {
    try {
      const response = await axios.get('/api/auth/csrf/', {
        withCredentials: true
      })
      csrfToken = response.data.csrfToken
    } catch (error) {
      console.error('获取 CSRF token 失败:', error)
    }
  }
  return csrfToken
}

// 请求拦截器
api.interceptors.request.use(
  async config => {
    // 对于 POST、PUT、PATCH、DELETE 请求，添加 CSRF token
    if (['post', 'put', 'patch', 'delete'].includes(config.method?.toLowerCase())) {
      const token = await getCsrfToken()
      if (token) {
        config.headers['X-CSRFToken'] = token
      }
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  response => {
    return response
  },
  error => {
    if (error.response?.status === 401) {
      // 未授权，跳转到登录页
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api

