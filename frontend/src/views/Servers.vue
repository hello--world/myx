<template>
  <div class="servers-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>服务器管理</span>
          <el-button type="primary" @click="handleAdd">添加服务器</el-button>
        </div>
      </template>

      <el-table 
        :data="servers" 
        v-loading="loading" 
        style="width: 100%"
        empty-text="暂无数据"
      >
        <el-table-column prop="name" label="名称"  min-width="150" />
        <el-table-column prop="host" label="主机地址" min-width="130" />
        <el-table-column prop="port" label="SSH端口" min-width="80" />
        <el-table-column prop="username" label="用户名" min-width="80" />
        <el-table-column prop="connection_method" label="连接方式" min-width="80">
          <template #default="{ row }">
            <el-tag type="info">{{ getConnectionMethodText(row.connection_method) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deployment_target" label="部署目标" min-width="80">
          <template #default="{ row }">
            <el-tag type="success">{{ getDeploymentTargetText(row.deployment_target) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_check" label="最后检查" min-width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.last_check) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="220">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-button 
                size="small" 
                :type="testSuccessMap[row.id] ? 'success' : 'warning'"
                @click="handleTest(row)" 
                :loading="testingServerId === row.id"
                :disabled="testingServerId === row.id"
              >
                {{ testSuccessMap[row.id] ? '连接成功' : '测试连接' }}
              </el-button>
              <el-button size="small" type="primary" @click="handleEdit(row)">编辑</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="600px"
      @close="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
      >
        <el-form-item label="服务器名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入服务器名称" />
        </el-form-item>
        <el-form-item label="主机地址" prop="host">
          <el-input v-model="form.host" placeholder="请输入主机IP或域名" />
        </el-form-item>
        <el-form-item label="SSH端口" prop="port">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item label="SSH用户名" prop="username">
          <el-input v-model="form.username" placeholder="请输入SSH用户名" />
        </el-form-item>
        <el-form-item label="SSH密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入SSH密码（或使用私钥）"
            show-password
          />
        </el-form-item>
        <el-form-item label="SSH私钥" prop="private_key">
          <el-input
            v-model="form.private_key"
            type="textarea"
            :rows="4"
            placeholder="请输入SSH私钥内容（可选）"
          />
        </el-form-item>
        <el-form-item label="连接方式" prop="connection_method">
          <el-select v-model="form.connection_method" placeholder="请选择连接方式" style="width: 100%">
            <el-option label="SSH" value="ssh" />
            <el-option label="Agent" value="agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署目标" prop="deployment_target">
          <el-select v-model="form.deployment_target" placeholder="请选择部署目标" style="width: 100%">
            <el-option label="宿主机" value="host" />
            <el-option label="Docker" value="docker" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button 
            :type="dialogTestSuccess ? 'success' : 'warning'"
            @click="handleTestInDialog" 
            :loading="testingConnection"
            :disabled="testingConnection || saving"
          >
            <el-icon v-if="!testingConnection && !dialogTestSuccess"><Connection /></el-icon>
            <el-icon v-else-if="dialogTestSuccess"><Check /></el-icon>
            {{ dialogTestSuccess ? '连接成功' : '测试连接' }}
          </el-button>
          <el-button 
            @click="dialogVisible = false" 
            :disabled="testingConnection || saving"
          >
            取消
          </el-button>
          <el-button 
            type="primary" 
            @click="handleSubmit" 
            :loading="saving"
            :disabled="testingConnection || saving"
          >
            <el-icon v-if="!saving"><Check /></el-icon>
            {{ editingId ? '更新' : '保存' }}
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Check } from '@element-plus/icons-vue'
import api from '@/api'

const loading = ref(false)
const servers = ref([])
const dialogVisible = ref(false)
const dialogTitle = ref('添加服务器')
const formRef = ref(null)
const editingId = ref(null)
const testingConnection = ref(false) // 测试连接loading状态
const saving = ref(false) // 保存loading状态
const testingServerId = ref(null) // 正在测试的服务器ID（用于表格中的测试按钮）
const testSuccessMap = ref({}) // 记录每个服务器的测试成功状态 {serverId: true/false}
const dialogTestSuccess = ref(false) // 表单中测试连接是否成功

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: '',
  password: '',
  private_key: '',
  connection_method: 'ssh',
  deployment_target: 'host'
})

const rules = {
  name: [{ required: true, message: '请输入服务器名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入主机地址', trigger: 'blur' }],
  port: [{ required: true, message: '请输入SSH端口', trigger: 'blur' }],
  username: [{ required: true, message: '请输入SSH用户名', trigger: 'blur' }]
}

const fetchServers = async () => {
  loading.value = true
  try {
    const response = await api.get('/servers/')
    servers.value = response.data.results || response.data || []
    // 根据服务器状态初始化测试成功状态（如果状态是active，显示为成功）
    if (Array.isArray(servers.value)) {
      servers.value.forEach(server => {
        if (server.status === 'active' && !(server.id in testSuccessMap.value)) {
          testSuccessMap.value[server.id] = true
        }
      })
    }
  } catch (error) {
    console.error('获取服务器列表失败:', error)
    ElMessage.error('获取服务器列表失败: ' + (error.response?.data?.message || error.message))
    servers.value = []
  } finally {
    loading.value = false
  }
}

const getStatusType = (status) => {
  const map = {
    active: 'success',
    inactive: 'info',
    error: 'danger'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    active: '活跃',
    inactive: '不活跃',
    error: '错误'
  }
  return map[status] || status
}

const getConnectionMethodText = (method) => {
  const map = {
    ssh: 'SSH',
    agent: 'Agent'
  }
  return map[method] || method
}

const getDeploymentTargetText = (target) => {
  const map = {
    host: '宿主机',
    docker: 'Docker'
  }
  return map[target] || target
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return '-'
  try {
    const date = new Date(dateTime)
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  } catch (error) {
    return '-'
  }
}

const handleAdd = () => {
  dialogTitle.value = '添加服务器'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  dialogTitle.value = '编辑服务器'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    host: row.host,
    port: row.port,
    username: row.username,
    password: '',
    private_key: '',
    connection_method: row.connection_method || 'ssh',
    deployment_target: row.deployment_target || 'host'
  })
  dialogTestSuccess.value = false // 重置测试状态
  dialogVisible.value = true
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个服务器吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/servers/${row.id}/`)
    ElMessage.success('删除成功')
    fetchServers()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleTest = async (row) => {
  if (testingServerId.value === row.id) return // 防止重复点击
  
  testingServerId.value = row.id
  testSuccessMap.value[row.id] = false // 重置状态
  try {
    await api.post(`/servers/${row.id}/test_connection/`)
    testSuccessMap.value[row.id] = true // 标记为成功
    ElMessage.success('连接测试成功')
    fetchServers()
  } catch (error) {
    testSuccessMap.value[row.id] = false // 标记为失败
    const errorMsg = error.response?.data?.message || '连接测试失败'
    ElMessage.error(errorMsg)
  } finally {
    testingServerId.value = null
  }
}

const handleTestInDialog = async () => {
  if (!formRef.value) return
  
  // 先验证必填字段
  try {
    await formRef.value.validateField(['name', 'host', 'port', 'username'])
  } catch (error) {
    ElMessage.warning('请先填写必填字段')
    return
  }
  
  // 检查是否有密码或私钥
  if (!form.password && !form.private_key) {
    ElMessage.warning('请提供SSH密码或私钥')
    return
  }
  
  testingConnection.value = true
  dialogTestSuccess.value = false // 重置状态
  try {
    const testData = {
      host: form.host,
      port: form.port,
      username: form.username,
      password: form.password || '',
      private_key: form.private_key || ''
    }
    await api.post('/servers/test/', testData)
    dialogTestSuccess.value = true // 标记为成功
    ElMessage.success('连接测试成功')
  } catch (error) {
    dialogTestSuccess.value = false // 标记为失败
    const errorMsg = error.response?.data?.message || '连接测试失败'
    ElMessage.error(errorMsg)
  } finally {
    testingConnection.value = false
  }
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      saving.value = true
      try {
        if (editingId.value) {
          await api.put(`/servers/${editingId.value}/`, form)
          ElMessage.success('更新成功')
        } else {
          await api.post('/servers/', form)
          ElMessage.success('添加成功')
        }
        
        dialogVisible.value = false
        fetchServers()
      } catch (error) {
        const errorMsg = error.response?.data?.message || '操作失败'
        ElMessage.error(errorMsg)
      } finally {
        saving.value = false
      }
    }
  })
}

const resetForm = () => {
  Object.assign(form, {
    name: '',
    host: '',
    port: 22,
    username: '',
    password: '',
    private_key: '',
    connection_method: 'ssh',
    deployment_target: 'host'
  })
  formRef.value?.resetFields()
  testingConnection.value = false
  saving.value = false
  dialogTestSuccess.value = false // 重置测试成功状态
}

onMounted(() => {
  fetchServers()
})
</script>

<style scoped>
.servers-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.dialog-footer .el-button .el-icon {
  margin-right: 4px;
}

.action-buttons {
  display: flex;
  gap: 6px;
}

/* 减少表头单元格的padding，让表头更紧凑 */
:deep(.el-table th) {
  padding: 8px 0 !important;
}

:deep(.el-table td) {
  padding: 8px 0 !important;
}

:deep(.el-table th .cell) {
  padding-left: 8px;
  padding-right: 8px;
}

:deep(.el-table td .cell) {
  padding-left: 8px;
  padding-right: 8px;
}
</style>

