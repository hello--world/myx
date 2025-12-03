<template>
  <div class="logs-page">
    <el-card class="logs-card">
      <template #header>
        <div class="card-header">
          <div class="header-title">
            <el-icon class="header-icon"><Document /></el-icon>
            <span>日志中心</span>
          </div>
          <div class="header-actions">
            <el-button
              :type="autoRefreshEnabled ? 'success' : 'default'"
              @click="toggleAutoRefresh"
              size="small"
              :loading="loading"
              :icon="autoRefreshEnabled ? 'Loading' : 'Refresh'"
            >
              {{ autoRefreshEnabled ? '自动刷新中' : '开启自动刷新' }}
            </el-button>
            <el-button @click="clearFilters" size="small" icon="RefreshLeft">清除筛选</el-button>
          </div>
        </div>
      </template>

      <!-- 筛选器 -->
      <div class="filters">
        <el-select v-model="filters.log_type" placeholder="日志类型" clearable style="width: 150px;" @change="fetchLogs" size="small">
          <el-option label="全部" value="" />
          <el-option label="部署日志" value="deployment" />
          <el-option label="命令执行" value="command" />
          <el-option label="Agent操作" value="agent" />
          <el-option label="代理操作" value="proxy" />
          <el-option label="服务器操作" value="server" />
          <el-option label="系统日志" value="system" />
        </el-select>
        <el-select v-model="filters.level" placeholder="日志级别" clearable style="width: 150px;" @change="fetchLogs" size="small">
          <el-option label="全部" value="" />
          <el-option label="信息" value="info" />
          <el-option label="成功" value="success" />
          <el-option label="警告" value="warning" />
          <el-option label="错误" value="error" />
        </el-select>
        <el-select v-model="filters.server" placeholder="服务器" clearable style="width: 200px;" @change="fetchLogs" size="small">
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
          style="width: 300px;"
          clearable
          size="small"
          @clear="fetchLogs"
          @keyup.enter="fetchLogs"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
          <template #append>
            <el-button @click="fetchLogs" size="small">搜索</el-button>
          </template>
        </el-input>
      </div>

      <el-table
        :data="logs"
        v-loading="loading"
        stripe
        style="width: 100%"
        @expand-change="handleExpandChange"
        :row-class-name="tableRowClassName"
      >
        <el-table-column type="expand" width="50">
          <template #default="{ row }">
            <div v-if="row.is_group" class="expanded-content">
              <div class="expanded-header">
                <el-icon class="expand-icon"><FolderOpened /></el-icon>
                <span class="expanded-title">任务组详情（共 {{ row.log_count }} 条日志）</span>
              </div>
              <div class="logs-list">
                <div v-for="(log, index) in row.logs" :key="log.id" class="log-item">
                  <div class="log-item-header">
                    <div class="log-meta">
                      <span class="log-index">#{{ index + 1 }}</span>
                      <el-tag :type="getLogTypeTagType(log.log_type) || undefined" size="small" effect="plain">
                        {{ log.log_type_display }}
                      </el-tag>
                      <el-tag :type="getLevelTagType(log.level) || undefined" size="small">
                        {{ log.level_display }}
                      </el-tag>
                      <span class="log-title">{{ log.title }}</span>
                    </div>
                    <span class="log-time">
                      <el-icon><Clock /></el-icon>
                      {{ formatDateTime(log.created_at) }}
                    </span>
                  </div>
                  <div class="log-content-wrapper">
                    <div class="log-content-label">日志内容：</div>
                    <el-scrollbar max-height="400px" class="log-content-scrollbar">
                      <pre class="log-content">{{ log.content || '无内容' }}</pre>
                    </el-scrollbar>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">
            <span v-if="row.is_group">{{ formatDateTime(row.last_log_time) }}</span>
            <span v-else>{{ formatDateTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="log_type_display" label="类型" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.is_group" type="info" size="small">任务组</el-tag>
            <el-tag v-else :type="getLogTypeTagType(row.log_type) || undefined">{{ row.log_type_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="level_display" label="级别" width="100">
          <template #default="{ row }">
            <span v-if="row.is_group">{{ row.log_count }} 条</span>
            <el-tag v-else :type="getLevelTagType(row.level) || undefined">{{ row.level_display }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题/任务" min-width="200">
          <template #default="{ row }">
            <span v-if="row.is_group" style="font-weight: bold;">{{ row.task_name }}</span>
            <span v-else>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="server_name" label="服务器" width="150" />
        <el-table-column prop="created_by_username" label="操作人" width="120" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_group" size="small" type="primary" @click="viewLogDetail(row)">查看详情</el-button>
            <span v-else style="color: #909399; font-size: 12px;">展开查看详情</span>
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
          <el-tag :type="getLogTypeTagType(currentLog.log_type) || undefined">{{ currentLog.log_type_display }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="级别">
          <el-tag :type="getLevelTagType(currentLog.level) || undefined">{{ currentLog.level_display }}</el-tag>
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
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Search, Refresh, RefreshLeft, FolderOpened, Clock } from '@element-plus/icons-vue'
import api from '@/api'

const loading = ref(false)
const logs = ref([])
const servers = ref([])
const detailDialogVisible = ref(false)
const currentLog = ref(null)
const expandedRows = ref([])  // 跟踪展开的行
const autoRefreshInterval = ref(null)  // 自动刷新定时器
const autoRefreshEnabled = ref(false)  // 自动刷新开关，默认关闭
const lastRefreshTime = ref(null)  // 最后刷新时间，用于增量更新

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

// 初始加载或手动刷新（全量刷新）
const fetchLogs = async (isIncremental = false) => {
  if (!isIncremental) {
    loading.value = true
  }
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.pageSize,
      group_by_task: 'true'  // 启用任务分组
    }
    if (filters.log_type) params.log_type = filters.log_type
    if (filters.level) params.level = filters.level
    if (filters.server) params.server = filters.server
    if (filters.search) params.search = filters.search

    const response = await api.get('/logs/', { params })
    const newLogs = response.data.results || response.data || []
    
    if (isIncremental && lastRefreshTime.value) {
      // 增量更新：只添加新日志到列表顶部
      const newLogsToAdd = []
      for (const log of newLogs) {
        const logTime = log.is_group ? log.last_log_time : log.created_at
        if (logTime && new Date(logTime) > new Date(lastRefreshTime.value)) {
          newLogsToAdd.push(log)
        }
      }
      
      if (newLogsToAdd.length > 0) {
        // 将新日志插入到列表顶部，避免重复
        const existingIds = new Set(logs.value.map(l => l.id))
        const uniqueNewLogs = newLogsToAdd.filter(l => !existingIds.has(l.id))
        if (uniqueNewLogs.length > 0) {
          logs.value = [...uniqueNewLogs, ...logs.value]
          pagination.total = response.data.count || logs.value.length
        }
      }
    } else {
      // 全量刷新
      logs.value = newLogs
      pagination.total = response.data.count || logs.value.length
    }
    
    // 更新最后刷新时间
    const now = new Date().toISOString()
    lastRefreshTime.value = now
    
  } catch (error) {
    console.error('获取日志失败:', error)
    if (!isIncremental) {
      ElMessage.error(error.response?.data?.detail || error.response?.data?.error || '获取日志失败')
    }
  } finally {
    if (!isIncremental) {
      loading.value = false
    }
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
  // 处理 null、undefined 或空值
  if (!type) {
    return ''
  }
  
  const map = {
    deployment: 'info',  // 改为 'info'，ElTag 不支持 'primary'
    command: 'success',
    agent: 'info',
    proxy: 'warning',
    server: 'danger',
    system: ''
  }
  // 确保返回的值是有效的 ElTag type 或空字符串
  const result = map[type] ?? ''
  // ElTag 的有效 type 值：'success', 'info', 'warning', 'danger' 或 ''
  const validTypes = ['success', 'info', 'warning', 'danger', '']
  return validTypes.includes(result) ? result : ''
}

const getLevelTagType = (level) => {
  // 处理 null、undefined 或空值
  if (!level) {
    return ''
  }
  
  const map = {
    info: '',
    success: 'success',
    warning: 'warning',
    error: 'danger'
  }
  // 确保返回的值是有效的 ElTag type 或空字符串
  const result = map[level] ?? ''
  // ElTag 的有效 type 值：'success', 'info', 'warning', 'danger' 或 ''
  const validTypes = ['success', 'info', 'warning', 'danger', '']
  return validTypes.includes(result) ? result : ''
}

const handleExpandChange = (row, expandedRowsArray) => {
  // 更新展开的行列表
  // expandedRowsArray 是当前所有展开的行数组
  if (row && row.is_group) {
    // 检查当前行是否在展开列表中
    const isExpanded = expandedRowsArray.some(r => r.id === row.id)
    if (isExpanded) {
      // 展开：添加到列表
      if (!expandedRows.value.includes(row.id)) {
        expandedRows.value.push(row.id)
      }
    } else {
      // 收起：从列表移除
      const index = expandedRows.value.indexOf(row.id)
      if (index > -1) {
        expandedRows.value.splice(index, 1)
      }
    }
  }
}

const tableRowClassName = ({ row }) => {
  if (row.is_group) {
    return 'group-row'
  }
  return ''
}

const toggleAutoRefresh = () => {
  if (autoRefreshEnabled.value) {
    // 关闭自动刷新
    stopAutoRefresh()
    autoRefreshEnabled.value = false
  } else {
    // 开启自动刷新
    // 先执行一次全量刷新
    fetchLogs(false).then(() => {
      startAutoRefresh()
      autoRefreshEnabled.value = true
    })
  }
}

const startAutoRefresh = () => {
  // 先清除已有的定时器
  stopAutoRefresh()
  // 增量刷新：只在没有展开的日志时才自动刷新
  autoRefreshInterval.value = setInterval(() => {
    if (expandedRows.value.length === 0) {
      fetchLogs(true)  // 增量刷新
    }
  }, 5000)
}

const stopAutoRefresh = () => {
  if (autoRefreshInterval.value) {
    clearInterval(autoRefreshInterval.value)
    autoRefreshInterval.value = null
  }
}

onMounted(() => {
  // 初始加载
  fetchLogs(false)  // 全量加载
  fetchServers()
  // 默认不自动刷新，需要用户手动开启
})

// 组件卸载时清除定时器
onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.logs-page {
  padding: 20px;
  background: #f5f7fa;
  min-height: calc(100vh - 60px);
}

.logs-card {
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.08);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.header-icon {
  font-size: 20px;
  color: #409eff;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
  padding: 16px;
  background: #f9fafb;
  border-radius: 6px;
}

/* 展开内容样式 */
.expanded-content {
  padding: 20px 40px;
  background: linear-gradient(to bottom, #f8f9fa 0%, #ffffff 100%);
  animation: expandAnimation 0.3s ease-out;
}

@keyframes expandAnimation {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.expanded-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #e4e7ed;
}

.expand-icon {
  font-size: 20px;
  color: #409eff;
}

.expanded-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.logs-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.log-item {
  background: #ffffff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  transition: all 0.3s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.log-item:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.log-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f0f2f5;
}

.log-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.log-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 24px;
  padding: 0 8px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 12px;
  font-weight: 600;
  border-radius: 12px;
}

.log-title {
  font-weight: 500;
  font-size: 14px;
  color: #303133;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-time {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 13px;
  white-space: nowrap;
}

.log-content-wrapper {
  margin-top: 12px;
}

.log-content-label {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 8px;
  padding-left: 4px;
}

.log-content-scrollbar {
  border-radius: 6px;
  overflow: hidden;
}

.log-content {
  white-space: pre-wrap;
  font-family: 'SF Mono', 'Monaco', 'Menlo', 'Ubuntu Mono', 'Consolas', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
  padding: 16px;
  background: #f8f9fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  color: #2c3e50;
}

/* 优化表格样式 */
:deep(.el-table) {
  font-size: 13px;
  border-radius: 8px;
  overflow: hidden;
}

:deep(.el-table th) {
  padding: 12px 0;
  background: #f5f7fa !important;
  font-weight: 600;
  color: #303133;
}

:deep(.el-table td) {
  padding: 10px 0;
}

:deep(.el-table .cell) {
  padding-left: 12px;
  padding-right: 12px;
}

:deep(.el-table__row.group-row) {
  background: #f0f9ff;
  font-weight: 500;
}

:deep(.el-table__row.group-row:hover) {
  background: #e0f2fe !important;
}

/* 优化分页样式 */
.pagination {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  padding: 16px;
  background: #fafafa;
  border-radius: 6px;
}

/* 优化对话框样式 */
:deep(.el-dialog) {
  border-radius: 12px;
  overflow: hidden;
}

:deep(.el-dialog__header) {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 20px;
}

:deep(.el-dialog__title) {
  color: white;
  font-weight: 600;
}

:deep(.el-dialog__close) {
  color: white !important;
}

:deep(.el-descriptions) {
  margin-top: 20px;
}
</style>

