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
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <div class="action-row">
                <el-button 
                  size="small" 
                  :type="testSuccessMap[row.id] ? 'success' : 'warning'"
                  @click="handleTest(row)" 
                  :loading="testingServerId === row.id"
                  :disabled="testingServerId === row.id"
                >
                  {{ testSuccessMap[row.id] ? '连接成功' : '测试连接' }}
                </el-button>
                <el-button 
                  size="small" 
                  type="success" 
                  @click="handleInstallAgent(row)"
                  :loading="installingAgentId === row.id"
                  :disabled="installingAgentId === row.id"
                >
                  {{ row.has_agent ? '升级Agent' : '安装Agent' }}
                </el-button>
              </div>
              <div class="action-row">
                <el-button 
                  size="small" 
                  type="info" 
                  @click="handleViewAgentLogs(row)"
                  :disabled="!row.has_agent"
                >
                  查看日志
                </el-button>
                <el-button size="small" type="primary" @click="handleEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 删除确认对话框 -->
    <el-dialog
      v-model="deleteDialogVisible"
      title="删除服务器确认"
      width="600px"
    >
      <div v-if="deleteServerInfo">
        <div style="margin-bottom: 20px;">
          确定要删除服务器 <strong>"{{ deleteServerInfo.name }}"</strong> ({{ deleteServerInfo.host }}) 吗？
        </div>
        
        <div v-if="deleteRelatedInfo?.has_agent" style="margin-bottom: 15px;">
          <div style="font-weight: bold; margin-bottom: 8px;">⚠️ 该服务器关联了 Agent：</div>
          <div style="margin-left: 20px; margin-bottom: 10px;">
            <div>Agent ID: {{ deleteRelatedInfo.agent.id }}</div>
            <div>Token: {{ deleteRelatedInfo.agent.token }}</div>
            <div>状态: {{ deleteRelatedInfo.agent.status }}</div>
            <div v-if="deleteRelatedInfo.agent.version">版本: {{ deleteRelatedInfo.agent.version }}</div>
            <div v-if="deleteRelatedInfo.agent.rpc_port">RPC端口: {{ deleteRelatedInfo.agent.rpc_port }}</div>
          </div>
        </div>
        
        <div v-if="deleteRelatedInfo?.has_proxies" style="margin-bottom: 15px;">
          <div style="font-weight: bold; margin-bottom: 8px;">⚠️ 该服务器关联了 {{ deleteRelatedInfo.proxies_count }} 个代理节点：</div>
          <div style="margin-left: 20px; max-height: 150px; overflow-y: auto; margin-bottom: 10px;">
            <div v-for="(proxy, index) in deleteRelatedInfo.proxies" :key="index">
              {{ index + 1 }}. {{ proxy.name }} ({{ proxy.protocol }}, 端口: {{ proxy.port }})
            </div>
            <div v-if="deleteRelatedInfo.proxies_count > deleteRelatedInfo.proxies.length">
              ... 还有 {{ deleteRelatedInfo.proxies_count - deleteRelatedInfo.proxies.length }} 个代理节点
            </div>
          </div>
        </div>
        
        <div style="margin-top: 20px; padding: 15px; background-color: #f5f7fa; border-radius: 4px;">
          <div style="font-weight: bold; margin-bottom: 12px; color: #303133;">选择删除选项：</div>
          <el-checkbox v-model="deleteAgentChecked" v-if="deleteRelatedInfo?.has_agent" style="display: block; margin-bottom: 10px;">
            同时删除关联的 Agent
          </el-checkbox>
          <el-checkbox v-model="deleteProxiesChecked" v-if="deleteRelatedInfo?.has_proxies" style="display: block; margin-bottom: 10px;">
            同时删除关联的代理节点 ({{ deleteRelatedInfo.proxies_count }} 个)
          </el-checkbox>
          <div style="margin-top: 12px; color: #909399; font-size: 12px; line-height: 1.5;">
            注意：由于外键约束，如果不选择删除关联对象，它们也会在删除服务器时被自动删除。
          </div>
        </div>
      </div>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="deleteDialogVisible = false">取消</el-button>
          <el-button type="danger" @click="confirmDelete" :loading="deleting">确定删除</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="800px"
      @close="resetForm"
      class="server-dialog"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="90px"
        class="server-form"
      >
        <!-- 基础信息 -->
        <el-divider content-position="left" class="first-divider">基础信息</el-divider>
        <div class="form-row-two-cols">
          <el-form-item label="SSH端口" prop="port">
            <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%;" />
        </el-form-item>
          <el-form-item label="服务器名" prop="name">
            <el-input 
              v-model="form.name" 
              placeholder="留空自动生成" 
              @blur="handleNameBlur"
            />
            <div v-if="autoGeneratingName" style="font-size: 12px; color: #909399; margin-top: 4px;">
              <el-icon class="is-loading"><Loading /></el-icon> 正在自动生成服务器名...
            </div>
          </el-form-item>
        </div>
        <div class="form-row-two-cols">
        <el-form-item label="主机地址" prop="host">
            <el-input 
              v-model="form.host" 
              placeholder="IP或域名" 
              @blur="handleHostBlur"
            />
        </el-form-item>
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" placeholder="SSH用户名" />
        </el-form-item>
        </div>

        <!-- SSH认证 -->
        <el-divider content-position="left">SSH认证</el-divider>
        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="SSH密码（或使用私钥）"
            show-password
          />
        </el-form-item>
        <el-form-item label="SSH Key">
          <div style="display: flex; align-items: center; gap: 8px;">
          <el-switch
            v-model="form.enable_ssh_key"
          />
            <span style="font-size: 13px; color: #909399;">自动生成并添加到服务器</span>
          </div>
        </el-form-item>
        <el-form-item label="保存密码">
            <div style="display: flex; align-items: center; gap: 8px;">
          <el-switch
            v-model="form.save_password"
          />
              <span style="font-size: 13px; color: #909399;">开启后加密保存</span>
            </div>
          </el-form-item>
          <el-form-item label="自动清除密码">
            <div style="display: flex; align-items: center; gap: 8px;">
          <el-switch
            v-model="form.auto_clear_password_after_agent_install"
          />
              <span style="font-size: 13px; color: #909399;">安装agent后自动清除密码</span>
            </div>
          </el-form-item>
        <el-form-item label="私钥" prop="private_key">
          <el-input
            v-model="form.private_key"
            type="textarea"
            :rows="2"
            placeholder="SSH私钥内容（可选）"
          />
        </el-form-item>

        <!-- 连接配置 -->
        <el-divider content-position="left">连接配置</el-divider>
        <div class="form-row-two-cols">
        <el-form-item label="连接方式" prop="connection_method">
            <el-select v-model="form.connection_method" placeholder="连接方式" style="width: 100%">
            <el-option label="SSH" value="ssh" />
            <el-option label="Agent" value="agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="部署目标" prop="deployment_target">
            <el-select v-model="form.deployment_target" placeholder="部署目标" style="width: 100%">
            <el-option label="宿主机" value="host" />
            <el-option label="Docker" value="docker" />
          </el-select>
        </el-form-item>
        </div>

        <!-- Agent高级选项（直接显示在连接配置下） -->
        <div v-if="form.connection_method === 'agent'" class="form-row-two-cols">
          <el-form-item label="连接地址" prop="agent_connect_host">
          <el-input 
            v-model="form.agent_connect_host" 
              placeholder="agent.example.com（可选）"
              @change="handleAgentConnectHostChange"
          />
        </el-form-item>
          <el-form-item label="连接端口" prop="agent_connect_port">
          <el-input-number 
            v-model="form.agent_connect_port" 
            :min="1" 
            :max="65535" 
              placeholder="默认"
              style="width: 100%;"
          />
        </el-form-item>
        </div>

        <!-- 重要提示 -->
        <el-alert
          v-if="form.save_password"
          title="建议开启密码保存以确保Agent部署成功。未开启则部署完成后自动删除。"
          type="warning"
          :closable="false"
          style="margin-top: 12px;"
        />
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

    <!-- Agent日志对话框 -->
    <el-dialog
      v-model="agentLogDialogVisible"
      title="Agent日志"
      width="80%"
      @close="stopAgentLogRefresh"
    >
      <div style="position: relative;">
        <!-- 大的loading遮罩（仅在手动刷新时显示） -->
        <div v-if="loadingAgentLogs && !autoRefreshLogs && isFirstLoad" class="log-loading-overlay">
          <el-icon class="is-loading" style="font-size: 64px; color: #409EFF;">
            <Loading />
          </el-icon>
          <div style="margin-top: 20px; font-size: 18px; color: #409EFF; font-weight: 500;">正在加载日志...</div>
        </div>
        
        <div style="margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <el-switch
              v-model="autoRefreshLogs"
              active-text="自动刷新"
              inactive-text="手动刷新"
              @change="handleAutoRefreshChange"
            />
            <el-select
              v-model="logSortOrder"
              size="small"
              style="width: 120px"
              @change="handleSortOrderChange"
            >
              <el-option label="最新在前" value="desc" />
              <el-option label="最久在前" value="asc" />
            </el-select>
            <el-select
              v-model="logLines"
              size="small"
              style="width: 120px"
              @change="handleLogLinesChange"
            >
              <el-option label="50行" :value="50" />
              <el-option label="100行" :value="100" />
              <el-option label="200行" :value="200" />
              <el-option label="500行" :value="500" />
              <el-option label="1000行" :value="1000" />
            </el-select>
            <el-button
              size="small"
              type="primary"
              @click="copyLogs"
              :icon="CopyDocument"
            >
              复制日志
            </el-button>
          </div>
          <span v-if="autoRefreshLogs" style="color: #909399; font-size: 12px;">
            <el-icon v-if="loadingAgentLogs" class="is-loading" style="margin-right: 5px;"><Loading /></el-icon>
            每3秒自动刷新
          </span>
        </div>
        
        <el-tabs v-model="activeLogTab">
          <el-tab-pane label="Agent日志" name="agent">
            <el-scrollbar height="500px" ref="agentLogScrollbar">
              <pre style="margin: 0; padding: 10px; background: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', monospace; white-space: pre-wrap; word-wrap: break-word;">{{ sortedAgentLog || '暂无日志' }}</pre>
            </el-scrollbar>
          </el-tab-pane>
          <el-tab-pane label="Systemd状态" name="systemd">
            <el-scrollbar height="500px" ref="systemdLogScrollbar">
              <pre style="margin: 0; padding: 10px; background: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', monospace; white-space: pre-wrap; word-wrap: break-word;">{{ agentLogs.systemd_status || '暂无状态信息' }}</pre>
            </el-scrollbar>
          </el-tab-pane>
          <el-tab-pane label="Journalctl日志" name="journalctl">
            <el-scrollbar height="500px" ref="journalctlLogScrollbar">
              <pre style="margin: 0; padding: 10px; background: #1e1e1e; color: #d4d4d4; font-family: 'Courier New', monospace; white-space: pre-wrap; word-wrap: break-word;">{{ sortedJournalctlLog || '暂无日志' }}</pre>
            </el-scrollbar>
          </el-tab-pane>
        </el-tabs>
        
        <div v-if="agentLogs.error" style="margin-top: 10px; color: #f56c6c;">
          <el-alert :title="agentLogs.error" type="error" :closable="false" />
        </div>
      </div>
      
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="refreshAgentLogs(true)" :loading="loadingAgentLogs">刷新</el-button>
          <el-button type="primary" @click="agentLogDialogVisible = false">关闭</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, h } from 'vue'
import { ElMessage, ElMessageBox, ElCheckbox } from 'element-plus'
import { Connection, Check, CopyDocument, Loading } from '@element-plus/icons-vue'
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
const deleteDialogVisible = ref(false) // 删除确认对话框显示状态
const deleteServerInfo = ref(null) // 要删除的服务器信息
const deleteRelatedInfo = ref(null) // 关联对象信息
const deleteAgentChecked = ref(false) // 是否删除 Agent
const deleteProxiesChecked = ref(false) // 是否删除代理节点
const deleting = ref(false) // 删除中状态
const installingAgentId = ref(null) // 正在安装Agent的服务器ID
const agentLogDialogVisible = ref(false) // Agent日志对话框显示状态
const agentLogs = ref({
  agent_log: '',
  systemd_status: '',
  journalctl_log: '',
  agent_log_offset: 0,
  systemd_offset: 0,
  journalctl_offset: 0,
  error: null
}) // Agent日志内容
const currentServerId = ref(null) // 当前查看日志的服务器ID
const loadingAgentLogs = ref(false) // 加载Agent日志中
const agentLogRefreshInterval = ref(null) // Agent日志刷新定时器
const autoRefreshLogs = ref(false) // 是否自动刷新日志（默认关闭）
const isFirstLoad = ref(true) // 是否是首次加载
const logSortOrder = ref('desc') // 日志排序顺序：'desc'=最新在前，'asc'=最久在前
const logLines = ref(200) // 日志显示行数，默认200行

const form = reactive({
  name: '',
  host: '',
  port: 22,
  username: '',
  save_password: true,  // 默认勾选保存密码
  auto_clear_password_after_agent_install: true,  // 默认开启：安装agent后自动清除密码
  enable_ssh_key: false,
  password: '',
  private_key: '',
  connection_method: 'agent',  // 默认使用Agent连接方式
  deployment_target: 'host',
  agent_connect_host: '',
  agent_connect_port: null
})

const rules = {
  name: [], // 服务器名改为可选，自动生成
  host: [{ required: true, message: '请输入主机地址', trigger: 'blur' }],
  port: [{ required: true, message: '请输入SSH端口', trigger: 'blur' }],
  username: [{ required: true, message: '请输入SSH用户名', trigger: 'blur' }]
}

const autoGeneratingName = ref(false)

// 获取IP地理位置信息（使用多个API作为备用）
const getIPGeoInfo = async (ip) => {
  console.log('[IP地理位置] 开始获取IP地理位置信息:', ip)
  
  // API列表（按优先级排序）
  const apis = [
    {
      name: 'freeipapi',
      url: `https://free.freeipapi.com/api/json/${ip}`,
      parser: (data) => {
        if (data && data.countryCode) {
          return {
            country: data.countryName || data.country,
            countryCode: data.countryCode.toLowerCase(),
            ip: data.ip || ip
          }
        }
        return null
      }
    },
    {
      name: 'ipinfo',
      url: `https://ipinfo.io/${ip}/json`,
      parser: (data) => {
        if (data && data.country) {
          return {
            country: data.country_name || data.country,
            countryCode: data.country.toLowerCase(),
            ip: data.ip || ip
          }
        }
        return null
      }
    },
    {
      name: 'ip-api',
      url: `http://ip-api.com/json/${ip}?fields=status,country,countryCode,query`,
      parser: (data) => {
        if (data && data.status === 'success') {
          return {
            country: data.country,
            countryCode: data.countryCode.toLowerCase(),
            ip: data.query || ip
          }
        }
        return null
      }
    }
  ]

  // 依次尝试每个API
  for (const api of apis) {
    try {
      console.log(`[IP地理位置] 尝试API: ${api.name}, URL: ${api.url}`)
      const response = await fetch(api.url, {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        }
      })
      
      console.log(`[IP地理位置] API ${api.name} 响应状态:`, response.status, response.statusText)
      
      if (!response.ok) {
        console.warn(`[IP地理位置] API ${api.name} 请求失败，状态码:`, response.status)
        continue // 如果请求失败，尝试下一个API
      }
      
      const data = await response.json()
      console.log(`[IP地理位置] API ${api.name} 返回数据:`, data)
      
      const result = api.parser(data)
      console.log(`[IP地理位置] API ${api.name} 解析结果:`, result)
      
      if (result) {
        console.log(`[IP地理位置] 成功获取地理位置信息，使用API: ${api.name}`, result)
        return result
      } else {
        console.warn(`[IP地理位置] API ${api.name} 解析结果为空，尝试下一个API`)
      }
    } catch (error) {
      console.warn(`[IP地理位置] API ${api.name} 请求异常:`, error)
      continue // 继续尝试下一个API
    }
  }
  
  // 所有API都失败
  console.error('[IP地理位置] 所有API都请求失败，无法获取地理位置信息')
  return null
}

// 国家代码到国旗emoji的映射
const countryFlags = {
  'us': '🇺🇸',
  'cn': '🇨🇳',
  'jp': '🇯🇵',
  'kr': '🇰🇷',
  'gb': '🇬🇧',
  'de': '🇩🇪',
  'fr': '🇫🇷',
  'ca': '🇨🇦',
  'au': '🇦🇺',
  'ru': '🇷🇺',
  'in': '🇮🇳',
  'br': '🇧🇷',
  'mx': '🇲🇽',
  'es': '🇪🇸',
  'it': '🇮🇹',
  'nl': '🇳🇱',
  'sg': '🇸🇬',
  'hk': '🇭🇰',
  'tw': '🇹🇼',
}

// 自动生成服务器名
const generateServerName = async (forceGenerate = false) => {
  console.log('[生成服务器名] 开始生成，form.host:', form.host, 'form.name:', form.name, 'editingId:', editingId.value, 'forceGenerate:', forceGenerate)
  
  // 如果主机地址为空，无法生成
  if (!form.host) {
    console.log('[生成服务器名] 跳过：主机地址为空')
    return
  }
  
  // 如果不是强制生成，且已有服务器名，不自动生成
  if (!forceGenerate && form.name) {
    console.log('[生成服务器名] 跳过：已有服务器名且不是强制生成')
    return
  }

  autoGeneratingName.value = true
  
  try {
    // 确定使用的地址（优先使用agent_connect_host，否则使用host）
    const address = form.agent_connect_host || form.host
    console.log('[生成服务器名] 使用的地址:', address, 'agent_connect_host:', form.agent_connect_host, 'host:', form.host)
    
    // 判断是否是IP地址（IPv4）
    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/
    const isIP = ipRegex.test(address)
    console.log('[生成服务器名] 是否为IP地址:', isIP)
    
    // 如果不是IP地址（域名），直接使用地址
    if (!isIP) {
      console.log('[生成服务器名] 不是IP地址，直接使用地址:', address)
      form.name = address
      autoGeneratingName.value = false
      return
    }
    
    // 只有IP地址才获取地理位置信息
    console.log('[生成服务器名] 开始获取IP地理位置信息:', address)
    let countryCode = null
    let countryFlag = ''
    
    const geoInfo = await getIPGeoInfo(address)
    console.log('[生成服务器名] 地理位置信息:', geoInfo)
    
    if (geoInfo && geoInfo.countryCode) {
      countryCode = geoInfo.countryCode
      countryFlag = countryFlags[countryCode] || ''
      console.log('[生成服务器名] 国家代码:', countryCode, '国旗:', countryFlag)
    } else {
      console.log('[生成服务器名] 无法获取地理位置信息')
    }
    
    // 生成服务器名（按照规则）
    let serverName = ''
    
    if (countryCode === 'us' && countryFlag) {
      // 美国：🇺🇸 us | 地址
      serverName = `${countryFlag} us | ${address}`
      console.log('[生成服务器名] 规则：美国，生成:', serverName)
    } else if (countryCode && countryFlag) {
      // 其他有国旗的国家：国旗 国家代码 | 地址
      serverName = `${countryFlag} ${countryCode} | ${address}`
      console.log('[生成服务器名] 规则：其他有国旗的国家，生成:', serverName)
    } else if (countryCode) {
      // 有国家代码但无国旗：国家代码 | 地址
      serverName = `${countryCode} | ${address}`
      console.log('[生成服务器名] 规则：有国家代码但无国旗，生成:', serverName)
    } else {
      // 无法获取地理位置：直接使用地址
      serverName = address
      console.log('[生成服务器名] 规则：无法获取地理位置，直接使用地址:', serverName)
    }
    
    form.name = serverName
    console.log('[生成服务器名] 最终生成的服务器名:', form.name)
  } catch (error) {
    console.error('[生成服务器名] 生成失败:', error)
    // 如果生成失败，直接使用地址
    form.name = form.agent_connect_host || form.host
    console.log('[生成服务器名] 失败后使用默认名称:', form.name)
  } finally {
    autoGeneratingName.value = false
  }
}

// 处理主机地址失焦事件
const handleHostBlur = async () => {
  console.log('[主机地址失焦] editingId:', editingId.value, 'form.name:', form.name, 'form.host:', form.host)
  
  // 如果服务器名为空，自动生成（编辑模式和新建模式都支持）
  if (!form.name && form.host) {
    console.log('[主机地址失焦] 服务器名为空，开始自动生成（强制生成）')
    await generateServerName(true) // 强制生成
  } else {
    console.log('[主机地址失焦] 服务器名不为空或主机地址为空，不自动生成')
  }
}

// 处理Agent连接地址变化
const handleAgentConnectHostChange = async () => {
  console.log('[Agent连接地址变化] editingId:', editingId.value, 'form.name:', form.name, 'form.agent_connect_host:', form.agent_connect_host)
  
  // 如果服务器名为空，或者是自动生成的格式，重新生成（编辑模式和新建模式都支持）
  if (!form.name || form.name === form.host || form.name.match(/^[🇺🇸🇨🇳🇯🇵🇰🇷🇬🇧🇩🇪🇫🇷🇨🇦🇦🇺🇷🇺🇮🇳🇧🇷🇲🇽🇪🇸🇮🇹🇳🇱🇸🇬🇭🇰🇹🇼]/) || form.name.includes(' | ')) {
    console.log('[Agent连接地址变化] 需要重新生成服务器名（强制生成）')
    await generateServerName(true) // 强制生成
  } else {
    console.log('[Agent连接地址变化] 不需要重新生成服务器名')
  }
}

// 处理服务器名失焦事件
const handleNameBlur = () => {
  console.log('[服务器名失焦] editingId:', editingId.value, 'form.name:', form.name, 'form.host:', form.host)
  
  // 如果用户清空了服务器名，自动生成（编辑模式和新建模式都支持）
  if (!form.name && form.host) {
    console.log('[服务器名失焦] 服务器名为空，开始自动生成（强制生成）')
    generateServerName(true) // 强制生成
  } else {
    console.log('[服务器名失焦] 服务器名不为空或主机地址为空，不自动生成')
  }
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
  // 先重置表单，再打开对话框
  resetForm()
  // 使用 nextTick 确保表单重置完成后再打开对话框
  setTimeout(() => {
  dialogVisible.value = true
  }, 0)
}

const handleEdit = (row) => {
  console.log('[编辑服务器] 开始编辑，服务器信息:', row)
  dialogTitle.value = '编辑服务器'
  editingId.value = row.id
  Object.assign(form, {
    name: row.name,
    host: row.host,
    port: row.port,
    username: row.username,
    password: '',
    private_key: '',
    save_password: row.save_password || false,
    auto_clear_password_after_agent_install: row.auto_clear_password_after_agent_install !== undefined ? row.auto_clear_password_after_agent_install : true,  // 默认开启
    enable_ssh_key: row.enable_ssh_key || false,
    connection_method: row.connection_method || 'agent',  // 默认使用Agent连接方式
    deployment_target: row.deployment_target || 'host',
    agent_connect_host: row.agent_connect_host || '',
    agent_connect_port: row.agent_connect_port || null
  })
  console.log('[编辑服务器] 表单数据已填充:', form)
  dialogTestSuccess.value = false // 重置测试状态
  dialogVisible.value = true
}

const handleInstallAgent = async (row) => {
  if (installingAgentId.value === row.id) return // 防止重复点击
  
  // 确认安装/升级
  const isUpgrade = row.has_agent
  
  // 升级时强制要求SSH凭证
  if (isUpgrade && !row.has_password && !row.has_private_key) {
    // 升级时需要SSH凭证，提示用户去编辑服务器
    try {
      await ElMessageBox.confirm(
        '升级Agent需要使用SSH方式，该服务器缺少SSH密码或私钥。\n\n请先编辑服务器并输入SSH凭证，然后再进行升级。',
        '需要SSH凭证',
        {
          confirmButtonText: '去编辑',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
      // 用户确认，打开编辑对话框
      handleEdit(row)
      return
    } catch {
      // 用户取消
      return
    }
  } else if (!isUpgrade && !row.has_password && !row.has_private_key) {
    // 安装时也需要SSH凭证
    ElMessageBox.confirm(
      '该服务器缺少SSH密码或私钥，无法安装Agent。是否现在编辑服务器并输入SSH凭证？',
      '缺少SSH凭证',
      {
        confirmButtonText: '去编辑',
        cancelButtonText: '取消',
        type: 'warning'
      }
    ).then(() => {
      handleEdit(row)
    }).catch(() => {})
    return
  }
  try {
    if (isUpgrade) {
      await ElMessageBox.confirm(
        '',
        '确认升级Agent',
        {
          confirmButtonText: '确定升级',
          cancelButtonText: '取消',
          type: 'info',
          message: `
            <div>
              <p style="margin-bottom: 10px;">确定要升级服务器 "<strong>${row.name}</strong>" 上的Agent到最新版本吗？</p>

              <p style="margin: 10px 0; font-weight: bold;">升级将：</p>
              <ul style="margin: 5px 0 10px 20px;">
                <li>停止现有Agent服务</li>
                <li>删除旧文件并全新安装最新版本的Agent</li>
                <li>重新安装依赖</li>
                <li>重启Agent服务</li>
              </ul>

              <p style="margin: 10px 0; font-weight: bold;">注意：</p>
              <ul style="margin: 5px 0 10px 20px;">
                <li>升级将使用SSH方式进行（需要提供SSH密码或私钥）</li>
                <li>升级将使用全新安装方式，不会保留旧文件</li>
                <li>升级完成后Agent服务会自动重启</li>
              </ul>
            </div>
          `,
          dangerouslyUseHTMLString: true
        }
      )
    } else {
    await ElMessageBox.confirm(
      `确定要在服务器 "${row.name}" 上安装Agent吗？\n\n` +
      `注意：如果安装失败，系统会保留SSH密码以便重试。\n` +
      `如果安装成功且未选择"保存密码"，系统会自动删除SSH密码。`,
      '确认安装Agent',
      {
        confirmButtonText: '确定安装',
        cancelButtonText: '取消',
        type: 'info'
      }
    )
    }
  } catch {
    return // 用户取消
  }

  installingAgentId.value = row.id
  try {
    const response = await api.post(`/servers/${row.id}/install_agent/`, {
      save_password: row.save_password || false
    })
    
    if (response.data.success) {
      ElMessage.success({
        message: isUpgrade
          ? 'Agent升级任务已启动，请稍后查看部署日志'
          : 'Agent安装任务已启动，请稍后查看部署日志',
        duration: 5000
      })
      // 刷新服务器列表
      await fetchServers()
    } else {
      ElMessage.error(response.data.error || (isUpgrade ? '启动Agent升级失败' : '启动Agent安装失败'))
    }
  } catch (error) {
    console.error('安装Agent失败:', error)
    const errorMsg = error.response?.data?.error || error.response?.data?.message || error.message
    ElMessage.error('安装Agent失败: ' + errorMsg)
  } finally {
    installingAgentId.value = null
  }
}

const handleViewAgentLogs = async (row) => {
  currentServerId.value = row.id
  agentLogDialogVisible.value = true
  activeLogTab.value = 'agent'
  autoRefreshLogs.value = false // 默认关闭自动刷新
  isFirstLoad.value = true
  // 重置offset
  agentLogs.value.agent_log_offset = 0
  agentLogs.value.systemd_offset = 0
  agentLogs.value.journalctl_offset = 0
  agentLogs.value.agent_log = ''
  agentLogs.value.systemd_status = ''
  agentLogs.value.journalctl_log = ''
  await refreshAgentLogs()
}

const refreshAgentLogs = async (isManualRefresh = false) => {
  if (!currentServerId.value) return
  
  // 如果关闭了自动刷新且不是手动刷新，则不执行任何操作（保持现有日志不变）
  if (!autoRefreshLogs.value && !isManualRefresh && !isFirstLoad.value) {
    return
  }
  
  loadingAgentLogs.value = true
  try {
    // 构建查询参数（支持增量获取）
    const params = new URLSearchParams()
    if (!isFirstLoad.value && autoRefreshLogs.value && !isManualRefresh) {
      params.append('incremental', 'true')
      params.append('agent_log_offset', agentLogs.value.agent_log_offset || 0)
      params.append('systemd_offset', agentLogs.value.systemd_offset || 0)
      params.append('journalctl_offset', agentLogs.value.journalctl_offset || 0)
    }
    
    const url = `/servers/${currentServerId.value}/agent_logs/${params.toString() ? '?' + params.toString() : ''}`
    const response = await api.get(url)
    
    // 流式追加：只追加新内容，不替换整个日志
    if (!isFirstLoad.value && autoRefreshLogs.value && !isManualRefresh) {
      // 增量模式：追加新内容（仅在自动刷新开启时）
      if (response.data.agent_log) {
        const newContent = response.data.agent_log
        if (newContent && newContent !== '日志文件不存在' && newContent.trim()) {
          // 根据排序顺序决定追加位置
          if (logSortOrder.value === 'desc') {
            // 最新在前：新内容追加到开头
            agentLogs.value.agent_log = newContent + agentLogs.value.agent_log
          } else {
            // 最久在前：新内容追加到末尾
            agentLogs.value.agent_log += newContent
          }
          agentLogs.value.agent_log_offset = response.data.agent_log_offset || agentLogs.value.agent_log_offset
        }
      }
      
      // journalctl日志也支持增量追加
      if (response.data.journalctl_log) {
        const newJournalContent = response.data.journalctl_log
        if (newJournalContent && newJournalContent !== '无法读取journalctl日志' && newJournalContent.trim()) {
          // 根据排序顺序决定追加位置
          if (logSortOrder.value === 'desc') {
            // 最新在前：新内容追加到开头
            agentLogs.value.journalctl_log = newJournalContent + agentLogs.value.journalctl_log
          } else {
            // 最久在前：新内容追加到末尾
            agentLogs.value.journalctl_log += newJournalContent
          }
          agentLogs.value.journalctl_offset = response.data.journalctl_offset || agentLogs.value.journalctl_offset
        }
      }
      
      // systemd状态通常不需要增量，只在首次加载时获取
    } else {
      // 首次加载或手动刷新：替换整个日志
      agentLogs.value.agent_log = response.data.agent_log || ''
      agentLogs.value.systemd_status = response.data.systemd_status || ''
      agentLogs.value.journalctl_log = response.data.journalctl_log || ''
      agentLogs.value.agent_log_offset = response.data.agent_log_offset || 0
      agentLogs.value.systemd_offset = response.data.systemd_offset || 0
      agentLogs.value.journalctl_offset = response.data.journalctl_offset || 0
      agentLogs.value.error = response.data.error || null
      isFirstLoad.value = false
    }
    
    // 自动滚动到相应位置（仅在自动刷新时）
    if (autoRefreshLogs.value) {
      await nextTick()
      if (activeLogTab.value === 'agent') {
        if (logSortOrder.value === 'desc') {
          // 最新在前：滚动到顶部
          scrollLogToTop('agent')
        } else {
          // 最久在前：滚动到底部
          scrollLogToBottom('agent')
        }
      } else if (activeLogTab.value === 'journalctl') {
        if (logSortOrder.value === 'desc') {
          // 最新在前：滚动到顶部
          scrollLogToTop('journalctl')
        } else {
          // 最久在前：滚动到底部
          scrollLogToBottom('journalctl')
        }
      }
    }
  } catch (error) {
    console.error('获取Agent日志失败:', error)
    const errorMsg = error.response?.data?.error || error.response?.data?.message || error.message
    agentLogs.value.error = `获取日志失败: ${errorMsg}`
  } finally {
    loadingAgentLogs.value = false
  }
}

const scrollLogToBottom = (tab) => {
  let scrollbarRef = null
  if (tab === 'agent') {
    scrollbarRef = agentLogScrollbar.value
  } else if (tab === 'systemd') {
    scrollbarRef = systemdLogScrollbar.value
  } else if (tab === 'journalctl') {
    scrollbarRef = journalctlLogScrollbar.value
  }
  
  if (scrollbarRef) {
    const scrollContainer = scrollbarRef.$el?.querySelector('.el-scrollbar__wrap')
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight
    }
  }
}

const scrollLogToTop = (tab) => {
  let scrollbarRef = null
  if (tab === 'agent') {
    scrollbarRef = agentLogScrollbar.value
  } else if (tab === 'journalctl') {
    scrollbarRef = journalctlLogScrollbar.value
  }
  
  if (scrollbarRef) {
    const scrollContainer = scrollbarRef.$el?.querySelector('.el-scrollbar__wrap')
    if (scrollContainer) {
      scrollContainer.scrollTop = 0
    }
  }
}

const handleAutoRefreshChange = (value) => {
  if (value) {
    startAgentLogRefresh()
  } else {
    stopAgentLogRefresh()
  }
}

const startAgentLogRefresh = () => {
  stopAgentLogRefresh()
  // 每3秒刷新一次日志（流式刷新，频率可以更高）
  agentLogRefreshInterval.value = setInterval(() => {
    if (agentLogDialogVisible.value && currentServerId.value && autoRefreshLogs.value) {
      refreshAgentLogs()
    } else {
      stopAgentLogRefresh()
    }
  }, 3000) // 3秒刷新一次，流式追加
}

const stopAgentLogRefresh = () => {
  if (agentLogRefreshInterval.value) {
    clearInterval(agentLogRefreshInterval.value)
    agentLogRefreshInterval.value = null
  }
}

const activeLogTab = ref('agent') // 当前激活的日志标签页
const agentLogScrollbar = ref(null) // Agent日志滚动条引用
const systemdLogScrollbar = ref(null) // Systemd日志滚动条引用
const journalctlLogScrollbar = ref(null) // Journalctl日志滚动条引用

// 计算排序后的日志
const sortedAgentLog = computed(() => {
  if (!agentLogs.value.agent_log) return '暂无日志'
  const lines = agentLogs.value.agent_log.split('\n')
  if (logSortOrder.value === 'desc') {
    // 最新在前：倒序（使用展开运算符创建新数组，避免修改原数组）
    return [...lines].reverse().join('\n')
  } else {
    // 最久在前：正序
    return lines.join('\n')
  }
})

const sortedJournalctlLog = computed(() => {
  if (!agentLogs.value.journalctl_log) return '暂无日志'
  const lines = agentLogs.value.journalctl_log.split('\n')
  if (logSortOrder.value === 'desc') {
    // 最新在前：倒序（使用展开运算符创建新数组，避免修改原数组）
    return [...lines].reverse().join('\n')
  } else {
    // 最久在前：正序
    return lines.join('\n')
  }
})

const handleSortOrderChange = () => {
  // 排序改变时，滚动到相应位置
  nextTick(() => {
    if (activeLogTab.value === 'agent') {
      if (logSortOrder.value === 'desc') {
        scrollLogToTop('agent')
      } else {
        scrollLogToBottom('agent')
      }
    } else if (activeLogTab.value === 'journalctl') {
      if (logSortOrder.value === 'desc') {
        scrollLogToTop('journalctl')
      } else {
        scrollLogToBottom('journalctl')
      }
    }
  })
}

const handleLogLinesChange = () => {
  // 行数改变时，重新加载日志（重置为首次加载）
  isFirstLoad.value = true
  agentLogs.value.agent_log_offset = 0
  agentLogs.value.systemd_offset = 0
  agentLogs.value.journalctl_offset = 0
  refreshAgentLogs(true) // 手动刷新
}

const copyLogs = async () => {
  // 根据当前标签页获取要复制的日志内容
  let logContent = ''
  if (activeLogTab.value === 'agent') {
    logContent = sortedAgentLog.value || '暂无日志'
  } else if (activeLogTab.value === 'systemd') {
    logContent = agentLogs.value.systemd_status || '暂无状态信息'
  } else if (activeLogTab.value === 'journalctl') {
    logContent = sortedJournalctlLog.value || '暂无日志'
  }
  
  if (!logContent || logContent === '暂无日志' || logContent === '暂无状态信息') {
    ElMessage.warning('没有可复制的内容')
    return
  }
  
  try {
    // 使用 Clipboard API 复制
    await navigator.clipboard.writeText(logContent)
    ElMessage.success('日志已复制到剪贴板')
  } catch (err) {
    // 降级方案：使用传统方法
    const textArea = document.createElement('textarea')
    textArea.value = logContent
    textArea.style.position = 'fixed'
    textArea.style.left = '-999999px'
    document.body.appendChild(textArea)
    textArea.select()
    try {
      document.execCommand('copy')
      ElMessage.success('日志已复制到剪贴板')
    } catch (e) {
      ElMessage.error('复制失败，请手动选择复制')
    } finally {
      document.body.removeChild(textArea)
    }
  }
}

const handleDelete = async (row) => {
  try {
    // 先调用删除接口获取关联信息
    const response = await api.delete(`/servers/${row.id}/`)
    
    // 如果返回需要确认的信息
    if (response.data?.requires_confirmation) {
      // 显示自定义删除确认对话框
      deleteServerInfo.value = row
      deleteRelatedInfo.value = response.data.related_objects
      deleteAgentChecked.value = response.data.related_objects.has_agent
      deleteProxiesChecked.value = response.data.related_objects.has_proxies
      deleteDialogVisible.value = true
    } else if (response.data?.success) {
      // 没有关联对象，直接删除成功
      ElMessage.success('删除成功')
      await fetchServers()
    } else {
      // 删除失败
      ElMessage.error(response.data?.error || '删除失败')
    }
  } catch (error) {
    console.error('删除服务器失败:', error)
    const errorMessage = error.response?.data?.error || error.response?.data?.message || error.message
    ElMessage.error('删除失败: ' + errorMessage)
  }
}

const confirmDelete = async () => {
  if (!deleteServerInfo.value) return
  
  deleting.value = true
  try {
    const deleteResponse = await api.delete(
      `/servers/${deleteServerInfo.value.id}/?confirmed=true&delete_agent=${deleteAgentChecked.value}&delete_proxies=${deleteProxiesChecked.value}`
    )
    if (deleteResponse.data?.success) {
      ElMessage.success('删除成功')
      deleteDialogVisible.value = false
      deleteServerInfo.value = null
      deleteRelatedInfo.value = null
      await fetchServers()
    } else {
      ElMessage.error(deleteResponse.data?.error || '删除失败')
    }
  } catch (error) {
    console.error('删除服务器失败:', error)
    const errorMessage = error.response?.data?.error || error.response?.data?.message || error.message
    ElMessage.error('删除失败: ' + errorMessage)
  } finally {
    deleting.value = false
  }
}

const handleTest = async (row) => {
  if (testingServerId.value === row.id) return // 防止重复点击
  
  testingServerId.value = row.id
  testSuccessMap.value[row.id] = false // 重置状态
  try {
    const response = await api.post(`/servers/${row.id}/test_connection/`)
    testSuccessMap.value[row.id] = true // 标记为成功
    
    // 检查是否有Web服务警告
    const data = response.data
    if (data.web_service_warning) {
      // 显示警告信息（使用warning类型）
      ElMessage({
        message: data.message || '连接测试成功',
        type: 'warning',
        duration: 5000,
        showClose: true
      })
      // 同时显示详细的Web服务警告
      ElMessage({
        message: `Web服务健康检查失败：${data.web_service_warning}\n已回退到心跳检查模式`,
        type: 'warning',
        duration: 8000,
        showClose: true
      })
    } else {
      ElMessage.success(data.message || '连接测试成功')
    }
    fetchServers()
  } catch (error) {
    testSuccessMap.value[row.id] = false // 标记为失败
    const errorMsg = error.response?.data?.error || error.response?.data?.message || '连接测试失败'
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
  console.log('[提交服务器] 开始提交，editingId:', editingId.value, 'form:', form)
  
  if (!formRef.value) {
    console.log('[提交服务器] formRef 不存在，返回')
    return
  }
  
  await formRef.value.validate(async (valid) => {
    console.log('[提交服务器] 表单验证结果:', valid)
    if (valid) {
      saving.value = true
      console.log('[提交服务器] 开始保存，editingId:', editingId.value)
      try {
        if (editingId.value) {
          console.log('[提交服务器] 更新服务器，ID:', editingId.value, '提交数据:', JSON.stringify(form, null, 2))
          const response = await api.put(`/servers/${editingId.value}/`, form)
          console.log('[提交服务器] 更新成功，响应:', response.data)
          ElMessage.success('更新成功')
        } else {
          console.log('[提交服务器] 创建新服务器，提交数据:', JSON.stringify(form, null, 2))
          const response = await api.post('/servers/', form)
          console.log('[提交服务器] 创建成功，响应:', response.data)
          ElMessage.success('添加成功')
        }
        
        dialogVisible.value = false
        await fetchServers()
        console.log('[提交服务器] 服务器列表已刷新')
      } catch (error) {
        console.error('[提交服务器] 操作失败:', error)
        console.error('[提交服务器] 错误详情:', {
          message: error.message,
          response: error.response?.data,
          status: error.response?.status,
          statusText: error.response?.statusText
        })
        const errorMsg = error.response?.data?.message || error.response?.data?.error || '操作失败'
        ElMessage.error(errorMsg)
      } finally {
        saving.value = false
        console.log('[提交服务器] 保存操作完成')
      }
    }
  })
}

const resetForm = () => {
  // 重置编辑ID
  editingId.value = null

  // 重置表单数据
  Object.assign(form, {
    name: '',
    host: '',
    port: 22,
    username: '',
    password: '',
    private_key: '',
    save_password: true,  // 默认勾选保存密码
    auto_clear_password_after_agent_install: true,  // 默认开启：安装agent后自动清除密码
    enable_ssh_key: false,
    connection_method: 'agent',  // 默认使用Agent连接方式
    deployment_target: 'host',
    agent_connect_host: '',
    agent_connect_port: null
  })

  // 重置表单验证状态
  formRef.value?.resetFields()

  // 重置其他状态
  testingConnection.value = false
  saving.value = false
  dialogTestSuccess.value = false // 重置测试成功状态
}

onMounted(() => {
  fetchServers()
})

// 组件卸载时清理定时器
onUnmounted(() => {
  stopAgentLogRefresh()
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
  flex-direction: column;
  gap: 6px;
}

.action-row {
  display: flex;
  gap: 6px;
  flex-wrap: nowrap;
}

/* 服务器表单优化样式 */
.server-form {
  max-height: 70vh;
  overflow-y: auto;
  padding-right: 8px;
}

.form-row-two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 0;
}

.form-row-two-cols .el-form-item {
  margin-bottom: 12px;
}

/* 优化对话框样式 */
.server-dialog :deep(.el-dialog__body) {
  padding: 16px 20px;
  max-height: 75vh;
}

/* 表单项样式 */
.server-form :deep(.el-form-item__label) {
  font-size: 14px;
  padding-right: 8px;
}

.server-form :deep(.el-form-item__content) {
  font-size: 14px;
}

.server-form :deep(.el-input__inner),
.server-form :deep(.el-textarea__inner) {
  font-size: 14px;
}

.server-form :deep(.el-switch__label) {
  font-size: 13px;
}

/* Divider样式 */
.server-form :deep(.el-divider) {
  margin: 18px 0 14px 0;
}

.server-form :deep(.el-divider.first-divider) {
  margin-top: 8px;
}

.server-form :deep(.el-divider__text) {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  background: #fff;
  padding: 0 12px;
}

/* Alert样式 */
.server-form :deep(.el-alert) {
  padding: 8px 12px;
}

.server-form :deep(.el-alert__title) {
  font-size: 13px;
  line-height: 1.5;
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

/* 日志加载遮罩层 */
.log-loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.9);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  z-index: 1000;
  border-radius: 4px;
}

/* 响应式优化 */
@media (max-width: 1024px) {
  .form-row-two-cols {
    grid-template-columns: 1fr;
  }

  .server-dialog {
    width: 90% !important;
  }
}
</style>

