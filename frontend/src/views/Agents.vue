<template>
  <div class="agents-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>Agent 管理</span>
          <el-button type="primary" @click="loadAgents">刷新</el-button>
        </div>
      </template>

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
        <el-table-column prop="version" label="版本" width="120" />
        <el-table-column prop="last_heartbeat" label="最后心跳" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.last_heartbeat) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="500" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="viewCommands(row)">查看命令</el-button>
            <el-button size="small" type="primary" @click="sendCommand(row)">下发命令</el-button>
            <el-button size="small" type="success" @click="startAgent(row)">启动</el-button>
            <el-button size="small" type="warning" @click="stopAgent(row)">停止</el-button>
            <el-button size="small" type="info" @click="upgradeAgent(row)">升级</el-button>
            <el-button size="small" type="danger" @click="redeployAgent(row)">重新部署</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 下发命令对话框 -->
    <el-dialog
      v-model="commandDialogVisible"
      title="下发命令"
      width="600px"
    >
      <el-form :model="commandForm" label-width="100px">
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
          <el-input
            :model-value="currentCommand?.result || ''"
            type="textarea"
            :rows="10"
            readonly
          />
        </el-descriptions-item>
        <el-descriptions-item label="错误信息" v-if="currentCommand?.error">
          <el-input
            :model-value="currentCommand?.error || ''"
            type="textarea"
            :rows="5"
            readonly
          />
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const agents = ref([])
const loading = ref(false)
const commandDialogVisible = ref(false)
const commandsDialogVisible = ref(false)
const resultDialogVisible = ref(false)
const commandsLoading = ref(false)
const commandHistory = ref([])
const currentCommand = ref(null)
const currentAgent = ref(null)

const commandForm = ref({
  command: '',
  args: '',
  timeout: 300
})

const loadAgents = async () => {
  loading.value = true
  try {
    const response = await api.get('/agents/')
    agents.value = response.data
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
  } catch (error) {
    ElMessage.error('下发命令失败: ' + (error.response?.data?.detail || error.message))
  }
}

const viewCommands = async (agent) => {
  currentAgent.value = agent
  commandsLoading.value = true
  commandsDialogVisible.value = true

  try {
    const response = await api.get(`/agents/${agent.id}/commands/`)
    commandHistory.value = response.data
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

const upgradeAgent = async (agent) => {
  try {
    await ElMessageBox.confirm('确定要升级该Agent吗？', '提示', {
      type: 'warning'
    })

    await api.post(`/agents/${agent.id}/upgrade/`)
    ElMessage.success('升级命令已下发，请稍后查看命令执行结果')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('升级失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const redeployAgent = async (agent) => {
  try {
    await ElMessageBox.confirm('重新部署将重新安装Agent，确定要继续吗？', '提示', {
      type: 'warning'
    })

    await api.post(`/agents/${agent.id}/redeploy/`)
    ElMessage.success('重新部署已启动，请查看部署任务')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('重新部署失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

onMounted(() => {
  loadAgents()
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

