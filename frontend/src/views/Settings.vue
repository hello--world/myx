<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>系统设置</span>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="系统设置" name="system">
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-width="120px"
            style="max-width: 600px"
          >
            <el-form-item label="网站标题" prop="site_title">
          <el-input
            v-model="form.site_title"
            placeholder="请输入网站标题"
            clearable
          />
          <div class="form-tip">此标题将显示在浏览器标签页和页面头部</div>
        </el-form-item>

        <el-form-item label="网站副标题" prop="site_subtitle">
          <el-input
            v-model="form.site_subtitle"
            placeholder="请输入网站副标题（可选）"
            clearable
          />
          <div class="form-tip">副标题将显示在页面头部标题下方（可选）</div>
        </el-form-item>

        <el-form-item label="网站图标" prop="site_icon">
          <el-input
            v-model="form.site_icon"
            type="textarea"
            :rows="10"
            placeholder="请输入SVG图标代码（可选）"
            clearable
          />
          <div class="form-tip">
            输入SVG代码，将用作网站图标和favicon。留空则使用默认图标。
            <el-button type="text" size="small" @click="showIconPreview = !showIconPreview" style="margin-left: 10px">
              {{ showIconPreview ? '隐藏预览' : '显示预览' }}
            </el-button>
          </div>
          <div v-if="showIconPreview && form.site_icon" class="icon-preview">
            <div class="preview-label">图标预览：</div>
            <div class="preview-container" v-html="form.site_icon"></div>
          </div>
        </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="handleSubmit" :loading="saving">
                保存设置
              </el-button>
              <el-button @click="handleReset">重置</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        
        <el-tab-pane label="账户设置" name="account">
          <el-form
            ref="userFormRef"
            :model="userForm"
            :rules="userRules"
            label-width="120px"
            style="max-width: 600px"
          >
            <el-form-item label="用户名" prop="username">
              <el-input
                v-model="userForm.username"
                placeholder="请输入用户名"
                clearable
              />
            </el-form-item>
            
            <el-form-item label="邮箱" prop="email">
              <el-input
                v-model="userForm.email"
                type="email"
                placeholder="请输入邮箱（可选）"
                clearable
              />
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="handleUpdateUser" :loading="userSaving">
                保存用户信息
              </el-button>
            </el-form-item>
          </el-form>
          
          <el-divider />
          
          <el-form
            ref="passwordFormRef"
            :model="passwordForm"
            :rules="passwordRules"
            label-width="120px"
            style="max-width: 600px"
          >
            <el-form-item label="当前密码" prop="old_password">
              <el-input
                v-model="passwordForm.old_password"
                type="password"
                placeholder="请输入当前密码"
                show-password
                clearable
              />
            </el-form-item>
            
            <el-form-item label="新密码" prop="new_password">
              <el-input
                v-model="passwordForm.new_password"
                type="password"
                placeholder="请输入新密码（至少8位）"
                show-password
                clearable
              />
            </el-form-item>
            
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input
                v-model="passwordForm.confirm_password"
                type="password"
                placeholder="请再次输入新密码"
                show-password
                clearable
              />
            </el-form-item>
            
            <el-form-item>
              <el-button type="primary" @click="handleChangePassword" :loading="passwordSaving">
                修改密码
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'
import { useAuthStore } from '@/stores/auth'

const formRef = ref(null)
const userFormRef = ref(null)
const passwordFormRef = ref(null)
const saving = ref(false)
const userSaving = ref(false)
const passwordSaving = ref(false)
const showIconPreview = ref(false)
const activeTab = ref('system')

const form = reactive({
  site_title: '',
  site_subtitle: '',
  site_icon: ''
})

const userForm = reactive({
  username: '',
  email: ''
})

const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: ''
})

const rules = {
  site_title: [
    { required: true, message: '请输入网站标题', trigger: 'blur' }
  ]
}

const userRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, message: '用户名长度至少为3位', trigger: 'blur' }
  ],
  email: [
    { type: 'email', message: '请输入有效的邮箱地址', trigger: 'blur' }
  ]
}

const validateConfirmPassword = (rule, value, callback) => {
  if (value !== passwordForm.new_password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const passwordRules = {
  old_password: [
    { required: true, message: '请输入当前密码', trigger: 'blur' }
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码长度至少为8位', trigger: 'blur' }
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

const loadSettings = async () => {
  try {
    const response = await api.get('/settings/')
    Object.assign(form, {
      site_title: response.data.site_title || '',
      site_subtitle: response.data.site_subtitle || '',
      site_icon: response.data.site_icon || ''
    })
    // 更新页面标题和图标
    updatePageTitle()
    updateFavicon()
  } catch (error) {
    ElMessage.error('加载设置失败: ' + (error.response?.data?.detail || error.message))
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return

  await formRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        await api.put('/settings/1/', form)
        ElMessage.success('设置保存成功')
        // 更新页面标题和图标
        updatePageTitle()
        updateFavicon()
        // 触发标题更新事件，让 MainLayout 也能更新
        window.dispatchEvent(new CustomEvent('settings-updated', { detail: form }))
      } catch (error) {
        ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.message))
      } finally {
        saving.value = false
      }
    }
  })
}

const handleReset = () => {
  loadSettings()
}

const updatePageTitle = () => {
  document.title = form.site_title || 'MyX - 科学技术管理平台'
}

const updateFavicon = () => {
  // 移除旧的favicon链接
  const oldFavicon = document.querySelector('link[rel="icon"]')
  if (oldFavicon) {
    oldFavicon.remove()
  }

  if (form.site_icon && form.site_icon.trim()) {
    // 创建新的favicon链接（使用SVG）
    const link = document.createElement('link')
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    // 将SVG转换为data URI
    const svgBlob = new Blob([form.site_icon], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(svgBlob)
    link.href = url
    document.head.appendChild(link)
  } else {
    // 使用默认图标
    const link = document.createElement('link')
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    link.href = '/favicon.svg'
    document.head.appendChild(link)
  }
}

const loadUserInfo = async () => {
  try {
    const response = await api.get('/auth/user/')
    Object.assign(userForm, {
      username: response.data.username || '',
      email: response.data.email || ''
    })
  } catch (error) {
    ElMessage.error('加载用户信息失败: ' + (error.response?.data?.detail || error.message))
  }
}

const handleUpdateUser = async () => {
  if (!userFormRef.value) return
  
  await userFormRef.value.validate(async (valid) => {
    if (valid) {
      userSaving.value = true
      try {
        await api.put('/auth/user/update/', userForm)
        ElMessage.success('用户信息更新成功')
        // 更新 auth store
        const authStore = useAuthStore()
        await authStore.fetchUser()
      } catch (error) {
        ElMessage.error('更新失败: ' + (error.response?.data?.error || error.response?.data?.detail || error.message))
      } finally {
        userSaving.value = false
      }
    }
  })
}

const handleChangePassword = async () => {
  if (!passwordFormRef.value) return
  
  await passwordFormRef.value.validate(async (valid) => {
    if (valid) {
      passwordSaving.value = true
      try {
        await api.post('/auth/user/change-password/', {
          old_password: passwordForm.old_password,
          new_password: passwordForm.new_password
        })
        ElMessage.success('密码修改成功')
        // 清空密码表单
        passwordForm.old_password = ''
        passwordForm.new_password = ''
        passwordForm.confirm_password = ''
        passwordFormRef.value.resetFields()
      } catch (error) {
        ElMessage.error('修改失败: ' + (error.response?.data?.error || error.response?.data?.detail || error.message))
      } finally {
        passwordSaving.value = false
      }
    }
  })
}

onMounted(() => {
  loadSettings()
  loadUserInfo()
})
</script>

<style scoped>
.settings-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>

