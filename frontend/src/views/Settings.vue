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
const form = reactive({
  site_title: '',
  site_subtitle: ''
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
      site_subtitle: response.data.site_subtitle || ''
    })
    // 更新页面标题
    updatePageTitle()
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
        // 更新页面标题
        updatePageTitle()
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
  document.title = form.site_title || 'MyX - 代理管理平台'
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

