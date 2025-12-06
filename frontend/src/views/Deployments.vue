<template>
  <div class="deployments-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>部署任务</span>
          <div>
            <el-button type="success" @click="handleQuickDeploy">一键部署</el-button>
            <el-button type="primary" @click="handleAdd">创建部署任务</el-button>
          </div>
        </div>
      </template>

      <el-table :data="deployments" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="任务名称" />
        <el-table-column prop="server_name" label="服务器" />
        <el-table-column prop="deployment_type" label="部署类型" width="120">
          <template #default="{ row }">
            <el-tag>{{ getDeploymentTypeText(row.deployment_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="connection_method" label="连接方式" width="100">
          <template #default="{ row }">
            <el-tag type="info">{{ getConnectionMethodText(row.connection_method || row.server?.connection_method) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deployment_target" label="部署目标" width="100">
          <template #default="{ row }">
            <el-tag type="success">{{ getDeploymentTargetText(row.deployment_target || row.server?.deployment_target) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间">
          <template #default="{ row }">
            {{ formatDateTime(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="completed_at" label="完成时间">
          <template #default="{ row }">
            {{ formatDateTime(row.completed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="350">
          <template #default="{ row }">
            <el-button size="small" @click="handleViewLogs(row)">查看日志</el-button>
            <el-button 
              v-if="row.status === 'running'" 
              size="small" 
              type="danger" 
              @click="handleStop(row)"
              :loading="stoppingDeploymentId === row.id"
            >
              停止
            </el-button>
            <el-button 
              v-if="row.status === 'failed' || row.status === 'timeout' || row.status === 'cancelled'" 
              size="small" 
              type="warning" 
              @click="handleRetry(row)"
              :loading="retryingDeploymentId === row.id"
            >
              重试
            </el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      title="创建部署任务"
      width="600px"
      @close="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="120px"
      >
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="form.name" placeholder="留空将根据部署类型和服务器自动生成" />
        </el-form-item>
        <el-form-item label="服务器" prop="server">
          <el-select v-model="form.server" placeholder="请选择服务器" style="width: 100%" @change="handleServerChange">
            <el-option
              v-for="server in servers"
              :key="server.id"
              :label="server.name"
              :value="server.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="部署类型" prop="deployment_type">
          <el-select v-model="form.deployment_type" placeholder="请选择部署类型" style="width: 100%" @change="handleDeploymentTypeChange">
            <el-option label="Xray" value="xray" />
            <el-option label="Caddy" value="caddy" />
            <el-option label="Xray + Caddy" value="both" />
          </el-select>
        </el-form-item>
        <el-form-item label="连接方式" prop="connection_method">
          <el-select v-model="form.connection_method" placeholder="请选择连接方式（留空使用服务器默认）" style="width: 100%">
            <el-option label="使用服务器默认" value="" />
            <el-option label="SSH" value="ssh" />
            <el-option label="Agent" value="agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署目标" prop="deployment_target">
          <el-select v-model="form.deployment_target" placeholder="请选择部署目标（留空使用服务器默认）" style="width: 100%">
            <el-option label="使用服务器默认" value="" />
            <el-option label="宿主机" value="host" />
            <el-option label="Docker" value="docker" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="logDialogVisible"
      title="部署日志"
      width="800px"
      @close="stopLogRefresh"
    >
      <el-scrollbar height="500px" ref="logScrollbarRef">
        <pre style="white-space: pre-wrap; font-family: monospace; font-size: 12px; padding: 10px; margin: 0;">{{ currentLog || '暂无日志' }}</pre>
      </el-scrollbar>
      <template #footer>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span v-if="currentDeploymentId && getDeploymentById(currentDeploymentId)?.status === 'running'" style="color: #409eff;">
            ⚡ 部署中，日志每2秒自动刷新
          </span>
          <span v-else></span>
          <el-button @click="logDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="quickDeployDialogVisible"
      title="一键部署"
      width="600px"
      @close="resetQuickDeployForm"
    >
      <el-form
        ref="quickDeployFormRef"
        :model="quickDeployForm"
        :rules="quickDeployRules"
        label-width="120px"
      >
        <el-form-item label="服务器选择">
          <el-radio-group v-model="quickDeployForm.inputMode" @change="handleInputModeChange">
            <el-radio label="select">使用已有服务器</el-radio>
            <el-radio label="input">直接输入SSH信息</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="quickDeployForm.inputMode === 'select'">
          <el-form-item label="选择服务器" prop="server_id">
            <el-select v-model="quickDeployForm.server_id" placeholder="请选择服务器" style="width: 100%" @change="handleServerSelect">
              <el-option
                v-for="server in servers"
                :key="server.id"
                :label="`${server.name} (${server.host})`"
                :value="server.id"
              />
            </el-select>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="服务器名称" prop="name">
            <el-input v-model="quickDeployForm.name" placeholder="请输入服务器名称" />
          </el-form-item>
          <el-form-item label="主机地址" prop="host">
            <el-input v-model="quickDeployForm.host" placeholder="请输入主机IP或域名" />
          </el-form-item>
          <el-form-item label="SSH端口" prop="port">
            <el-input-number v-model="quickDeployForm.port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="SSH用户名" prop="username">
            <el-input v-model="quickDeployForm.username" placeholder="请输入SSH用户名" />
          </el-form-item>
          <el-form-item label="SSH密码" prop="password">
            <el-input
              v-model="quickDeployForm.password"
              type="password"
              placeholder="请输入SSH密码（或使用私钥）"
              show-password
            />
          </el-form-item>
          <el-form-item label="SSH私钥" prop="private_key">
            <el-input
              v-model="quickDeployForm.private_key"
              type="textarea"
              :rows="4"
              placeholder="请输入SSH私钥内容（可选）"
            />
          </el-form-item>
        </template>

        <el-form-item label="部署目标" prop="deployment_target">
          <el-select v-model="quickDeployForm.deployment_target" placeholder="请选择部署目标" style="width: 100%">
            <el-option label="宿主机" value="host" />
            <el-option label="Docker" value="docker" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="quickDeployDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleQuickDeploySubmit" :loading="quickDeployLoading">开始部署</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const deployments = ref([])
const servers = ref([])
const dialogVisible = ref(false)
const logDialogVisible = ref(false)
const quickDeployDialogVisible = ref(false)
const quickDeployLoading = ref(false)
const currentLog = ref('')
const currentDeploymentId = ref(null)
const logRefreshInterval = ref(null)
const logScrollbarRef = ref(null)
const formRef = ref(null)
const quickDeployFormRef = ref(null)
const retryingDeploymentId = ref(null)
const stoppingDeploymentId = ref(null)

const form = reactive({
  name: '',
  server: null,
  deployment_type: 'xray',
  connection_method: '',
  deployment_target: ''
})

const rules = {
  name: [{ required: false }], // 任务名称改为可选，会自动生成
  server: [{ required: true, message: '请选择服务器', trigger: 'change' }],
  deployment_type: [{ required: true, message: '请选择部署类型', trigger: 'change' }]
}

const fetchDeployments = async () => {
  loading.value = true
  try {
    const response = await api.get('/deployments/')
    deployments.value = response.data.results || response.data
  } catch (error) {
    ElMessage.error('获取部署任务列表失败')
  } finally {
    loading.value = false
  }
}

const fetchServers = async () => {
  try {
    const response = await api.get('/servers/')
    servers.value = response.data.results || response.data
  } catch (error) {
    console.error('获取服务器列表失败:', error)
  }
}

const quickDeployForm = reactive({
  inputMode: 'select', // 'select' 或 'input'
  server_id: null,
  name: '',
  host: '',
  port: 22,
  username: '',
  password: '',
  private_key: '',
  deployment_target: 'host'
})

const quickDeployRules = {
  server_id: [{ required: false }],
  name: [{ required: false }],
  host: [{ required: false }],
  port: [{ required: false }],
  username: [{ required: false }],
  password: [{ required: false }],
  deployment_target: [{ required: true, message: '请选择部署目标', trigger: 'change' }]
}

const getDeploymentTypeText = (type) => {
  const map = {
    xray: 'Xray',
    caddy: 'Caddy',
    both: 'Xray + Caddy',
    full: '一键部署'
  }
  return map[type] || type
}

const getConnectionMethodText = (method) => {
  const map = {
    ssh: 'SSH',
    agent: 'Agent'
  }
  return map[method] || method || '-'
}

const getDeploymentTargetText = (target) => {
  const map = {
    host: '宿主机',
    docker: 'Docker'
  }
  return map[target] || target || '-'
}

const getStatusType = (status) => {
  const map = {
    pending: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger',
    timeout: 'danger',
    cancelled: 'info'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    failed: '失败',
    timeout: '超时',
    cancelled: '已取消'
  }
  return map[status] || status
}

const handleAdd = () => {
  resetForm()
  dialogVisible.value = true
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个部署任务吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/deployments/${row.id}/`)
    ElMessage.success('删除成功')
    fetchDeployments()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleViewLogs = async (row) => {
  try {
    currentDeploymentId.value = row.id
    await fetchLogs(row.id)
    logDialogVisible.value = true
    // 如果任务还在运行中，启动自动刷新
    if (row.status === 'running' || row.status === 'pending') {
      startLogRefresh()
    }
  } catch (error) {
    ElMessage.error('获取日志失败')
  }
}

const handleStop = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要停止部署任务 "${row.name}" 吗？\n\n` +
      `停止后任务将标记为"已取消"状态，无法继续执行。`,
      '确认停止',
      {
        confirmButtonText: '确定停止',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    if (stoppingDeploymentId.value === row.id) return // 防止重复点击
    
    stoppingDeploymentId.value = row.id
    try {
      const response = await api.post(`/deployments/${row.id}/stop/`)
      ElMessage.success(response.data.message || '部署任务已停止')
      await fetchDeployments()
      // 如果当前正在查看这个任务的日志，刷新日志
      if (currentDeploymentId.value === row.id) {
        await fetchLogs(row.id)
        stopLogRefresh()
      }
    } catch (error) {
      console.error('停止部署任务失败:', error)
      ElMessage.error(error.response?.data?.error || '停止失败')
    } finally {
      stoppingDeploymentId.value = null
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('停止部署任务失败:', error)
    }
  }
}

const handleRetry = async (row) => {
  if (retryingDeploymentId.value === row.id) return // 防止重复点击
  
  try {
    await ElMessageBox.confirm('确定要重试这个部署任务吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    retryingDeploymentId.value = row.id
    await api.post(`/deployments/${row.id}/retry/`)
    ElMessage.success('重试任务已启动')
    fetchDeployments()
  } catch (error) {
    if (error !== 'cancel') {
      const errorMsg = error.response?.data?.error || '重试失败'
      ElMessage.error(errorMsg)
    }
  } finally {
    retryingDeploymentId.value = null
  }
}

const fetchLogs = async (deploymentId) => {
  try {
    const response = await api.get(`/deployments/${deploymentId}/logs/`)
    const newLog = response.data.log || response.data.error_message || '暂无日志'
    
    // 只有在日志内容变化时才更新，并滚动到底部
    if (newLog !== currentLog.value) {
      currentLog.value = newLog
      // 等待DOM更新后滚动到底部
      await nextTick()
      scrollLogToBottom()
    }
    
    // 同时获取任务状态，如果已完成则停止刷新
    const deployment = deployments.value.find(d => d.id === deploymentId)
          if (deployment && (deployment.status === 'success' || deployment.status === 'failed' || deployment.status === 'timeout' || deployment.status === 'cancelled')) {
      stopLogRefresh()
    }
  } catch (error) {
    console.error('获取日志失败:', error)
  }
}

const scrollLogToBottom = () => {
  if (logScrollbarRef.value) {
    // 获取内部滚动容器
    const scrollbar = logScrollbarRef.value
    const scrollContainer = scrollbar.$el?.querySelector('.el-scrollbar__wrap')
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight
    }
  }
}

const getDeploymentById = (id) => {
  return deployments.value.find(d => d.id === id)
}

const startLogRefresh = () => {
  // 清除之前的定时器
  stopLogRefresh()
  // 每2秒刷新一次日志
  logRefreshInterval.value = setInterval(() => {
    if (currentDeploymentId.value) {
      fetchLogs(currentDeploymentId.value)
    }
  }, 2000)
}

const stopLogRefresh = () => {
  if (logRefreshInterval.value) {
    clearInterval(logRefreshInterval.value)
    logRefreshInterval.value = null
  }
}

// 自动生成任务名称
const generateTaskName = () => {
  if (!form.deployment_type || !form.server) {
    return ''
  }
  
  const server = servers.value.find(s => s.id === form.server)
  if (!server) {
    return ''
  }
  
  const typeTextMap = {
    xray: '部署Xray',
    caddy: '部署Caddy',
    both: '部署Xray + Caddy'
  }
  
  const typeText = typeTextMap[form.deployment_type] || '部署'
  return `${typeText} - ${server.name}`
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      try {
        // 如果任务名称为空，自动生成
        const submitData = { ...form }
        if (!submitData.name || submitData.name.trim() === '') {
          submitData.name = generateTaskName()
        }
        
        await api.post('/deployments/', submitData)
        ElMessage.success('部署任务已创建')
        dialogVisible.value = false
        fetchDeployments()
      } catch (error) {
        ElMessage.error('创建失败')
      }
    }
  })
}

const handleQuickDeploy = () => {
  resetQuickDeployForm()
  quickDeployDialogVisible.value = true
}

const handleInputModeChange = () => {
  // 切换模式时重置表单验证
  if (quickDeployFormRef.value) {
    quickDeployFormRef.value.clearValidate()
  }
  // 更新验证规则
  updateQuickDeployRules()
}

const handleServerSelect = (serverId) => {
  // 选择服务器时，自动填充部署目标
  const server = servers.value.find(s => s.id === serverId)
  if (server) {
    quickDeployForm.deployment_target = server.deployment_target || 'host'
  }
}

// 处理部署类型变化，自动生成任务名称
const handleDeploymentTypeChange = () => {
  // 如果任务名称为空或者是自动生成的格式，则自动生成
  if (!form.name || form.name.match(/^(部署|一键部署)/)) {
    const autoName = generateTaskName()
    if (autoName) {
      form.name = autoName
    }
  }
}

// 处理服务器选择变化，自动生成任务名称
const handleServerChange = () => {
  // 如果任务名称为空或者是自动生成的格式，则自动生成
  if (!form.name || form.name.match(/^(部署|一键部署)/)) {
    const autoName = generateTaskName()
    if (autoName) {
      form.name = autoName
    }
  }
}

const updateQuickDeployRules = () => {
  if (quickDeployForm.inputMode === 'select') {
    quickDeployRules.server_id = [{ required: true, message: '请选择服务器', trigger: 'change' }]
    quickDeployRules.name = [{ required: false }]
    quickDeployRules.host = [{ required: false }]
    quickDeployRules.port = [{ required: false }]
    quickDeployRules.username = [{ required: false }]
    quickDeployRules.password = [{ required: false }]
    quickDeployRules.private_key = [{ required: false }]
  } else {
    quickDeployRules.server_id = [{ required: false }]
    quickDeployRules.name = [{ required: true, message: '请输入服务器名称', trigger: 'blur' }]
    quickDeployRules.host = [{ required: true, message: '请输入主机地址', trigger: 'blur' }]
    quickDeployRules.port = [{ required: true, message: '请输入SSH端口', trigger: 'blur' }]
    quickDeployRules.username = [{ required: true, message: '请输入SSH用户名', trigger: 'blur' }]
    // 密码或私钥至少提供一个
    quickDeployRules.password = [{
      validator: (rule, value, callback) => {
        if (!value && !quickDeployForm.private_key) {
          callback(new Error('请输入SSH密码或私钥'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }]
    quickDeployRules.private_key = [{ required: false }]
  }
}

const handleQuickDeploySubmit = async () => {
  if (!quickDeployFormRef.value) return
  
  // 手动验证密码或私钥（直接输入模式）
  if (quickDeployForm.inputMode === 'input') {
    if (!quickDeployForm.password && !quickDeployForm.private_key) {
      ElMessage.warning('请输入SSH密码或私钥')
      return
    }
  }
  
  // 根据输入模式构建请求数据
  let requestData = {
    deployment_target: quickDeployForm.deployment_target
  }
  
  if (quickDeployForm.inputMode === 'select') {
    // 使用已有服务器
    if (!quickDeployForm.server_id) {
      ElMessage.warning('请选择服务器')
      return
    }
    requestData.server_id = quickDeployForm.server_id
  } else {
    // 直接输入SSH信息（不保存密码）
    requestData.name = quickDeployForm.name
    requestData.host = quickDeployForm.host
    requestData.port = quickDeployForm.port
    requestData.username = quickDeployForm.username
    requestData.password = quickDeployForm.password || ''
    requestData.private_key = quickDeployForm.private_key || ''
  }
  
  await quickDeployFormRef.value.validate(async (valid) => {
    if (valid) {
      quickDeployLoading.value = true
      try {
        const response = await api.post('/deployments/quick-deploy/', requestData)
        ElMessage.success('一键部署任务已创建')
        quickDeployDialogVisible.value = false
        fetchDeployments()
        fetchServers()  // 刷新服务器列表（可能新增了服务器）
      } catch (error) {
        const errorMsg = error.response?.data?.error || error.response?.data?.message || '创建失败'
        ElMessage.error(errorMsg)
      } finally {
        quickDeployLoading.value = false
      }
    }
  })
}

const resetQuickDeployForm = () => {
  Object.assign(quickDeployForm, {
    inputMode: 'select',
    server_id: null,
    name: '',
    host: '',
    port: 22,
    username: '',
    password: '',
    private_key: '',
    deployment_target: 'host'
  })
  quickDeployFormRef.value?.resetFields()
  updateQuickDeployRules()
}

const resetForm = () => {
  Object.assign(form, {
    name: '',
    server: null,
    deployment_type: 'xray',
    connection_method: '',
    deployment_target: ''
  })
  formRef.value?.resetFields()
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return '-'
  const date = new Date(dateTime)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

onMounted(() => {
  fetchDeployments()
  fetchServers()
  updateQuickDeployRules()
  
  // 每2秒刷新一次部署状态（如果有运行中的任务）
  setInterval(() => {
    const hasRunning = deployments.value.some(d => d.status === 'running' || d.status === 'pending')
    if (hasRunning) {
      fetchDeployments()
      // 如果日志对话框打开且当前任务还在运行，也刷新日志
      if (logDialogVisible.value && currentDeploymentId.value) {
        const deployment = deployments.value.find(d => d.id === currentDeploymentId.value)
        if (deployment && (deployment.status === 'running' || deployment.status === 'pending')) {
          fetchLogs(currentDeploymentId.value)
        } else {
          stopLogRefresh()
        }
      }
    }
  }, 2000)
  
  // 监听部署任务创建事件（从Agent页面触发）
  window.addEventListener('deployment-created', () => {
    fetchDeployments()
  })
})
</script>

<style scoped>
.deployments-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

