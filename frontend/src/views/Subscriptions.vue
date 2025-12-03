<template>
  <div class="subscriptions-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>订阅管理</span>
          <el-button type="primary" @click="handleAdd">添加订阅</el-button>
        </div>
      </template>

      <el-table :data="subscriptions" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="订阅名称" />
        <el-table-column prop="format" label="格式" width="100">
          <template #default="{ row }">
            <el-tag>{{ row.format === 'base64' ? 'Base64' : 'Clash' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="subscription_url" label="订阅链接">
          <template #default="{ row }">
            <el-input
              :value="getSubscriptionUrl(row.token)"
              readonly
              style="width: 100%"
            >
              <template #append>
                <el-button @click="copyUrl(getSubscriptionUrl(row.token))">复制</el-button>
              </template>
            </el-input>
          </template>
        </el-table-column>
        <el-table-column prop="enabled" label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              v-model="row.enabled"
              @change="handleToggle(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="700px"
      @close="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
      >
        <el-form-item label="订阅名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入订阅名称" />
        </el-form-item>
        <el-form-item label="订阅格式" prop="format">
          <el-select v-model="form.format" placeholder="请选择订阅格式">
            <el-option label="Base64" value="base64" />
            <el-option label="Clash" value="clash" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择节点" prop="proxy_ids">
          <div style="width: 100%">
            <div style="margin-bottom: 10px">
              <el-button size="small" @click="selectAllProxies">全选</el-button>
              <el-button size="small" @click="clearAllProxies">清空</el-button>
            </div>
            <el-checkbox-group v-model="form.proxy_ids" style="width: 100%">
              <el-checkbox
                v-for="proxy in availableProxies"
                :key="proxy.id"
                :label="proxy.id"
                style="display: block; margin-bottom: 8px"
              >
                {{ proxy.name }} ({{ proxy.protocol }}) - {{ proxy.server_name }}
              </el-checkbox>
            </el-checkbox-group>
            <div v-if="availableProxies.length === 0" style="color: #909399; font-size: 12px; margin-top: 10px">
              暂无可用节点，请先创建节点
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const subscriptions = ref([])
const dialogVisible = ref(false)
const formRef = ref(null)
const availableProxies = ref([])
const isEdit = ref(false)

const form = reactive({
  name: '',
  format: 'base64',
  proxy_ids: []
})

const dialogTitle = computed(() => isEdit.value ? '编辑订阅' : '添加订阅')

const rules = {
  name: [{ required: true, message: '请输入订阅名称', trigger: 'blur' }],
  format: [{ required: true, message: '请选择订阅格式', trigger: 'change' }],
  proxy_ids: [{ required: true, message: '请至少选择一个节点', trigger: 'change' }]
}

const fetchSubscriptions = async () => {
  loading.value = true
  try {
    const response = await api.get('/subscriptions/')
    subscriptions.value = response.data.results || response.data
  } catch (error) {
    ElMessage.error('获取订阅列表失败')
  } finally {
    loading.value = false
  }
}

const fetchProxies = async () => {
  try {
    const response = await api.get('/proxies/')
    const proxies = response.data.results || response.data || []
    // 只显示启用且状态为active的节点
    availableProxies.value = proxies.filter(p => p.enable && p.status === 'active')
  } catch (error) {
    console.error('获取节点列表失败:', error)
    availableProxies.value = []
  }
}

const selectAllProxies = () => {
  form.proxy_ids = availableProxies.value.map(p => p.id)
}

const clearAllProxies = () => {
  form.proxy_ids = []
}

const handleAdd = () => {
  resetForm()
  isEdit.value = false
  fetchProxies().then(() => {
    // 默认全选
    selectAllProxies()
    dialogVisible.value = true
  })
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个订阅吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/subscriptions/${row.id}/`)
    ElMessage.success('删除成功')
    fetchSubscriptions()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleToggle = async (row) => {
  try {
    await api.patch(`/subscriptions/${row.id}/`, { enabled: row.enabled })
    ElMessage.success('更新成功')
  } catch (error) {
    ElMessage.error('更新失败')
    row.enabled = !row.enabled
  }
}

// 根据当前访问页面的URL生成订阅链接
const getSubscriptionUrl = (token) => {
  // 获取当前页面的 origin（协议+主机+端口）
  const origin = window.location.origin
  // 构建订阅URL
  return `${origin}/api/subscriptions/${token}/`
}

const copyUrl = (url) => {
  navigator.clipboard.writeText(url).then(() => {
    ElMessage.success('复制成功')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      try {
        if (isEdit.value && form.id) {
          await api.put(`/subscriptions/${form.id}/`, form)
          ElMessage.success('更新成功')
        } else {
          await api.post('/subscriptions/', form)
          ElMessage.success('添加成功')
        }
        dialogVisible.value = false
        fetchSubscriptions()
      } catch (error) {
        ElMessage.error(isEdit.value ? '更新失败' : '添加失败')
      }
    }
  })
}

const resetForm = () => {
  Object.assign(form, {
    name: '',
    format: 'base64',
    proxy_ids: []
  })
  isEdit.value = false
  formRef.value?.resetFields()
}

onMounted(() => {
  fetchSubscriptions()
  fetchProxies()
})
</script>

<style scoped>
.subscriptions-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

