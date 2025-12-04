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
              <div class="server-name">{{ currentServerName }}</div>
              <div class="file-path">/etc/caddy/Caddyfile</div>
            </div>
            <div class="toolbar-actions">
              <el-button type="primary" size="small" @click="handleSave" :loading="saving">
                保存
              </el-button>
              <el-button size="small" @click="handleShowHistory">
                历史
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

      <!-- 右侧：操作结果和证书管理 -->
      <div class="result-panel">
        <el-tabs v-model="rightPanelTab" class="panel-tabs">
          <!-- 操作结果标签页 -->
          <el-tab-pane label="操作结果" name="result">
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
          </el-tab-pane>

          <!-- 证书管理标签页 -->
          <el-tab-pane label="证书管理" name="certificates">
            <div class="certificates-header">
              <h3>证书管理</h3>
              <div class="header-actions">
                <el-input
                  v-model="certSearchText"
                  placeholder="搜索域名或路径..."
                  size="small"
                  style="width: 200px; margin-right: 8px;"
                  clearable
                  @input="handleCertSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-select
                  v-model="certFilterFormat"
                  placeholder="筛选格式"
                  size="small"
                  style="width: 120px; margin-right: 8px;"
                  clearable
                  @change="handleCertFilter"
                >
                  <el-option label="全部" value="" />
                  <el-option label="Caddyfile" value="caddyfile" />
                  <el-option label="数据库记录" value="database" />
                </el-select>
                <el-button
                  size="small"
                  type="primary"
                  @click="handleRefreshCertificates"
                  :loading="loadingCertificates"
                >
                  刷新
                </el-button>
              </div>
            </div>
            <div class="certificates-content">
              <div v-loading="loadingCertificates">
                <el-empty
                  v-if="filteredCertificates.length === 0 && !loadingCertificates"
                  :description="certificates.length === 0 ? '暂无证书配置' : '没有匹配的证书'"
                  :image-size="100"
                />
                <el-table
                  v-else
                  :data="filteredCertificates"
                  stripe
                  style="width: 100%"
                  :max-height="600"
                  size="small"
                >
                  <el-table-column prop="domain" label="域名" width="100" show-overflow-tooltip>
                    <template #default="{ row }">
                      <div style="display: flex; align-items: center; gap: 6px;">
                        <el-icon><Document /></el-icon>
                        <span>{{ row.domain || '未命名证书' }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column prop="cert_path" label="证书路径" show-overflow-tooltip>
                    <template #default="{ row }">
                      <code style="font-size: 11px;">{{ row.cert_path }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column prop="key_path" label="密钥路径" show-overflow-tooltip>
                    <template #default="{ row }">
                      <code style="font-size: 11px;">{{ row.key_path }}</code>
                    </template>
                  </el-table-column>
                  <el-table-column prop="format" label="来源" width="110" align="center">
                    <template #default="{ row }">
                      <el-tag
                        v-if="row.format"
                        size="small"
                        :type="row.format === 'database' ? 'warning' : 'info'"
                      >
                        {{ row.format === 'simple' ? '简单格式' : row.format === 'block' ? '块格式' : '数据库记录' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="line" label="行号" width="80" align="center">
                    <template #default="{ row }">
                      <span v-if="row.line !== null && row.line !== undefined" class="line-number">
                        {{ row.line }}
                      </span>
                      <el-tag v-else size="small" type="warning">未配置</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="150" align="center" fixed="right">
                    <template #default="{ row }">
                      <el-button
                        size="small"
                        type="primary"
                        @click="handleViewCertificate(row)"
                      >
                        查看/编辑
                      </el-button>
                      <el-button
                        v-if="row.format === 'database'"
                        size="small"
                        type="danger"
                        @click="handleDeleteCertificate(row)"
                      >
                        删除
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>

              <el-divider />

              <div class="upload-cert-section">
                <h4>上传新证书</h4>
                <el-form :model="certForm" label-width="100px" size="small">
                  <el-form-item label="域名（可选）">
                    <el-input
                      v-model="certForm.domain"
                      placeholder="example.com（可选，用于标识证书）"
                    />
                  </el-form-item>
                  <el-form-item label="证书路径">
                    <el-input
                      v-model="certForm.cert_path"
                      placeholder="/etc/caddy/ssl/cert.pem"
                    />
                  </el-form-item>
                  <el-form-item label="密钥路径">
                    <el-input
                      v-model="certForm.key_path"
                      placeholder="/etc/caddy/ssl/key.pem"
                    />
                  </el-form-item>
                  <el-form-item label="证书内容">
                    <el-input
                      v-model="certForm.cert_content"
                      type="textarea"
                      :rows="6"
                      placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                    />
                  </el-form-item>
                  <el-form-item label="密钥内容">
                    <el-input
                      v-model="certForm.key_content"
                      type="textarea"
                      :rows="6"
                      placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                    />
                  </el-form-item>
                  <el-form-item>
                    <el-button
                      type="primary"
                      @click="handleUploadCertificate"
                      :loading="uploadingCertificate"
                      :disabled="!certForm.cert_path || !certForm.key_path || !certForm.cert_content || !certForm.key_content"
                    >
                      上传证书
                    </el-button>
                    <el-button @click="resetCertForm">重置</el-button>
                  </el-form-item>
                </el-form>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <!-- Caddyfile历史版本对话框 -->
    <el-dialog
      v-model="historyDialogVisible"
      title="Caddyfile 历史版本"
      width="80%"
      :close-on-click-modal="false"
    >
      <div class="history-container">
        <div class="history-list">
          <el-table
            :data="historyList"
            stripe
            style="width: 100%"
            :max-height="400"
            size="small"
            v-loading="loadingHistory"
            @row-click="handleViewHistory"
          >
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="created_at" label="保存时间" width="180">
              <template #default="{ row }">
                {{ formatHistoryDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column prop="created_by" label="保存者" width="120" />
            <el-table-column prop="content" label="内容预览" show-overflow-tooltip>
              <template #default="{ row }">
                <code style="font-size: 11px;">{{ row.content.substring(0, 100) }}{{ row.content.length > 100 ? '...' : '' }}</code>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  @click.stop="handleViewHistory(row)"
                >
                  查看
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div v-if="viewingHistoryContent" class="history-content">
          <div class="history-content-header">
            <span>历史版本内容</span>
            <el-button
              size="small"
              type="primary"
              @click="handleRestoreHistory"
            >
              恢复此版本
            </el-button>
          </div>
          <div class="history-content-body">
            <pre><code>{{ viewingHistoryContent }}</code></pre>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="historyDialogVisible = false">关闭</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Caddyfile历史版本对话框 -->
    <el-dialog
      v-model="historyDialogVisible"
      title="Caddyfile 历史版本"
      width="90%"
      :close-on-click-modal="false"
    >
      <div class="history-container">
        <div class="history-list">
          <el-table
            :data="historyList"
            stripe
            style="width: 100%"
            :max-height="500"
            size="small"
            v-loading="loadingHistory"
            highlight-current-row
            @row-click="handleViewHistory"
          >
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="created_at" label="保存时间" width="180">
              <template #default="{ row }">
                {{ formatHistoryDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column prop="created_by" label="保存者" width="120" />
            <el-table-column prop="content" label="内容预览" show-overflow-tooltip>
              <template #default="{ row }">
                <code style="font-size: 11px;">{{ row.content.substring(0, 100) }}{{ row.content.length > 100 ? '...' : '' }}</code>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button
                  size="small"
                  type="primary"
                  @click.stop="handleViewHistory(row)"
                >
                  查看
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div v-if="viewingHistoryContent" class="history-content">
          <div class="history-content-header">
            <span>历史版本内容</span>
            <el-button
              size="small"
              type="primary"
              @click="handleRestoreHistory"
            >
              恢复此版本
            </el-button>
          </div>
          <div class="history-content-body">
            <pre><code>{{ viewingHistoryContent }}</code></pre>
          </div>
        </div>
      </div>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="historyDialogVisible = false">关闭</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 证书查看/编辑对话框 -->
    <el-dialog
      v-model="certDialogVisible"
      :title="editingCert ? '编辑证书' : '查看证书'"
      width="800px"
      :close-on-click-modal="false"
    >
      <el-form :model="editingCertForm" label-width="120px" v-loading="loadingCertContent">
        <el-form-item label="域名">
          <el-input v-model="editingCertForm.domain" disabled />
        </el-form-item>
        <el-form-item label="证书路径">
          <el-input v-model="editingCertForm.cert_path" />
        </el-form-item>
        <el-form-item label="密钥路径">
          <el-input v-model="editingCertForm.key_path" />
        </el-form-item>
        <el-form-item label="证书内容">
          <el-input
            v-model="editingCertForm.cert_content"
            type="textarea"
            :rows="10"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
            style="font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 12px;"
          />
        </el-form-item>
        <el-form-item label="密钥内容">
          <el-input
            v-model="editingCertForm.key_content"
            type="textarea"
            :rows="10"
            placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
            style="font-family: 'Consolas', 'Monaco', 'Courier New', monospace; font-size: 12px;"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="certDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            @click="handleUpdateCertificate"
            :loading="updatingCertificate"
            :disabled="!editingCertForm.cert_path || !editingCertForm.key_path || !editingCertForm.cert_content || !editingCertForm.key_content"
          >
            更新证书
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, Search } from '@element-plus/icons-vue'
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
const resultMessage = ref('')
const resultType = ref('info')
const resultDetail = ref('')
const useDarkTheme = ref(false)
const rightPanelTab = ref('result')
const certificates = ref([])
const loadingCertificates = ref(false)
const uploadingCertificate = ref(false)
const certForm = ref({
  domain: '',
  cert_path: '/etc/caddy/ssl/cert.pem',
  key_path: '/etc/caddy/ssl/key.pem',
  cert_content: '',
  key_content: '',
  remark: ''
})
const certDialogVisible = ref(false)
const editingCert = ref(null) // 当前正在编辑的证书对象
const editingCertForm = ref({
  domain: '',
  cert_path: '',
  key_path: '',
  cert_content: '',
  key_content: ''
})
const loadingCertContent = ref(false)
const updatingCertificate = ref(false)
const certSearchText = ref('')
const certFilterFormat = ref('')
const filteredCertificates = ref([])
const historyDialogVisible = ref(false)
const historyList = ref([])
const loadingHistory = ref(false)
const viewingHistoryContent = ref('')
const viewingHistoryId = ref(null)

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
  // loadCaddyfile 中已经处理了自动刷新证书列表的逻辑
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
    
    // 如果当前在证书管理标签页，自动刷新证书列表（不显示消息）
    if (rightPanelTab.value === 'certificates') {
      await handleRefreshCertificates(false)
    }
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
      ElMessage.success('保存成功，已自动备份历史版本')
      // 保存后重新加载文件以获取最新的修改时间
      await loadCaddyfile()
      resultMessage.value = '保存成功'
      resultType.value = 'success'
      resultDetail.value = response.data.result || '文件已成功保存到服务器，历史版本已备份'
    } else {
      // 这种情况不应该发生，因为成功时会有 message
      ElMessage.error('保存失败')
      resultMessage.value = '保存失败'
      resultType.value = 'error'
      resultDetail.value = response.data.error || response.data.result || '未知错误'
    }
  } catch (error) {
    console.error('保存失败:', error)
    const errorMsg = error.response?.data?.error || error.message || '未知错误'
    const isValidationFailed = error.response?.data?.validation_failed
    
    if (isValidationFailed) {
      ElMessage.error({
        message: '配置验证失败，文件未保存',
        duration: 5000,
        showClose: true
      })
      resultMessage.value = '配置验证失败'
      resultType.value = 'error'
      resultDetail.value = errorMsg
    } else {
      ElMessage.error('保存失败: ' + errorMsg)
      resultMessage.value = '保存失败'
      resultType.value = 'error'
      resultDetail.value = errorMsg
    }
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

const handleShowHistory = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  historyDialogVisible.value = true
  viewingHistoryContent.value = ''
  viewingHistoryId.value = null
  await fetchHistory()
}

const fetchHistory = async () => {
  if (!currentProxyId.value) return

  loadingHistory.value = true
  try {
    const response = await api.get(`/proxies/${currentProxyId.value}/list_caddyfile_history/`)
    historyList.value = response.data.results || []
  } catch (error) {
    console.error('获取历史版本失败:', error)
    ElMessage.error('获取历史版本失败: ' + (error.response?.data?.error || error.message))
    historyList.value = []
  } finally {
    loadingHistory.value = false
  }
}

const handleViewHistory = async (history) => {
  if (!currentProxyId.value) return

  try {
    const response = await api.get(`/proxies/${currentProxyId.value}/caddyfile_history/${history.id}/`)
    viewingHistoryContent.value = response.data.content || ''
    viewingHistoryId.value = history.id
  } catch (error) {
    console.error('获取历史版本内容失败:', error)
    ElMessage.error('获取历史版本内容失败: ' + (error.response?.data?.error || error.message))
  }
}

const handleRestoreHistoryDirect = async (history) => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要恢复此历史版本吗？\n保存时间：${formatHistoryDate(history.created_at)}\n\n当前编辑器中的内容将被替换，恢复后需要点击"保存"按钮应用更改。`,
      '确认恢复历史版本',
      {
        confirmButtonText: '确定恢复',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    // 获取完整的历史版本内容
    try {
      const response = await api.get(`/proxies/${currentProxyId.value}/caddyfile_history/${history.id}/`)
      content.value = response.data.content || ''
      historyDialogVisible.value = false
      ElMessage.success('历史版本已加载到编辑器，请点击"保存"按钮应用更改')
    } catch (error) {
      console.error('获取历史版本内容失败:', error)
      ElMessage.error('获取历史版本内容失败: ' + (error.response?.data?.error || error.message))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('恢复失败:', error)
    }
  }
}

const handleRestoreHistory = async () => {
  if (!viewingHistoryId.value || !viewingHistoryContent.value) {
    ElMessage.warning('请先选择一个历史版本')
    return
  }

  try {
    await ElMessageBox.confirm(
      '确定要恢复此历史版本吗？当前内容将被替换。',
      '确认恢复',
      {
        confirmButtonText: '确定恢复',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    content.value = viewingHistoryContent.value
    historyDialogVisible.value = false
    ElMessage.success('历史版本已加载到编辑器，请点击保存应用更改')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('恢复失败:', error)
    }
  }
}

const formatHistoryDate = (dateString) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const clearResult = () => {
  resultMessage.value = ''
  resultType.value = 'info'
  resultDetail.value = ''
}

const handleRefreshCertificates = async (showMessage = true) => {
  if (!currentProxyId.value) {
    if (showMessage) {
      ElMessage.warning('请先选择服务器')
    }
    return
  }

  loadingCertificates.value = true
  try {
    const response = await api.get(`/proxies/${currentProxyId.value}/list_certificates/`)
    certificates.value = response.data.certificates || []
    applyCertFilters() // 应用过滤
    if (showMessage) {
      if (certificates.value.length === 0) {
        ElMessage.info('未找到证书配置')
      } else {
        ElMessage.success(`找到 ${certificates.value.length} 个证书配置`)
      }
    }
  } catch (error) {
    console.error('获取证书列表失败:', error)
    if (showMessage) {
      ElMessage.error('获取证书列表失败: ' + (error.response?.data?.error || error.message))
    }
    certificates.value = []
    filteredCertificates.value = []
  } finally {
    loadingCertificates.value = false
  }
}

const applyCertFilters = () => {
  let filtered = [...certificates.value]
  
  // 搜索过滤
  if (certSearchText.value) {
    const searchLower = certSearchText.value.toLowerCase()
    filtered = filtered.filter(cert => {
      const domain = (cert.domain || '').toLowerCase()
      const certPath = (cert.cert_path || '').toLowerCase()
      const keyPath = (cert.key_path || '').toLowerCase()
      return domain.includes(searchLower) || certPath.includes(searchLower) || keyPath.includes(searchLower)
    })
  }
  
  // 格式过滤
  if (certFilterFormat.value) {
    if (certFilterFormat.value === 'caddyfile') {
      filtered = filtered.filter(cert => cert.format === 'simple' || cert.format === 'block')
    } else if (certFilterFormat.value === 'database') {
      filtered = filtered.filter(cert => cert.format === 'database')
    }
  }
  
  filteredCertificates.value = filtered
}

const handleCertSearch = () => {
  applyCertFilters()
}

const handleCertFilter = () => {
  applyCertFilters()
}

const handleUploadCertificate = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  if (!certForm.value.cert_path || !certForm.value.key_path) {
    ElMessage.warning('请填写证书路径和密钥路径')
    return
  }

  if (!certForm.value.cert_content || !certForm.value.key_content) {
    ElMessage.warning('请填写证书内容和密钥内容')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要上传证书到以下路径吗？\n证书: ${certForm.value.cert_path}\n密钥: ${certForm.value.key_path}`,
      '确认上传证书',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    uploadingCertificate.value = true

    const response = await api.post(`/proxies/${currentProxyId.value}/upload_certificate/`, {
      domain: certForm.value.domain,
      cert_path: certForm.value.cert_path,
      key_path: certForm.value.key_path,
      cert_content: certForm.value.cert_content,
      key_content: certForm.value.key_content,
      remark: certForm.value.remark
    })

    if (response.data.message) {
      ElMessage.success('证书上传成功')
      resetCertForm()
      // 刷新证书列表
      await handleRefreshCertificates()
    } else {
      ElMessage.error('证书上传失败: ' + (response.data.error || '未知错误'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('上传证书失败:', error)
      ElMessage.error('上传证书失败: ' + (error.response?.data?.error || error.message))
    }
  } finally {
    uploadingCertificate.value = false
  }
}

const resetCertForm = () => {
  certForm.value = {
    domain: '',
    cert_path: '/etc/caddy/ssl/cert.pem',
    key_path: '/etc/caddy/ssl/key.pem',
    cert_content: '',
    key_content: '',
    remark: ''
  }
}

const handleDeleteCertificate = async (cert) => {
  if (!cert.id) {
    ElMessage.warning('无法删除：该证书不是数据库中的记录')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要删除证书 "${cert.domain || cert.cert_path}" 吗？\n\n此操作只会删除数据库记录，不会删除服务器上的证书文件。`,
      '确认删除证书',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    const response = await api.delete(`/proxies/${currentProxyId.value}/certificates/${cert.id}/delete_record/`)
    
    if (response.status === 204 || response.data?.message) {
      ElMessage.success('证书记录已删除')
      await handleRefreshCertificates(false)
    } else {
      ElMessage.error('删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除证书失败:', error)
      ElMessage.error('删除证书失败: ' + (error.response?.data?.error || error.message))
    }
  }
}

const handleViewCertificate = async (cert) => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  editingCert.value = cert
  editingCertForm.value = {
    domain: cert.domain || '',
    cert_path: cert.cert_path || '',
    key_path: cert.key_path || '',
    cert_content: '',
    key_content: ''
  }

  certDialogVisible.value = true
  loadingCertContent.value = true

  try {
    // 读取证书和密钥内容（使用 GET 方法）
    const response = await api.get(`/proxies/${currentProxyId.value}/get_certificate/`, {
      params: {
        cert_path: cert.cert_path,
        key_path: cert.key_path
      }
    })

    if (response.data.cert_content) {
      editingCertForm.value.cert_content = response.data.cert_content
    }
    if (response.data.key_content) {
      editingCertForm.value.key_content = response.data.key_content
    }
  } catch (error) {
    console.error('读取证书内容失败:', error)
    ElMessage.warning('读取证书内容失败: ' + (error.response?.data?.error || error.message))
    // 即使读取失败，也允许用户手动输入
  } finally {
    loadingCertContent.value = false
  }
}

const handleUpdateCertificate = async () => {
  if (!currentProxyId.value) {
    ElMessage.warning('请先选择服务器')
    return
  }

  if (!editingCertForm.value.cert_path || !editingCertForm.value.key_path) {
    ElMessage.warning('请填写证书路径和密钥路径')
    return
  }

  if (!editingCertForm.value.cert_content || !editingCertForm.value.key_content) {
    ElMessage.warning('请填写证书内容和密钥内容')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要更新证书吗？\n证书: ${editingCertForm.value.cert_path}\n密钥: ${editingCertForm.value.key_path}`,
      '确认更新证书',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )

    updatingCertificate.value = true

    const response = await api.post(`/proxies/${currentProxyId.value}/upload_certificate/`, {
      domain: editingCertForm.value.domain,
      cert_path: editingCertForm.value.cert_path,
      key_path: editingCertForm.value.key_path,
      cert_content: editingCertForm.value.cert_content,
      key_content: editingCertForm.value.key_content,
      remark: editingCertForm.value.remark || ''
    })

    if (response.data.message) {
      ElMessage.success('证书更新成功')
      certDialogVisible.value = false
      // 刷新证书列表
      await handleRefreshCertificates()
    } else {
      ElMessage.error('证书更新失败: ' + (response.data.error || '未知错误'))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('更新证书失败:', error)
      ElMessage.error('更新证书失败: ' + (error.response?.data?.error || error.message))
    }
  } finally {
    updatingCertificate.value = false
  }
}

// 当选择服务器时，自动刷新证书列表
watch(selectedServerId, () => {
  if (selectedServerId.value && rightPanelTab.value === 'certificates') {
    // 延迟执行，等待 loadCaddyfile 完成并设置 currentProxyId
    setTimeout(() => {
      if (currentProxyId.value) {
        handleRefreshCertificates(false) // 自动刷新时不显示消息
      }
    }, 500)
  }
})

// 当切换到证书管理标签页时，自动刷新证书列表
watch(rightPanelTab, (newTab) => {
  if (newTab === 'certificates' && selectedServerId.value && currentProxyId.value) {
    handleRefreshCertificates(false) // 自动刷新时不显示消息
  }
})

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
  width: 250px;
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
  /* width: 600px; */
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  overflow: hidden;
  min-height: 0;
  flex-shrink: 0;
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
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: #606266;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.file-info .server-name {
  font-weight: 600;
  color: #303133;
  font-size: 14px;
}

.file-info .file-path {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
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
  width: 700px;
  background: #fff;
  border-left: 1px solid #dcdfe6;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
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

/* 标签页样式 */
.panel-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.panel-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 20px;
  border-bottom: 1px solid #dcdfe6;
  flex-shrink: 0;
}

.panel-tabs :deep(.el-tabs__content) {
  flex: 1;
  overflow: hidden;
  min-height: 0;
  height: 0;
}

.panel-tabs :deep(.el-tab-pane) {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 证书管理样式 */
.certificates-header {
  padding: 16px 20px;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.certificates-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.certificates-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  min-height: 0;
  height: 0;
}

/* 证书表格样式优化 */
.certificates-content :deep(.el-table) {
  font-size: 13px;
}

.certificates-content :deep(.el-table code) {
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 11px;
  color: #606266;
}

.certificates-content :deep(.el-table .line-number) {
  color: #409eff;
  font-weight: 500;
}

.line-number {
  color: #409eff;
  font-weight: 500;
}

.cert-actions {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e4e7ed;
}

.upload-cert-section {
  margin-top: 16px;
}

.upload-cert-section h4 {
  margin: 0 0 16px 0;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.upload-cert-section :deep(.el-form-item) {
  margin-bottom: 16px;
}

.upload-cert-section :deep(.el-textarea__inner) {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
}

/* 历史版本对话框样式 */
.history-container {
  display: flex;
  gap: 20px;
  min-height: 400px;
}

.history-list {
  flex: 1;
  min-width: 0;
}

.history-content {
  width: 500px;
  display: flex;
  flex-direction: column;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}

.history-content-header {
  padding: 12px 16px;
  background: #f5f7fa;
  border-bottom: 1px solid #dcdfe6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  font-size: 14px;
}

.history-content-body {
  flex: 1;
  overflow: auto;
  padding: 16px;
  background: #fff;
  max-height: 500px;
}

.history-content-body pre {
  margin: 0;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.history-content-body code {
  color: #303133;
}
</style>
