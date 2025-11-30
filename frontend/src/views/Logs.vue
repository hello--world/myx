<template>
  <div class="logs-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>日志中心</span>
          <div>
            <el-button type="primary" @click="fetchLogs">刷新</el-button>
            <el-button @click="clearFilters">清除筛选</el-button>
          </div>
        </div>
      </template>

      <!-- 筛选器 -->
      <div class="filters" style="margin-bottom: 20px;">
        <el-select v-model="filters.log_type" placeholder="日志类型" clearable style="width: 150px; margin-right: 10px;" @change="fetchLogs">
          <el-option label="全部" value="" />
          <el-option label="部署日志" value="deployment" />
          <el-option label="命令执行" value="command" />
          <el-option label="Agent操作" value="agent" />
          <el-option label="代理操作" value="proxy" />
          <el-option label="服务器操作" value="server" />
          <el-option label="系统日志" value="system" />
        </el-select>
        <el-select v-model="filters.level" placeholder="日志级别" clearable style="width: 150px; margin-right: 10px;" @change="fetchLogs">
          <el-option label="全部" value="" />
          <el-option label="信息" value="info" />
          <el-option label="成功" value="success" />
          <el-option label="警告" value="warning" />
          <el-option label="错误" value="error" />
        </el-select>
        <el-select v-model="filters.server" placeholder="服务器" clearable style="width: 200px; margin-right: 10px;" @change="fetchLogs">
          <el-option label="全部" value="" />
          <el-option
            v-for="server in servers"
            :key="server.id"
            :label="server.name"
            :value="server.id"
          />
        </el-select>
        <el-input
          v-model="filters.search"
          placeholder="搜索标题或内容"
          style="width: 250px;"
          clearable
          @clear="fetchLogs"
          @keyup.enter="fetchLogs"
        >
          <template #append>
            <el-button @click="fetchLogs">搜索</el-button>
          </template>
        </el-input>
      </div>

      <el-table :data="logs" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">
            {{ formatDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="log_type_display" label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="getLogTypeTagType(row.log_type)">{{ row.log_type_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="level_display" label="级别" width="100">
          <template #default="{ row }">
            <el-tag :type="getLevelTagType(row.level)">{{ row.level_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="server_name" label="服务器" width="150" />
        <el-table-column prop="created_by_username" label="操作人" width="120" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="viewLogDetail(row)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination" style="margin-top: 20px; display: flex; justify-content: center;">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="pagination.total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleSizeChange"
          @current-change="handlePageChange"
        />
      </div>
    </el-card>

    <!-- 日志详情对话框 -->
    <el-dialog
      v-model="detailDialogVisible"
      :title="currentLog?.title"
      width="800px"
    >
      <el-descriptions :column="1" border v-if="currentLog">
        <el-descriptions-item label="时间">
          {{ formatDateTime(currentLog.created_at) }}
        </el-descriptions-item>
        <el-descriptions-item label="类型">
          <el-tag :type="getLogTypeTagType(currentLog.log_type)">{{ currentLog.log_type_display }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="级别">
          <el-tag :type="getLevelTagType(currentLog.level)">{{ currentLog.level_display }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="服务器" v-if="currentLog.server_name">
          {{ currentLog.server_name }}
        </el-descriptions-item>
        <el-descriptions-item label="操作人">
          {{ currentLog.created_by_username }}
        </el-descriptions-item>
        <el-descriptions-item label="内容">
          <el-scrollbar height="400px">
            <pre style="white-space: pre-wrap; font-family: monospace; padding: 10px; margin: 0;">{{ currentLog.content || '无内容' }}</pre>
          </el-scrollbar>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const logs = ref([])
const servers = ref([])
const detailDialogVisible = ref(false)
const currentLog = ref(null)

const filters = reactive({
  log_type: '',
  level: '',
  server: '',
  search: ''
})

const pagination = reactive({
  page: 1,
  pageSize: 20,
  total: 0
})

const fetchLogs = async () => {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize
    }
    if (filters.log_type) params.log_type = filters.log_type
    if (filters.level) params.level = filters.level
    if (filters.server) params.server = filters.server
    if (filters.search) params.search = filters.search

    const response = await api.get('/logs/', { params })
    logs.value = response.data.results || response.data || []
    pagination.total = response.data.count || logs.value.length
  } catch (error) {
    console.error('获取日志失败:', error)
    ElMessage.error('获取日志失败')
  } finally {
    loading.value = false
  }
}

const fetchServers = async () => {
  try {
    const response = await api.get('/servers/')
    servers.value = response.data.results || response.data || []
  } catch (error) {
    console.error('获取服务器列表失败:', error)
  }
}

const clearFilters = () => {
  filters.log_type = ''
  filters.level = ''
  filters.server = ''
  filters.search = ''
  pagination.page = 1
  fetchLogs()
}

const handleSizeChange = (size) => {
  pagination.pageSize = size
  pagination.page = 1
  fetchLogs()
}

const handlePageChange = (page) => {
  pagination.page = page
  fetchLogs()
}

const viewLogDetail = (log) => {
  currentLog.value = log
  detailDialogVisible.value = true
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

const getLogTypeTagType = (type) => {
  const map = {
    deployment: 'primary',
    command: 'success',
    agent: 'info',
    proxy: 'warning',
    server: 'danger',
    system: ''
  }
  return map[type] || ''
}

const getLevelTagType = (level) => {
  const map = {
    info: '',
    success: 'success',
    warning: 'warning',
    error: 'danger'
  }
  return map[level] || ''
}

onMounted(() => {
  fetchLogs()
  fetchServers()
  // 每5秒自动刷新
  setInterval(() => {
    fetchLogs()
  }, 5000)
})
</script>

<style scoped>
.logs-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
</style>

