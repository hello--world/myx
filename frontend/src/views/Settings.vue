<template>
  <div class="settings-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>系统设置</span>
        </div>
      </template>

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
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const formRef = ref(null)
const saving = ref(false)
const showIconPreview = ref(false)
const form = reactive({
  site_title: '',
  site_subtitle: '',
  site_icon: ''
})

const rules = {
  site_title: [
    { required: true, message: '请输入网站标题', trigger: 'blur' }
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

onMounted(() => {
  loadSettings()
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

