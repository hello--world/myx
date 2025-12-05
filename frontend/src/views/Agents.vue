<template>
  <div class="agents-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>Agent 管理</span>
          <el-button type="primary" @click="loadAgents">刷新</el-button>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <el-tab-pane label="Agent列表" name="agents">
          <el-table
        :data="agents"
        v-loading="loading"
        stripe
        style="width: 100%"
      >
        <el-table-column prop="server_name" label="服务器名称" width="150" />
        <el-table-column prop="server_host" label="主机地址" width="150" />
        <el-table-column prop="server_port" label="SSH端口" width="100" />
        <el-table-column prop="connection_method" label="连接方式" width="100">
          <template #default="{ row }">
            <el-tag :type="row.connection_method === 'agent' ? 'success' : 'info'">
              {{ row.connection_method === 'agent' ? 'Agent' : 'SSH' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deployment_target" label="部署目标" width="100">
          <template #default="{ row }">
            <el-tag :type="row.deployment_target === 'docker' ? 'warning' : 'primary'">
              {{ row.deployment_target === 'docker' ? 'Docker' : '宿主机' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="heartbeat_mode" label="心跳模式" width="120">
          <template #default="{ row }">
            <el-tag :type="row.heartbeat_mode === 'pull' ? 'warning' : 'success'">
              {{ row.heartbeat_mode === 'pull' ? '拉取模式' : '推送模式' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="120" />
        <el-table-column prop="last_heartbeat" label="最后心跳" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.last_heartbeat) }}
          </template>
        </el-table-column>
        <el-table-column prop="last_check" label="最后检查" width="180" v-if="hasPullModeAgent">
          <template #default="{ row }">
            {{ formatDateTime(row.last_check) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="580" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewCommands(row)">查看命令</el-button>
            <el-button size="small" type="primary" @click="sendCommand(row)">下发命令</el-button>
            <el-button 
              size="small" 
              type="info" 
              @click="checkAgentStatus(row)" 
              v-if="row.heartbeat_mode === 'pull'"
            >
              检查状态
            </el-button>
            <el-button size="small" type="success" @click="startAgent(row)">启动</el-button>
            <el-button size="small" type="warning" @click="stopAgent(row)">停止</el-button>
            <el-button size="small" type="danger" @click="redeployAgent(row)">重新部署</el-button>
          </template>
        </el-table-column>
      </el-table>
        </el-tab-pane>
        
        <el-tab-pane label="命令管理" name="templates">
          <div style="margin-bottom: 20px;">
            <el-button type="primary" @click="handleAddTemplate">添加模板</el-button>
          </div>
          <el-table
            :data="commandTemplates"
            v-loading="templatesLoading"
            stripe
            style="width: 100%"
          >
            <el-table-column prop="name" label="模板名称" width="200" />
            <el-table-column prop="description" label="描述" />
            <el-table-column prop="command" label="命令" width="200" />
            <el-table-column prop="args" label="参数" width="200">
              <template #default="{ row }">
                {{ Array.isArray(row.args) ? row.args.join(' ') : row.args || '' }}
              </template>
            </el-table-column>
            <el-table-column prop="timeout" label="超时时间" width="100">
              <template #default="{ row }">
                {{ row.timeout }}秒
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" type="primary" @click="handleUseTemplate(row)">使用</el-button>
                <el-button size="small" @click="handleEditTemplate(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="handleDeleteTemplate(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 下发命令对话框 -->
    <el-dialog
      v-model="commandDialogVisible"
      title="下发命令"
      width="600px"
    >
      <el-form :model="commandForm" label-width="100px">
        <el-form-item label="选择模板">
          <el-select
            v-model="selectedTemplateId"
            placeholder="选择命令模板（可选）"
            style="width: 100%"
            clearable
            @change="handleTemplateSelect"
          >
            <el-option
              v-for="template in commandTemplates"
              :key="template.id"
              :label="template.name"
              :value="template.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="命令">
          <el-input v-model="commandForm.command" placeholder="例如: ls, ps, systemctl status" />
        </el-form-item>
        <el-form-item label="参数">
          <el-input
            v-model="commandForm.args"
            placeholder="多个参数用空格分隔，例如: -la /tmp"
          />
        </el-form-item>
        <el-form-item label="超时时间">
          <el-input-number v-model="commandForm.timeout" :min="10" :max="3600" />
          <span style="margin-left: 10px">秒</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="commandDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSendCommand">确定</el-button>
      </template>
    </el-dialog>

    <!-- 命令历史对话框 -->
    <el-dialog
      v-model="commandsDialogVisible"
      title="命令历史"
      width="900px"
    >
      <el-table
        :data="commandHistory"
        v-loading="commandsLoading"
        stripe
        style="width: 100%"
        max-height="500"
      >
        <el-table-column prop="command" label="命令" width="200" />
        <el-table-column prop="args" label="参数" width="200">
          <template #default="{ row }">
            {{ Array.isArray(row.args) ? row.args.join(' ') : row.args }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getCommandStatusType(row.status)">
              {{ getCommandStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="completed_at" label="完成时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.completed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="viewCommandResult(row)">查看结果</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 命令结果对话框 -->
    <el-dialog
      v-model="resultDialogVisible"
      title="命令执行结果"
      width="800px"
    >
      <el-descriptions :column="1" border v-if="currentCommand">
        <el-descriptions-item label="命令">
          {{ currentCommand.command }}
        </el-descriptions-item>
        <el-descriptions-item label="参数">
          {{ Array.isArray(currentCommand.args) ? currentCommand.args.join(' ') : currentCommand.args || '' }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getCommandStatusType(currentCommand.status)">
            {{ getCommandStatusText(currentCommand.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="执行结果">
          <el-scrollbar height="300px">
            <pre style="white-space: pre-wrap; font-family: monospace; padding: 10px; margin: 0; background: #f5f7fa; border-radius: 4px;">{{ currentCommand?.result || '暂无结果' }}</pre>
          </el-scrollbar>
        </el-descriptions-item>
        <el-descriptions-item label="错误信息" v-if="currentCommand?.error">
          <el-scrollbar height="200px">
            <pre style="white-space: pre-wrap; font-family: monospace; padding: 10px; margin: 0; background: #fef0f0; border-radius: 4px; color: #f56c6c;">{{ currentCommand?.error || '' }}</pre>
          </el-scrollbar>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 命令模板编辑对话框 -->
    <el-dialog
      v-model="templateDialogVisible"
      :title="editingTemplateId ? '编辑模板' : '添加模板'"
      width="600px"
    >
      <el-form :model="templateForm" label-width="100px">
        <el-form-item label="模板名称">
          <el-input v-model="templateForm.name" placeholder="例如: 查看系统状态" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="templateForm.description"
            type="textarea"
            :rows="2"
            placeholder="模板描述（可选）"
          />
        </el-form-item>
        <el-form-item label="命令">
          <el-input v-model="templateForm.command" placeholder="例如: systemctl" />
        </el-form-item>
        <el-form-item label="参数">
          <el-input
            v-model="templateForm.args"
            placeholder="多个参数用空格分隔，例如: status xray"
          />
        </el-form-item>
        <el-form-item label="超时时间">
          <el-input-number v-model="templateForm.timeout" :min="10" :max="3600" />
          <span style="margin-left: 10px">秒</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="templateDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveTemplate">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const agents = ref([])
const loading = ref(false)
const activeTab = ref('agents')
const commandDialogVisible = ref(false)
const commandsDialogVisible = ref(false)
const resultDialogVisible = ref(false)
const commandsLoading = ref(false)
const commandHistory = ref([])
const currentCommand = ref(null)
const currentAgent = ref(null)

// 命令模板相关
const commandTemplates = ref([])
const templatesLoading = ref(false)
const templateDialogVisible = ref(false)
const templateForm = ref({
  name: '',
  description: '',
  command: '',
  args: '',
  timeout: 300
})
const editingTemplateId = ref(null)
const selectedTemplateId = ref(null)

const commandForm = ref({
  command: '',
  args: '',
  timeout: 300
})

const hasPullModeAgent = computed(() => {
  return agents.value.some(agent => agent.heartbeat_mode === 'pull')
})

const loadAgents = async () => {
  loading.value = true
  try {
    const response = await api.get('/agents/')
    // 处理分页响应：Django REST Framework 返回 {count, next, previous, results}
    agents.value = response.data.results || response.data || []
  } catch (error) {
    ElMessage.error('加载Agent列表失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    loading.value = false
  }
}

const getStatusType = (status) => {
  const map = {
    'online': 'success',
    'offline': 'danger',
    'error': 'warning'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    'online': '在线',
    'offline': '离线',
    'error': '错误'
  }
  return map[status] || status
}

const getCommandStatusType = (status) => {
  const map = {
    'pending': 'info',
    'running': 'warning',
    'success': 'success',
    'failed': 'danger'
  }
  return map[status] || 'info'
}

const getCommandStatusText = (status) => {
  const map = {
    'pending': '等待中',
    'running': '执行中',
    'success': '成功',
    'failed': '失败'
  }
  return map[status] || status
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return '暂无'
  return new Date(dateTime).toLocaleString('zh-CN')
}

const sendCommand = (agent) => {
  currentAgent.value = agent
  commandForm.value = {
    command: '',
    args: '',
    timeout: 300
  }
  selectedTemplateId.value = null
  commandDialogVisible.value = true
}

const handleSendCommand = async () => {
  if (!commandForm.value.command) {
    ElMessage.warning('请输入命令')
    return
  }

  try {
    const args = commandForm.value.args
      ? commandForm.value.args.split(' ').filter(arg => arg.trim())
      : []

    const response = await api.post(
      `/agents/${currentAgent.value.id}/send_command/`,
      {
        command: commandForm.value.command,
        args: args,
        timeout: commandForm.value.timeout
      }
    )

    ElMessage.success('命令已下发')
    commandDialogVisible.value = false
    
    // 如果有返回的命令ID，立即查看结果
    if (response.data && response.data.command && response.data.command.id) {
      const commandId = response.data.command.id
      // 等待一下让命令开始执行
      setTimeout(async () => {
        await viewCommandResultById(commandId)
      }, 1000)
    }
  } catch (error) {
    ElMessage.error('下发命令失败: ' + (error.response?.data?.detail || error.message))
  }
}

const viewCommandResultById = async (commandId) => {
  try {
    // 从命令历史中查找
    const response = await api.get(`/agents/${currentAgent.value.id}/commands/`)
    const commands = response.data.results || response.data || []
    const command = commands.find(cmd => cmd.id === commandId)
    if (command) {
      viewCommandResult(command)
    } else {
      // 如果找不到，尝试直接获取
      ElMessage.warning('命令可能还在执行中，请稍后查看')
    }
  } catch (error) {
    console.error('获取命令结果失败:', error)
  }
}

let commandRefreshInterval = null

const stopCommandRefresh = () => {
  if (commandRefreshInterval) {
    clearInterval(commandRefreshInterval)
    commandRefreshInterval = null
  }
}

const startCommandRefresh = () => {
  stopCommandRefresh()
  commandRefreshInterval = setInterval(async () => {
    if (commandsDialogVisible.value && currentAgent.value) {
      try {
        const response = await api.get(`/agents/${currentAgent.value.id}/commands/`)
        commandHistory.value = response.data.results || response.data || []
      } catch (error) {
        console.error('刷新命令历史失败:', error)
      }
    } else {
      stopCommandRefresh()
    }
  }, 2000) // 每2秒刷新一次
}

const viewCommands = async (agent) => {
  currentAgent.value = agent
  commandsLoading.value = true
  commandsDialogVisible.value = true

  try {
    const response = await api.get(`/agents/${agent.id}/commands/`)
    commandHistory.value = response.data.results || response.data || []
    // 自动刷新命令状态
    startCommandRefresh()
  } catch (error) {
    ElMessage.error('加载命令历史失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    commandsLoading.value = false
  }
}

const viewCommandResult = (command) => {
  currentCommand.value = command
  resultDialogVisible.value = true
}

const startAgent = async (agent) => {
  try {
    await ElMessageBox.confirm('确定要启动该Agent吗？', '提示', {
      type: 'warning'
    })

    await api.post(`/agents/${agent.id}/start/`)
    ElMessage.success('启动命令已下发')
    await loadAgents()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('启动失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const stopAgent = async (agent) => {
  try {
    await ElMessageBox.confirm('确定要停止该Agent吗？', '提示', {
      type: 'warning'
    })

    await api.post(`/agents/${agent.id}/stop/`)
    ElMessage.success('停止命令已下发')
    await loadAgents()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('停止失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}


const redeployAgent = async (agent) => {
  try {
    await ElMessageBox.confirm(
      '重新部署将停止现有Agent服务，删除旧文件并全新安装最新版本的Agent。确定要继续吗？',
      '重新部署Agent',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const response = await api.post(`/agents/${agent.id}/redeploy/`)

    ElMessage.success({
      message: 'Agent重新部署已启动，请查看部署任务',
      duration: 5000,
      showClose: true
    })
    // 触发事件通知其他组件刷新部署任务列表
    if (response.data.deployment_id) {
      window.dispatchEvent(new CustomEvent('deployment-created', { detail: { deployment_id: response.data.deployment_id } }))
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('重新部署失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const checkAgentStatus = async (agent) => {
  try {
    await api.post(`/agents/${agent.id}/check_status/`)
    ElMessage.success('状态检查完成')
    await loadAgents()
  } catch (error) {
    ElMessage.error('检查状态失败: ' + (error.response?.data?.detail || error.message))
  }
}

// 命令模板相关函数
const loadTemplates = async () => {
  templatesLoading.value = true
  try {
    const response = await api.get('/agents/command-templates/')
    commandTemplates.value = response.data.results || response.data || []
  } catch (error) {
    ElMessage.error('加载命令模板失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    templatesLoading.value = false
  }
}

const handleTemplateSelect = (templateId) => {
  if (!templateId) return
  
  const template = commandTemplates.value.find(t => t.id === templateId)
  if (template) {
    commandForm.value.command = template.command
    commandForm.value.args = Array.isArray(template.args) ? template.args.join(' ') : template.args || ''
    commandForm.value.timeout = template.timeout
  }
}

const handleAddTemplate = () => {
  editingTemplateId.value = null
  templateForm.value = {
    name: '',
    description: '',
    command: '',
    args: '',
    timeout: 300
  }
  templateDialogVisible.value = true
}

const handleEditTemplate = (row) => {
  editingTemplateId.value = row.id
  templateForm.value = {
    name: row.name,
    description: row.description || '',
    command: row.command,
    args: Array.isArray(row.args) ? row.args.join(' ') : row.args || '',
    timeout: row.timeout
  }
  templateDialogVisible.value = true
}

const handleDeleteTemplate = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个命令模板吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/agents/command-templates/${row.id}/`)
    ElMessage.success('删除成功')
    loadTemplates()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const handleUseTemplate = (template) => {
  if (!currentAgent.value) {
    ElMessage.warning('请先选择Agent')
    return
  }
  commandForm.value.command = template.command
  commandForm.value.args = Array.isArray(template.args) ? template.args.join(' ') : template.args || ''
  commandForm.value.timeout = template.timeout
  selectedTemplateId.value = template.id
  commandDialogVisible.value = true
}

const handleSaveTemplate = async () => {
  if (!templateForm.value.name || !templateForm.value.command) {
    ElMessage.warning('请填写模板名称和命令')
    return
  }
  
  try {
    const args = templateForm.value.args
      ? templateForm.value.args.split(' ').filter(arg => arg.trim())
      : []
    
    const payload = {
      name: templateForm.value.name,
      description: templateForm.value.description || '',
      command: templateForm.value.command,
      args: args,
      timeout: templateForm.value.timeout
    }
    
    if (editingTemplateId.value) {
      await api.put(`/agents/command-templates/${editingTemplateId.value}/`, payload)
      ElMessage.success('更新成功')
    } else {
      await api.post('/agents/command-templates/', payload)
      ElMessage.success('添加成功')
    }
    
    templateDialogVisible.value = false
    loadTemplates()
  } catch (error) {
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.message))
  }
}

onMounted(() => {
  loadAgents()
  loadTemplates()
})
</script>

<style scoped>
.agents-container {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

