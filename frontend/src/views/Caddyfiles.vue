<template>
  <div class="caddyfiles-page">
    <div class="content-layout">
      <!-- 左侧：服务器列表 -->
      <div class="sidebar">
        <div class="sidebar-header">
          <h3>服务器列表</h3>
        </div>
        <div class="server-list" v-loading="loading">
          <div
            v-for="server in servers"
            :key="server.id"
            class="server-item"
            :class="{ active: selectedServerId === server.id }"
            @click="selectServer(server.id)"
          >
            <div class="server-name">{{ server.name }}</div>
            <el-tag size="small" :type="server.status === 'active' ? 'success' : 'info'">
              {{ server.status === 'active' ? '在线' : '离线' }}
            </el-tag>
          </div>
          <el-empty v-if="servers.length === 0 && !loading" description="暂无服务器" :image-size="80" />
        </div>
      </div>

      <!-- 中间：编辑器 -->
      <div class="editor-area">
        <el-empty
          v-if="!selectedServerId"
          description="请从左侧选择一个服务器"
          :image-size="150"
        />

        <div v-else class="editor-container">
          <!-- 工具栏 -->
          <div class="file-toolbar">
            <div class="file-info">
              <span class="server-name">{{ currentServerName }}</span>
              <span class="separator">|</span>
              <span class="file-path">/etc/caddy/Caddyfile</span>
              <span v-if="lastUpdateTime" class="separator">|</span>
              <span v-if="lastUpdateTime" class="update-time">{{ lastUpdateTime }}</span>
            </div>
            <div class="toolbar-actions">
              <el-button type="primary" size="small" @click="handleSave" :loading="saving">
                保存
              </el-button>
              <el-button type="success" size="small" @click="handleValidate" :loading="validating">
                验证配置
              </el-button>
              <el-button type="warning" size="small" @click="handleReload" :loading="reloading">
                重载 Caddy
              </el-button>
              <el-divider direction="vertical" />
              <el-button size="small" @click="handleRefresh" :loading="loadingContent">
                刷新
              </el-button>
              <el-button size="small" @click="copyContent">
                复制
              </el-button>
            </div>
          </div>

          <!-- 代码编辑器 -->
          <div class="editor-wrapper" v-loading="loadingContent">
            <codemirror
              v-model="content"
              :style="{ height: '100%' }"
              :autofocus="true"
              :indent-with-tab="true"
              :tab-size="2"
              :extensions="extensions"
              class="code-editor"
            />
          </div>
        </div>
      </div>

      <!-- 右侧：操作结果 -->
      <div class="result-panel">
        <div class="result-header">
          <h3>操作结果</h3>
          <el-button
            v-if="resultMessage"
            size="small"
            text
            @click="clearResult"
          >
            清空
          </el-button>
        </div>
        <div class="result-content">
          <el-empty
            v-if="!resultMessage"
            description="暂无操作结果"
            :image-size="100"
          />
          <div v-else class="result-display">
            <el-alert
              :title="resultMessage"
              :type="resultType"
              :closable="false"
              show-icon
            />
            <div v-if="resultDetail" class="result-detail">
              <div class="detail-header">详细信息</div>
              <pre class="detail-content">{{ resultDetail }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Codemirror } from 'vue-codemirror'
import { EditorView } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { StreamLanguage } from '@codemirror/language'
import { oneDark } from '@codemirror/theme-one-dark'
import api from '@/api'

const loading = ref(false)
const loadingContent = ref(false)
const saving = ref(false)
const validating = ref(false)
const reloading = ref(false)
const servers = ref([])
const selectedServerId = ref(null)
const content = ref('')
const currentProxyId = ref(null)
const lastUpdateTime = ref('')
const resultMessage = ref('')
const resultType = ref('info')
const resultDetail = ref('')
const useDarkTheme = ref(false)

// Caddyfile 语法高亮定义
const caddyfileLanguage = StreamLanguage.define({
  name: 'caddyfile',
  startState: () => ({ inBlock: false }),
  token: (stream, state) => {
    // 跳过空白
    if (stream.eatSpace()) return null
    
    // 匹配注释
    if (stream.match(/^#.*/)) {
      return 'comment'
    }
    
    // 匹配行首的域名/地址
    if (stream.sol()) {
      if (stream.match(/^[\w\.\-:\[\]]+/)) {
        return 'string'
      }
    }
    
    // 匹配花括号
    if (stream.match(/^[{}]/)) {
      if (stream.match(/^{/)) {
        state.inBlock = true
      } else {
        state.inBlock = false
      }
      return 'bracket'
    }
    
    // 在块内匹配指令
    if (state.inBlock) {
      if (stream.match(/^\w+/)) {
        return 'keyword'
      }
    }
    
    // 匹配路径
    if (stream.match(/^\/[\w\/\.\-]+/)) {
      return 'string'
    }
    
    // 匹配端口号
    if (stream.match(/^:\d+/)) {
      return 'number'
    }
    
    // 匹配引号内的字符串
    if (stream.match(/^"[^"]*"/) || stream.match(/^'[^']*'/)) {
      return 'string'
    }
    
    // 匹配其他内容
    stream.next()
    return null
  }
})

// CodeMirror 配置
const extensions = computed(() => {
  const baseExtensions = [
    EditorView.lineWrapping,
    EditorState.tabSize.of(2),
    caddyfileLanguage, // 使用自定义 Caddyfile 语法高亮
  ]
  
  // 可选：添加暗色主题
  if (useDarkTheme.value) {
    baseExtensions.push(oneDark)
  }
  
  return baseExtensions
})

const currentServerName = computed(() => {
  const server = servers.value.find(s => s.id === selectedServerId.value)
  return server ? server.name : ''
})

const fetchServers = async () => {
  loading.value = true
  try {
    const response = await api.get('/servers/')
    servers.value = response.data.results || response.data || []
  } catch (error) {
    console.error('获取服务器列表失败:', error)
    ElMessage.error('获取服务器列表失败')
  } finally {
    loading.value = false
  }
}

const selectServer = async (serverId) => {
  selectedServerId.value = serverId
  clearResult()
  await loadCaddyfile()
}

const loadCaddyfile = async () => {
  if (!selectedServerId.value) return

  loadingContent.value = true
  content.value = ''
  currentProxyId.value = null

  try {
    // 获取该服务器的代理节点
    const response = await api.get('/proxies/')
    const proxies = response.data.results || response.data || []
    const serverProxies = proxies.filter(p => p.server === selectedServerId.value)

    if (serverProxies.length === 0) {
      ElMessage.warning('该服务器没有代理节点')
      return
    }

    const proxy = serverProxies[0]
    currentProxyId.value = proxy.id

    // 读取 Caddyfile
    const caddyResponse = await api.get(`/proxies/${proxy.id}/get_caddyfile/`)
    content.value = caddyResponse.data.content || ''
    lastUpdateTime.value = new Date().toLocaleString()
  } catch (error) {
    console.error('读取 Caddyfile 失败:', error)
    ElMessage.error('读取 Caddyfile 失败: ' + (error.response?.data?.error || error.message))
  } finally {
    loadingContent.value = false
  }
}

const handleSave = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  if (!content.value.trim()) {
    ElMessage.warning('内容不能为空')
    return
  }

  saving.value = true
  clearResult()

  try {
    const response = await api.post(`/proxies/${currentProxyId.value}/update_caddyfile/`, {
      content: content.value
    })

    if (response.data.message) {
      ElMessage.success('保存成功')
      lastUpdateTime.value = new Date().toLocaleString()
      resultMessage.value = '保存成功'
      resultType.value = 'success'
      resultDetail.value = response.data.result || '文件已成功保存到服务器'
    } else {
      ElMessage.error('保存失败')
      resultMessage.value = '保存失败'
      resultType.value = 'error'
      resultDetail.value = response.data.error || response.data.result || '未知错误'
    }
  } catch (error) {
    console.error('保存失败:', error)
    ElMessage.error('保存失败: ' + (error.response?.data?.error || error.message))
    resultMessage.value = '保存失败'
    resultType.value = 'error'
    resultDetail.value = error.response?.data?.error || error.message || '未知错误'
  } finally {
    saving.value = false
  }
}

const handleValidate = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  validating.value = true
  clearResult()

  try {
    const response = await api.post(`/proxies/${currentProxyId.value}/validate_caddyfile/`)

    if (response.data.message) {
      ElMessage.success('验证成功')
      resultMessage.value = 'Caddyfile 配置验证通过'
      resultType.value = 'success'
      resultDetail.value = response.data.result || '配置文件语法正确，可以安全使用'
    } else {
      ElMessage.error('验证失败')
      resultMessage.value = 'Caddyfile 配置验证失败'
      resultType.value = 'error'
      resultDetail.value = response.data.error || response.data.result || '配置文件存在语法错误'
    }
  } catch (error) {
    console.error('验证失败:', error)
    ElMessage.error('验证失败: ' + (error.response?.data?.error || error.message))
    resultMessage.value = '验证失败'
    resultType.value = 'error'
    resultDetail.value = error.response?.data?.error || error.response?.data?.result || error.message || '验证过程出错'
  } finally {
    validating.value = false
  }
}

const handleReload = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  try {
    await ElMessageBox.confirm(
      '确定要重载 Caddy 服务吗？',
      '确认操作',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    reloading.value = true
    clearResult()

    const response = await api.post(`/proxies/${currentProxyId.value}/reload_caddy/`)

    if (response.data.message) {
      ElMessage.success('重载成功')
      resultMessage.value = 'Caddy 重载成功'
      resultType.value = 'success'
      resultDetail.value = response.data.result || 'Caddy 服务已重新加载配置'
    } else {
      ElMessage.error('重载失败')
      resultMessage.value = 'Caddy 重载失败'
      resultType.value = 'error'
      resultDetail.value = response.data.error || response.data.result || '重载过程出错'
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('重载失败:', error)
      ElMessage.error('重载失败: ' + (error.response?.data?.error || error.message))
      resultMessage.value = '重载失败'
      resultType.value = 'error'
      resultDetail.value = error.response?.data?.error || error.response?.data?.result || error.message || '重载过程出错'
    }
  } finally {
    reloading.value = false
  }
}

const handleRefresh = () => {
  loadCaddyfile()
}

const copyContent = () => {
  if (!content.value) {
    ElMessage.warning('没有内容可复制')
    return
  }
  navigator.clipboard.writeText(content.value).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const clearResult = () => {
  resultMessage.value = ''
  resultType.value = 'info'
  resultDetail.value = ''
}

onMounted(() => {
  fetchServers()
})
</script>

<style scoped>
.caddyfiles-page {
  height: calc(100vh - 60px - 0px); /* 减去 header 高度和 padding */
  display: flex;
  flex-direction: column;
  overflow: hidden;
  margin: -20px; /* 抵消 MainLayout 的 padding */
}

.content-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
  height: 0; /* 强制 flex 子元素使用剩余空间 */
}

/* 左侧服务器列表 */
.sidebar {
  width: 240px;
  background: #fff;
  border-right: 1px solid #dcdfe6;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid #dcdfe6;
  flex-shrink: 0;
}

.sidebar-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.server-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  min-height: 0;
  height: 0; /* 强制 flex 子元素使用剩余空间 */
}

.server-item {
  padding: 12px 14px;
  margin-bottom: 6px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid #e4e7ed;
  transition: all 0.2s;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.server-item:hover {
  background: #f5f7fa;
  border-color: #409eff;
}

.server-item.active {
  background: #ecf5ff;
  border-color: #409eff;
}

.server-name {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}

/* 中间编辑器区域 */
.editor-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  overflow: hidden;
  min-height: 0;
}

.editor-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  height: 0; /* 强制 flex 子元素使用剩余空间 */
}

.file-toolbar {
  background: #fff;
  border-bottom: 1px solid #dcdfe6;
  padding: 12px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: #606266;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.file-info .server-name {
  font-weight: 600;
  color: #303133;
}

.file-info .separator {
  color: #dcdfe6;
}

.file-info .file-path {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  color: #909399;
}

.file-info .update-time {
  color: #909399;
  font-size: 12px;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.editor-wrapper {
  flex: 1;
  overflow: hidden;
  background: #fff;
  min-height: 0;
  height: 0; /* 强制 flex 子元素使用剩余空间 */
  position: relative;
}

.code-editor {
  height: 100%;
  width: 100%;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
}

.code-editor :deep(.cm-editor) {
  height: 100% !important;
  max-height: 100% !important;
  overflow: hidden !important;
  display: flex !important;
  flex-direction: column !important;
}

.code-editor :deep(.cm-scroller) {
  font-size: 14px;
  line-height: 1.6;
  padding: 16px;
  overflow: auto !important;
  flex: 1 !important;
  min-height: 0 !important;
  max-height: 100% !important;
  height: 100% !important;
}

.code-editor :deep(.cm-content) {
  height: auto !important;
  min-height: 100% !important;
}

.code-editor :deep(.cm-gutters) {
  background: #fafafa;
  border-right: 1px solid #e4e7ed;
}

/* Caddyfile 语法高亮样式 */
.code-editor :deep(.cm-comment) {
  color: #6a737d;
  font-style: italic;
}

.code-editor :deep(.cm-keyword) {
  color: #d73a49;
  font-weight: 500;
}

.code-editor :deep(.cm-string) {
  color: #032f62;
}

.code-editor :deep(.cm-number) {
  color: #005cc5;
}

.code-editor :deep(.cm-bracket) {
  color: #e36209;
  font-weight: 600;
}

/* 右侧结果面板 */
.result-panel {
  width: 320px;
  background: #fff;
  border-left: 1px solid #dcdfe6;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.result-header {
  padding: 16px 20px;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.result-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.result-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  min-height: 0;
  height: 0; /* 强制 flex 子元素使用剩余空间 */
}

.result-display {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.result-detail {
  background: #f5f7fa;
  border-radius: 4px;
  padding: 12px;
}

.detail-header {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}

.detail-content {
  margin: 0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #606266;
  white-space: pre-wrap;
  word-wrap: break-word;
}
</style>
