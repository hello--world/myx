<template>
  <div class="proxies-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>代理节点管理</span>
          <el-button type="primary" @click="handleAdd">添加节点</el-button>
        </div>
      </template>

      <el-table :data="proxies" v-loading="loading" style="width: 100%">
        <el-table-column prop="name" label="节点名称" min-width="150" />
        <el-table-column prop="server_name" label="服务器" min-width="120" />
        <el-table-column prop="protocol" label="协议" width="100">
          <template #default="{ row }">
            <el-tag type="info">{{ row.protocol.toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="port" label="端口" width="100" />
        <el-table-column label="传输方式" width="120">
          <template #default="{ row }">
            {{ row.stream_settings_dict?.network || 'tcp' }}
          </template>
        </el-table-column>
        <el-table-column prop="enable" label="启用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.enable ? 'success' : 'info'">
              {{ row.enable ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '活跃' : '不活跃' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="deployment_status" label="部署状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getDeploymentStatusType(row.deployment_status)">
              {{ getDeploymentStatusText(row.deployment_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button 
              size="small" 
              type="warning" 
              @click="handleRedeploy(row)" 
              v-if="row.deployment_status === 'failed'"
              :loading="redeploying[row.id]"
            >
              重新部署
            </el-button>
            <el-button size="small" type="info" @click="handleViewLog(row)" v-if="row.deployment_log">查看日志</el-button>
            <el-button size="small" type="primary" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="dialogTitle"
      width="900px"
      @close="resetForm"
      :close-on-click-modal="false"
    >
      <el-tabs v-model="activeTab" type="border-card">
        <!-- 基础配置 -->
        <el-tab-pane label="基础配置" name="basic">
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-width="120px"
            style="margin-top: 20px;"
          >
            <el-form-item label="节点名称" prop="name">
              <el-input v-model="form.name" placeholder="请输入节点名称" style="width: 300px;" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注信息" style="width: 500px;" />
            </el-form-item>
            <el-form-item label="服务器" prop="server">
              <el-select v-model="form.server" placeholder="请选择服务器" style="width: 300px;">
                <el-option
                  v-for="server in servers"
                  :key="server.id"
                  :label="server.name"
                  :value="server.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="启用">
              <el-switch v-model="form.enable" />
            </el-form-item>
            <el-form-item label="协议" prop="protocol">
              <el-select v-model="form.protocol" placeholder="请选择协议" style="width: 200px;">
                <el-option label="VLESS" value="vless" />
                <el-option label="VMess" value="vmess" />
                <el-option label="Trojan" value="trojan" />
                <el-option label="Shadowsocks" value="shadowsocks" />
              </el-select>
            </el-form-item>
            <el-form-item label="监听IP">
              <el-input v-model="form.listen" placeholder="留空使用默认" style="width: 200px;" />
              <el-text type="info" size="small" style="margin-left: 10px;">默认留空即可</el-text>
            </el-form-item>
            <el-form-item label="端口" prop="port">
              <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 200px;" />
            </el-form-item>
            <el-form-item label="总流量(GB)">
              <el-input-number v-model="form.totalGB" :min="0" style="width: 200px;" />
              <el-text type="info" size="small" style="margin-left: 10px;">0 表示不限制</el-text>
            </el-form-item>
            <el-form-item label="到期时间">
              <el-date-picker
                v-model="form.expiryTime"
                type="datetime"
                placeholder="留空则永不到期"
                format="YYYY-MM-DD HH:mm"
                value-format="x"
                style="width: 300px;"
              />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <!-- 协议设置 -->
        <el-tab-pane :label="`${form.protocol.toUpperCase()} 设置`" name="protocol">
          <el-form :model="form" label-width="120px" style="margin-top: 20px;">
            <!-- VLESS 设置 -->
            <template v-if="form.protocol === 'vless'">
              <el-form-item label="ID (UUID)">
                <el-input v-model="protocolSettings.vless.id" placeholder="自动生成" style="width: 400px;" />
                <el-button @click="generateUUID('vless')" style="margin-left: 10px;">生成UUID</el-button>
              </el-form-item>
              <el-form-item label="Flow">
                <el-select v-model="protocolSettings.vless.flow" style="width: 200px;">
                  <el-option label="无" value="" />
                  <el-option label="xtls-rprx-vision" value="xtls-rprx-vision" />
                  <el-option label="xtls-rprx-vision-udp443" value="xtls-rprx-vision-udp443" />
                </el-select>
              </el-form-item>
            </template>

            <!-- VMess 设置 -->
            <template v-if="form.protocol === 'vmess'">
              <el-form-item label="ID (UUID)">
                <el-input v-model="protocolSettings.vmess.id" placeholder="自动生成" style="width: 400px;" />
                <el-button @click="generateUUID('vmess')" style="margin-left: 10px;">生成UUID</el-button>
              </el-form-item>
              <el-form-item label="禁用不安全加密">
                <el-switch v-model="protocolSettings.vmess.disableInsecure" />
              </el-form-item>
            </template>

            <!-- Trojan 设置 -->
            <template v-if="form.protocol === 'trojan'">
              <el-form-item label="密码">
                <el-input v-model="protocolSettings.trojan.password" placeholder="请输入密码" style="width: 400px;" />
                <el-button @click="generatePassword" style="margin-left: 10px;">生成密码</el-button>
              </el-form-item>
            </template>

            <!-- Shadowsocks 设置 -->
            <template v-if="form.protocol === 'shadowsocks'">
              <el-form-item label="加密方法">
                <el-select v-model="protocolSettings.shadowsocks.method" style="width: 300px;">
                  <el-option label="aes-256-gcm" value="aes-256-gcm" />
                  <el-option label="aes-128-gcm" value="aes-128-gcm" />
                  <el-option label="chacha20-poly1305" value="chacha20-poly1305" />
                  <el-option label="chacha20-ietf-poly1305" value="chacha20-ietf-poly1305" />
                </el-select>
              </el-form-item>
              <el-form-item label="密码">
                <el-input v-model="protocolSettings.shadowsocks.password" placeholder="请输入密码" style="width: 400px;" />
                <el-button @click="generatePassword" style="margin-left: 10px;">生成密码</el-button>
              </el-form-item>
              <el-form-item label="网络">
                <el-select v-model="protocolSettings.shadowsocks.network" style="width: 200px;">
                  <el-option label="tcp+udp" value="tcp,udp" />
                  <el-option label="tcp" value="tcp" />
                  <el-option label="udp" value="udp" />
                </el-select>
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>

        <!-- 传输设置 -->
        <el-tab-pane label="传输设置" name="stream">
          <el-form :model="form" label-width="120px" style="margin-top: 20px;">
            <el-form-item label="传输方式">
              <el-select v-model="streamSettings.network" style="width: 200px;">
                <el-option label="TCP" value="tcp" />
                <el-option label="WebSocket" value="ws" />
                <el-option label="gRPC" value="grpc" />
                <el-option label="QUIC" value="quic" />
                <el-option label="HTTP/2" value="h2" />
              </el-select>
            </el-form-item>

            <!-- WebSocket 设置 -->
            <template v-if="streamSettings.network === 'ws'">
              <el-form-item label="路径">
                <el-input v-model="streamSettings.ws.path" placeholder="/" style="width: 300px;" />
              </el-form-item>
              <el-form-item label="请求头">
                <div v-for="(header, index) in streamSettings.ws.headers" :key="index" style="margin-bottom: 10px;">
                  <el-input v-model="header.name" placeholder="名称" style="width: 150px; margin-right: 10px;" />
                  <el-input v-model="header.value" placeholder="值" style="width: 200px; margin-right: 10px;" />
                  <el-button @click="removeHeader(index)" type="danger" size="small">删除</el-button>
                </div>
                <el-button @click="addHeader" size="small">+ 添加请求头</el-button>
              </el-form-item>
            </template>

            <!-- gRPC 设置 -->
            <template v-if="streamSettings.network === 'grpc'">
              <el-form-item label="serviceName">
                <el-input v-model="streamSettings.grpc.serviceName" placeholder="" style="width: 300px;" />
              </el-form-item>
              <el-form-item label="authority">
                <el-input v-model="streamSettings.grpc.authority" placeholder="" style="width: 300px;" />
              </el-form-item>
              <el-form-item label="Multi Mode">
                <el-switch v-model="streamSettings.grpc.multiMode" />
              </el-form-item>
            </template>

            <!-- QUIC 设置 -->
            <template v-if="streamSettings.network === 'quic'">
              <el-form-item label="security">
                <el-select v-model="streamSettings.quic.security" style="width: 200px;">
                  <el-option label="none" value="none" />
                  <el-option label="aes-128-gcm" value="aes-128-gcm" />
                  <el-option label="chacha20-poly1305" value="chacha20-poly1305" />
                </el-select>
              </el-form-item>
              <el-form-item label="key">
                <el-input v-model="streamSettings.quic.key" placeholder="" style="width: 300px;" />
              </el-form-item>
              <el-form-item label="type">
                <el-select v-model="streamSettings.quic.type" style="width: 200px;">
                  <el-option label="none" value="none" />
                  <el-option label="srtp" value="srtp" />
                  <el-option label="utp" value="utp" />
                  <el-option label="wechat-video" value="wechat-video" />
                  <el-option label="dtls" value="dtls" />
                  <el-option label="wireguard" value="wireguard" />
                </el-select>
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>

        <!-- TLS/REALITY 设置 -->
        <el-tab-pane label="TLS/REALITY" name="tls">
          <el-form :model="form" label-width="120px" style="margin-top: 20px;">
            <el-form-item label="启用TLS">
              <el-switch v-model="streamSettings.security" :active-value="'tls'" :inactive-value="'none'" />
            </el-form-item>
            <el-form-item label="启用REALITY" v-if="streamSettings.security === 'tls'">
              <el-switch v-model="streamSettings.useReality" />
            </el-form-item>

            <!-- TLS 设置 -->
            <template v-if="streamSettings.security === 'tls' && !streamSettings.useReality">
              <el-form-item label="域名">
                <el-input v-model="streamSettings.tls.serverName" placeholder="SNI" style="width: 300px;" />
              </el-form-item>
              <el-form-item label="ALPN">
                <el-checkbox-group v-model="streamSettings.tls.alpn">
                  <el-checkbox label="h2" />
                  <el-checkbox label="http/1.1" />
                </el-checkbox-group>
              </el-form-item>
            </template>

            <!-- REALITY 设置 -->
            <template v-if="streamSettings.security === 'tls' && streamSettings.useReality">
              <el-form-item label="show">
                <el-switch v-model="streamSettings.reality.show" />
              </el-form-item>
              <el-form-item label="target">
                <el-input v-model="streamSettings.reality.dest" placeholder="www.microsoft.com:443" style="width: 400px;" />
              </el-form-item>
              <el-form-item label="serverNames">
                <el-input v-model="streamSettings.reality.serverNames" type="textarea" :rows="2" placeholder="每行一个域名" style="width: 400px;" />
              </el-form-item>
              <el-form-item label="privateKey">
                <el-input v-model="streamSettings.reality.privateKey" placeholder="" style="width: 400px;" />
              </el-form-item>
              <el-form-item label="publicKey">
                <el-input v-model="streamSettings.reality.publicKey" placeholder="" style="width: 400px;" />
              </el-form-item>
              <el-form-item label="shortIds">
                <el-input v-model="streamSettings.reality.shortIds" type="textarea" :rows="2" placeholder="每行一个" style="width: 400px;" />
              </el-form-item>
              <el-form-item>
                <el-button @click="generateRealityKeys" type="primary">生成REALITY密钥对</el-button>
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>

        <!-- 嗅探设置 -->
        <el-tab-pane label="嗅探设置" name="sniffing">
          <el-form :model="form" label-width="120px" style="margin-top: 20px;">
            <el-form-item label="启用嗅探">
              <el-switch v-model="sniffingSettings.enabled" />
            </el-form-item>
            <el-form-item label="destOverride" v-if="sniffingSettings.enabled">
              <el-checkbox-group v-model="sniffingSettings.destOverride">
                <el-checkbox label="http" />
                <el-checkbox label="tls" />
                <el-checkbox label="quic" />
                <el-checkbox label="fakedns" />
              </el-checkbox-group>
            </el-form-item>
            <el-form-item label="Metadata Only">
              <el-switch v-model="sniffingSettings.metadataOnly" />
            </el-form-item>
            <el-form-item label="Route Only">
              <el-switch v-model="sniffingSettings.routeOnly" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="logDialogVisible"
      title="部署日志"
      width="800px"
    >
      <el-scrollbar height="400px">
        <pre style="white-space: pre-wrap; font-family: monospace; padding: 10px;">{{ currentLog }}</pre>
      </el-scrollbar>
      <template #footer>
        <el-button @click="logDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const proxies = ref([])
const servers = ref([])
const dialogVisible = ref(false)
const dialogTitle = ref('添加节点')
const formRef = ref(null)
const editingId = ref(null)
const logDialogVisible = ref(false)
const currentLog = ref('')
const activeTab = ref('basic')
const redeploying = ref({})  // 记录正在重新部署的节点ID

// 基础表单
const form = reactive({
  name: '',
  server: null,
  remark: '',
  enable: true,
  protocol: 'vless',
  listen: '',
  port: 443,
  totalGB: 0,
  expiryTime: null
})

// 协议设置
const protocolSettings = reactive({
  vless: {
    id: '',
    flow: ''
  },
  vmess: {
    id: '',
    disableInsecure: false
  },
  trojan: {
    password: ''
  },
  shadowsocks: {
    method: 'aes-256-gcm',
    password: '',
    network: 'tcp,udp'
  }
})

// 传输设置
const streamSettings = reactive({
  network: 'tcp',
  security: 'none',
  useReality: false,
  ws: {
    path: '/',
    headers: []
  },
  grpc: {
    serviceName: '',
    authority: '',
    multiMode: false
  },
  quic: {
    security: 'none',
    key: '',
    type: 'none'
  },
  tls: {
    serverName: '',
    alpn: ['h2', 'http/1.1']
  },
  reality: {
    show: false,
    dest: 'www.microsoft.com:443',
    serverNames: '',
    privateKey: '',
    publicKey: '',
    shortIds: ''
  }
})

// 嗅探设置
const sniffingSettings = reactive({
  enabled: true,
  destOverride: ['http', 'tls', 'quic'],
  metadataOnly: false,
  routeOnly: false
})

const rules = {
  name: [{ required: true, message: '请输入节点名称', trigger: 'blur' }],
  server: [{ required: true, message: '请选择服务器', trigger: 'change' }],
  protocol: [{ required: true, message: '请选择协议', trigger: 'change' }],
  port: [{ required: true, message: '请输入端口', trigger: 'blur' }]
}

// 生成UUID
const generateUUID = (protocol) => {
  const uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0
    const v = c === 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
  if (protocol === 'vless') {
    protocolSettings.vless.id = uuid
    return uuid
  } else if (protocol === 'vmess') {
    protocolSettings.vmess.id = uuid
    return uuid
  }
  return uuid
}

// 生成密码
const generatePassword = () => {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let password = ''
  for (let i = 0; i < 16; i++) {
    password += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  if (form.protocol === 'trojan') {
    protocolSettings.trojan.password = password
  } else if (form.protocol === 'shadowsocks') {
    protocolSettings.shadowsocks.password = password
  }
}

// 添加请求头
const addHeader = () => {
  streamSettings.ws.headers.push({ name: '', value: '' })
}

// 删除请求头
const removeHeader = (index) => {
  streamSettings.ws.headers.splice(index, 1)
}

// 生成REALITY密钥对（简化版，实际应该调用后端API）
const generateRealityKeys = () => {
  // 这里应该调用后端API生成密钥对
  // 暂时使用占位符
  ElMessage.info('REALITY密钥对生成功能需要后端支持')
}

// 构建 settings JSON
const buildSettings = () => {
  const protocol = form.protocol
  if (protocol === 'vless') {
    if (!protocolSettings.vless.id) {
      generateUUID('vless')
    }
    const clients = [{
      id: protocolSettings.vless.id,
      flow: protocolSettings.vless.flow || '',
      encryption: 'none'
    }]
    return { clients, decryption: 'none' }
  } else if (protocol === 'vmess') {
    if (!protocolSettings.vmess.id) {
      generateUUID('vmess')
    }
    const clients = [{
      id: protocolSettings.vmess.id,
      alterId: 0,
      security: 'auto'
    }]
    return { clients, disableInsecureEncryption: protocolSettings.vmess.disableInsecure }
  } else if (protocol === 'trojan') {
    if (!protocolSettings.trojan.password) {
      generatePassword()
    }
    const clients = [{
      password: protocolSettings.trojan.password,
      flow: ''
    }]
    return { clients }
  } else if (protocol === 'shadowsocks') {
    if (!protocolSettings.shadowsocks.password) {
      generatePassword()
    }
    return {
      method: protocolSettings.shadowsocks.method,
      password: protocolSettings.shadowsocks.password,
      network: protocolSettings.shadowsocks.network
    }
  }
  return {}
}

// 构建 streamSettings JSON
const buildStreamSettings = () => {
  const network = streamSettings.network
  const result = {
    network: network,
    security: streamSettings.security
  }

  // 根据传输方式添加对应配置
  if (network === 'ws') {
    const headers = {}
    streamSettings.ws.headers.forEach(h => {
      if (h.name && h.value) {
        headers[h.name] = h.value
      }
    })
    result.wsSettings = {
      path: streamSettings.ws.path || '/',
      headers: headers
    }
  } else if (network === 'grpc') {
    result.grpcSettings = {
      serviceName: streamSettings.grpc.serviceName || '',
      authority: streamSettings.grpc.authority || '',
      multiMode: streamSettings.grpc.multiMode
    }
  } else if (network === 'quic') {
    result.quicSettings = {
      security: streamSettings.quic.security,
      key: streamSettings.quic.key,
      type: streamSettings.quic.type
    }
  } else if (network === 'tcp') {
    result.tcpSettings = {
      header: { type: 'none' }
    }
  }

  // TLS/REALITY 配置
  if (streamSettings.security === 'tls') {
    if (streamSettings.useReality) {
      result.realitySettings = {
        show: streamSettings.reality.show,
        dest: streamSettings.reality.dest,
        xver: 0,
        serverNames: streamSettings.reality.serverNames.split('\n').filter(s => s.trim()),
        privateKey: streamSettings.reality.privateKey,
        publicKey: streamSettings.reality.publicKey,
        shortIds: streamSettings.reality.shortIds.split('\n').filter(s => s.trim())
      }
      result.security = 'reality'
    } else {
      result.tlsSettings = {
        serverName: streamSettings.tls.serverName || '',
        alpn: streamSettings.tls.alpn || ['h2', 'http/1.1'],
        certificates: [{
          certificateFile: '/usr/local/etc/xray/cert.pem',
          keyFile: '/usr/local/etc/xray/key.pem'
        }]
      }
    }
  }

  return result
}

// 构建 sniffing JSON
const buildSniffing = () => {
  return {
    enabled: sniffingSettings.enabled,
    destOverride: sniffingSettings.destOverride || [],
    metadataOnly: sniffingSettings.metadataOnly,
    routeOnly: sniffingSettings.routeOnly
  }
}

const fetchProxies = async () => {
  loading.value = true
  try {
    const response = await api.get('/proxies/')
    proxies.value = response.data.results || response.data
  } catch (error) {
    ElMessage.error('获取节点列表失败')
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

const handleAdd = () => {
  dialogTitle.value = '添加节点'
  editingId.value = null
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  dialogTitle.value = '编辑节点'
  editingId.value = row.id
  
  // 基础信息
  Object.assign(form, {
    name: row.name,
    server: row.server,
    remark: row.remark || '',
    enable: row.enable !== false,
    protocol: row.protocol,
    listen: row.listen || '',
    port: row.port,
    totalGB: row.total ? (row.total / 1024 / 1024 / 1024).toFixed(2) : 0,
    expiryTime: row.expiry_time ? row.expiry_time * 1000 : null
  })
  
  // 解析 settings
  if (row.settings_dict) {
    const settings = row.settings_dict
    if (row.protocol === 'vless' && settings.clients && settings.clients[0]) {
      protocolSettings.vless.id = settings.clients[0].id || ''
      protocolSettings.vless.flow = settings.clients[0].flow || ''
    } else if (row.protocol === 'vmess' && settings.clients && settings.clients[0]) {
      protocolSettings.vmess.id = settings.clients[0].id || ''
      protocolSettings.vmess.disableInsecure = settings.disableInsecureEncryption || false
    } else if (row.protocol === 'trojan' && settings.clients && settings.clients[0]) {
      protocolSettings.trojan.password = settings.clients[0].password || ''
    } else if (row.protocol === 'shadowsocks') {
      protocolSettings.shadowsocks.method = settings.method || 'aes-256-gcm'
      protocolSettings.shadowsocks.password = settings.password || ''
      protocolSettings.shadowsocks.network = settings.network || 'tcp,udp'
    }
  }
  
  // 解析 streamSettings
  if (row.stream_settings_dict) {
    const ss = row.stream_settings_dict
    streamSettings.network = ss.network || 'tcp'
    streamSettings.security = ss.security || 'none'
    streamSettings.useReality = ss.security === 'reality'
    
    if (ss.wsSettings) {
      streamSettings.ws.path = ss.wsSettings.path || '/'
      streamSettings.ws.headers = Object.keys(ss.wsSettings.headers || {}).map(k => ({
        name: k,
        value: ss.wsSettings.headers[k]
      }))
    }
    if (ss.grpcSettings) {
      streamSettings.grpc.serviceName = ss.grpcSettings.serviceName || ''
      streamSettings.grpc.authority = ss.grpcSettings.authority || ''
      streamSettings.grpc.multiMode = ss.grpcSettings.multiMode || false
    }
    if (ss.tlsSettings) {
      streamSettings.tls.serverName = ss.tlsSettings.serverName || ''
      streamSettings.tls.alpn = ss.tlsSettings.alpn || ['h2', 'http/1.1']
    }
    if (ss.realitySettings) {
      streamSettings.reality.show = ss.realitySettings.show || false
      streamSettings.reality.dest = ss.realitySettings.dest || 'www.microsoft.com:443'
      streamSettings.reality.serverNames = Array.isArray(ss.realitySettings.serverNames) 
        ? ss.realitySettings.serverNames.join('\n') 
        : ''
      streamSettings.reality.privateKey = ss.realitySettings.privateKey || ''
      streamSettings.reality.publicKey = ss.realitySettings.publicKey || ''
      streamSettings.reality.shortIds = Array.isArray(ss.realitySettings.shortIds)
        ? ss.realitySettings.shortIds.join('\n')
        : ''
    }
  }
  
  // 解析 sniffing
  if (row.sniffing_dict) {
    const sniff = row.sniffing_dict
    sniffingSettings.enabled = sniff.enabled !== false
    sniffingSettings.destOverride = sniff.destOverride || ['http', 'tls', 'quic']
    sniffingSettings.metadataOnly = sniff.metadataOnly || false
    sniffingSettings.routeOnly = sniff.routeOnly || false
  }
  
  dialogVisible.value = true
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm('确定要删除这个节点吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/proxies/${row.id}/`)
    ElMessage.success('删除成功')
    fetchProxies()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const handleViewLog = (row) => {
  currentLog.value = row.deployment_log || '暂无日志'
  logDialogVisible.value = true
}

const handleRedeploy = async (row) => {
  try {
    await ElMessageBox.confirm('确定要重新部署这个节点吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    redeploying.value[row.id] = true
    try {
      await api.post(`/proxies/${row.id}/redeploy/`)
      ElMessage.success('重新部署已启动，请稍后查看部署状态')
      
      // 刷新列表
      fetchProxies()
      
      // 定期刷新以更新部署状态
      const refreshInterval = setInterval(() => {
        fetchProxies()
        // 如果部署完成，停止刷新
        const proxy = proxies.value.find(p => p.id === row.id)
        if (proxy && (proxy.deployment_status === 'success' || proxy.deployment_status === 'failed')) {
          clearInterval(refreshInterval)
          redeploying.value[row.id] = false
        }
      }, 3000)
      
      // 60秒后停止自动刷新
      setTimeout(() => {
        clearInterval(refreshInterval)
        redeploying.value[row.id] = false
      }, 60000)
    } catch (error) {
      redeploying.value[row.id] = false
      ElMessage.error('重新部署失败: ' + (error.response?.data?.detail || error.message))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('重新部署错误:', error)
    }
  }
}

const getDeploymentStatusType = (status) => {
  const map = {
    pending: 'info',
    running: 'warning',
    success: 'success',
    failed: 'danger'
  }
  return map[status] || 'info'
}

const getDeploymentStatusText = (status) => {
  const map = {
    pending: '待部署',
    running: '部署中',
    success: '部署成功',
    failed: '部署失败'
  }
  return map[status] || '未知'
}

const handleSubmit = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (valid) {
      try {
        // 构建完整的配置对象
        const payload = {
          name: form.name,
          server: form.server,
          remark: form.remark || '',
          enable: form.enable,
          protocol: form.protocol,
          listen: form.listen || '',
          port: form.port,
          total: form.totalGB ? Math.floor(form.totalGB * 1024 * 1024 * 1024) : 0,
          expiry_time: form.expiryTime ? Math.floor(form.expiryTime / 1000) : 0,
          settings: buildSettings(),
          stream_settings: buildStreamSettings(),
          sniffing: buildSniffing()
        }
        
        if (editingId.value) {
          await api.put(`/proxies/${editingId.value}/`, payload)
          ElMessage.success('更新成功')
        } else {
          await api.post('/proxies/', payload)
          ElMessage.success('添加成功，正在自动部署...')
        }
        dialogVisible.value = false
        fetchProxies()
        
        // 如果是新建，定期刷新以更新部署状态
        if (!editingId.value) {
          const refreshInterval = setInterval(() => {
            fetchProxies()
            // 如果所有代理都部署完成，停止刷新
            const allDone = proxies.value.every(p => 
              p.deployment_status === 'success' || p.deployment_status === 'failed'
            )
            if (allDone) {
              clearInterval(refreshInterval)
            }
          }, 3000)
          
          // 30秒后停止自动刷新
          setTimeout(() => clearInterval(refreshInterval), 30000)
        }
      } catch (error) {
        console.error('提交失败:', error)
        ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
      }
    }
  })
}

const resetForm = () => {
  Object.assign(form, {
    name: '',
    server: null,
    remark: '',
    enable: true,
    protocol: 'vless',
    listen: '',
    port: 443,
    totalGB: 0,
    expiryTime: null
  })
  
  // 重置协议设置
  protocolSettings.vless = { id: '', flow: '' }
  protocolSettings.vmess = { id: '', disableInsecure: false }
  protocolSettings.trojan = { password: '' }
  protocolSettings.shadowsocks = { method: 'aes-256-gcm', password: '', network: 'tcp,udp' }
  
  // 重置传输设置
  streamSettings.network = 'tcp'
  streamSettings.security = 'none'
  streamSettings.useReality = false
  streamSettings.ws = { path: '/', headers: [] }
  streamSettings.grpc = { serviceName: '', authority: '', multiMode: false }
  streamSettings.quic = { security: 'none', key: '', type: 'none' }
  streamSettings.tls = { serverName: '', alpn: ['h2', 'http/1.1'] }
  streamSettings.reality = {
    show: false,
    dest: 'www.microsoft.com:443',
    serverNames: '',
    privateKey: '',
    publicKey: '',
    shortIds: ''
  }
  
  // 重置嗅探设置
  sniffingSettings.enabled = true
  sniffingSettings.destOverride = ['http', 'tls', 'quic']
  sniffingSettings.metadataOnly = false
  sniffingSettings.routeOnly = false
  
  activeTab.value = 'basic'
  formRef.value?.resetFields()
}

// 监听协议变化，自动生成UUID
watch(() => form.protocol, (newProtocol) => {
  if (newProtocol === 'vless' && !protocolSettings.vless.id) {
    generateUUID('vless')
  } else if (newProtocol === 'vmess' && !protocolSettings.vmess.id) {
    generateUUID('vmess')
  }
}, { immediate: true })

onMounted(() => {
  fetchProxies()
  fetchServers()
})
</script>

<style scoped>
.proxies-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>

