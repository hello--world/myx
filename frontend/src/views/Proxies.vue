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
              type="danger" 
              @click="handleStopDeployment(row)" 
              v-if="row.deployment_status === 'running'"
              :loading="stopping[row.id]"
            >
              停止部署
            </el-button>
            <el-button 
              size="small" 
              type="warning" 
              @click="handleRedeploy(row)" 
              v-if="row.deployment_status === 'failed'"
              :loading="redeploying[row.id]"
            >
              重新部署
            </el-button>
            <el-button 
              size="small" 
              type="info" 
              @click="handleViewLog(row)" 
              v-if="row.deployment_log"
            >
              查看日志
            </el-button>
            <el-button 
              size="small" 
              type="success" 
              @click="handleManageCaddy(row)"
            >
              Caddy管理
            </el-button>
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
      class="proxy-dialog"
    >
      <el-tabs v-model="activeTab" type="border-card">
        <!-- 基础配置 -->
        <el-tab-pane label="基础配置" name="basic">
          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            label-width="80px"
            class="proxy-form"
          >
            <!-- 基本信息 -->
            <el-divider content-position="left" class="first-divider">基本信息</el-divider>
            <div class="form-row-three-cols">
              <el-form-item label="节点名" prop="name">
                <el-input v-model="form.name" placeholder="节点名" />
              </el-form-item>
              <el-form-item label="服务器" prop="server">
                <el-select v-model="form.server" placeholder="选择服务器" style="width: 100%;" @change="handleServerChange">
                  <el-option
                    v-for="server in servers"
                    :key="server.id"
                    :label="server.name"
                    :value="server.id"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="订阅">
                <el-switch v-model="form.enable" />
              </el-form-item>
            </div>
            <div class="form-row-three-cols">
              <el-form-item label="域名" prop="agent_connect_host">
                <el-input
                  v-model="form.agent_connect_host"
                  placeholder="CDN或Nginx代理域名，隐藏真实服务器地址"
                />
              </el-form-item>
              <el-form-item label="域名端口" prop="agent_connect_port">
                <el-input-number
                  v-model="form.agent_connect_port"
                  :min="1"
                  :max="65535"
                  placeholder="端口"
                  style="width: 100%;"
                />
              </el-form-item>
              <el-form-item label="监听IP">
                <el-input v-model="form.listen" placeholder="默认0.0.0.0" />
              </el-form-item>
            </div>
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="备注信息" />
            </el-form-item>

            <!-- 协议配置 -->
            <el-divider content-position="left">协议配置</el-divider>
            <div class="form-row-two-cols">
              <el-form-item label="协议" prop="protocol">
                <el-select v-model="form.protocol" placeholder="选择协议" style="width: 100%;">
                  <el-option label="VLESS" value="vless" />
                  <el-option label="VMess" value="vmess" />
                  <el-option label="Trojan" value="trojan" />
                  <el-option label="Shadowsocks" value="shadowsocks" />
                </el-select>
              </el-form-item>
              <el-form-item label="端口" prop="port">
                <div style="display: flex; align-items: center; gap: 6px;">
                  <el-input-number
                    v-model="form.port"
                    :min="1"
                    :max="65535"
                    style="width: 100%;"
                    @blur="checkPortAvailability"
                  />
                  <el-button type="primary" @click="getRandomPort" size="small">随机</el-button>
                  <span v-if="form.port" style="color: #67c23a; font-size: 13px; font-weight: 500; white-space: nowrap;">已分配端口{{ form.port }}</span>
                </div>
                <div v-if="portCheckMessage && !portCheckAvailable" :style="{ color: '#f56c6c', fontSize: '13px', marginTop: '4px' }">
                  {{ portCheckMessage }}
                </div>
              </el-form-item>
            </div>
            <div class="form-row-two-cols">
              <el-form-item label="到期时间">
                <el-date-picker
                  v-model="form.expiryTime"
                  type="datetime"
                  placeholder="留空永不到期"
                  format="YYYY-MM-DD HH:mm"
                  value-format="x"
                  style="width: 100%;"
                />
              </el-form-item>
              <el-form-item label="总流量GB">
                <el-input-number v-model="form.totalGB" :min="0" style="width: 100%;" placeholder="0不限" />
              </el-form-item>
            </div>
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
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span v-if="currentProxyId && getProxyById(currentProxyId)?.deployment_status === 'running'" style="color: #409eff;">
            ⚡ 部署中，日志每2秒自动刷新
          </span>
          <span v-else></span>
          <div>
            <el-button 
              type="primary" 
              @click="handleRefreshLog" 
              v-if="currentProxyId && getProxyById(currentProxyId)?.deployment_status === 'running'"
            >
              刷新日志
            </el-button>
            <el-button @click="logDialogVisible = false">关闭</el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- Caddy 管理对话框 -->
    <el-dialog
      v-model="caddyDialogVisible"
      title="Caddy 管理"
      width="800px"
      @close="resetCaddyForm"
    >
      <el-tabs v-model="caddyActiveTab">
        <el-tab-pane label="Caddyfile 编辑" name="edit">
          <el-form label-width="120px" style="margin-top: 20px;">
            <el-form-item label="Caddyfile 内容">
              <el-input
                v-model="caddyfileContent"
                type="textarea"
                :rows="20"
                :placeholder="caddyLoading ? '正在读取 Caddyfile...' : 'Caddyfile 内容'"
                :disabled="caddyLoading"
                style="font-family: monospace;"
                v-loading="caddyLoading && !caddyfileContent"
              />
              <div v-if="caddyLoading && !caddyfileContent" style="color: #909399; font-size: 12px; margin-top: 5px;">
                <el-icon class="is-loading"><Loading /></el-icon> 正在从远程服务器读取 Caddyfile...
              </div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="handleLoadCaddyfile" :loading="caddyLoading">读取 Caddyfile</el-button>
              <el-button type="success" @click="handleSaveCaddyfile" :loading="caddyLoading">保存并验证</el-button>
              <el-button type="warning" @click="handleValidateCaddyfile" :loading="caddyLoading">验证配置</el-button>
              <el-button type="info" @click="handleReloadCaddy" :loading="caddyLoading">重载 Caddy</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="TLS 证书管理" name="certificates">
          <div style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
              <span>证书列表</span>
              <el-button type="primary" size="small" @click="handleAddCertificate">新增证书</el-button>
            </div>
            <el-table :data="certificates" stripe style="width: 100%">
              <el-table-column prop="domain" label="域名" width="200" />
              <el-table-column prop="cert_path" label="证书路径" />
              <el-table-column prop="key_path" label="密钥路径" />
              <el-table-column label="操作" width="200">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="handleEditCertificate(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="handleDeleteCertificate(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
        <el-tab-pane label="操作结果" name="result">
          <el-alert
            v-if="caddyResult"
            :title="caddyResult"
            :type="caddyResultType"
            :closable="false"
            style="margin-bottom: 20px;"
          />
          <el-input
            v-model="caddyResultDetail"
            type="textarea"
            :rows="15"
            readonly
            placeholder="操作结果将显示在这里"
            style="font-family: monospace;"
          />
        </el-tab-pane>
      </el-tabs>
    </el-dialog>

    <!-- 证书编辑对话框 -->
    <el-dialog
      v-model="certDialogVisible"
      :title="certEditing ? '编辑证书' : '新增证书'"
      width="700px"
      @close="resetCertForm"
    >
      <el-form label-width="120px">
        <el-form-item label="域名">
          <el-input v-model="certForm.domain" placeholder="例如: example.com" />
        </el-form-item>
        <el-form-item label="证书路径">
          <el-input v-model="certForm.cert_path" placeholder="例如: /data/ssl/example.com.pem" />
        </el-form-item>
        <el-form-item label="密钥路径">
          <el-input v-model="certForm.key_path" placeholder="例如: /data/ssl/example.com.key" />
        </el-form-item>
        <el-form-item label="证书内容">
          <el-input
            v-model="certForm.cert_content"
            type="textarea"
            :rows="10"
            placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
            style="font-family: monospace;"
          />
        </el-form-item>
        <el-form-item label="密钥内容">
          <el-input
            v-model="certForm.key_content"
            type="textarea"
            :rows="10"
            placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
            style="font-family: monospace;"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="certDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveCertificate" :loading="certLoading">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
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
const currentProxyId = ref(null)  // 当前查看日志的代理ID
const activeTab = ref('basic')
const redeploying = ref({})  // 记录正在重新部署的节点ID
const stopping = ref({})  // 记录正在停止部署的节点ID
let refreshInterval = null  // 自动刷新定时器
let logRefreshInterval = null  // 日志自动刷新定时器

// Caddy 管理相关
const caddyDialogVisible = ref(false)
const caddyActiveTab = ref('edit')
const caddyfileContent = ref('')
const caddyLoading = ref(false)
const caddyResult = ref('')
const caddyResultType = ref('info')
const caddyResultDetail = ref('')
const currentCaddyProxyId = ref(null)  // 当前管理 Caddy 的代理ID

// 证书管理相关
const certificates = ref([])
const certDialogVisible = ref(false)
const certEditing = ref(false)
const certLoading = ref(false)
const certForm = reactive({
  domain: '',
  cert_path: '',
  key_path: '',
  cert_content: '',
  key_content: ''
})

// 基础表单
const form = reactive({
  name: '',
  server: null,
  remark: '',
  enable: true,
  protocol: 'vless',
  listen: '',
  port: null,
  totalGB: 0,
  expiryTime: null,
  agent_connect_host: '',
  agent_connect_port: null
})

const selectedServer = computed(() => {
  if (!form.server) return null
  return servers.value.find(s => s.id === form.server)
})

const handleServerChange = () => {
  // 当选择服务器时，如果服务器有Agent连接地址，自动填充
  if (selectedServer.value) {
    if (selectedServer.value.agent_connect_host) {
      form.agent_connect_host = selectedServer.value.agent_connect_host
    }
    if (selectedServer.value.agent_connect_port) {
      form.agent_connect_port = selectedServer.value.agent_connect_port
    }
  }
}

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

const portCheckMessage = ref('')
const portCheckAvailable = ref(true)

// 获取随机端口
const getRandomPort = async () => {
  try {
    const response = await api.get('/proxies/random_port/')
    if (response.data.port) {
      form.port = response.data.port
      portCheckMessage.value = response.data.message
      portCheckAvailable.value = true
      ElMessage.success(`已分配端口: ${response.data.port}`)
    } else {
      ElMessage.error(response.data.error || '获取随机端口失败')
    }
  } catch (error) {
    console.error('获取随机端口失败:', error)
    ElMessage.error('获取随机端口失败，请重试')
  }
}

// 检查端口是否可用
const checkPortAvailability = async () => {
  if (!form.port) {
    portCheckMessage.value = ''
    return
  }
  
  try {
    const params = { port: form.port }
    if (editingId.value) {
      params.proxy_id = editingId.value
    }
    const response = await api.get('/proxies/check_port/', { params })
    portCheckMessage.value = response.data.message
    portCheckAvailable.value = response.data.available
  } catch (error) {
    console.error('检查端口失败:', error)
    portCheckMessage.value = '检查端口失败，请重试'
    portCheckAvailable.value = false
  }
}

const rules = {
  name: [{ required: true, message: '请输入节点名称', trigger: 'blur' }],
  server: [{ required: true, message: '请选择服务器', trigger: 'change' }],
  protocol: [{ required: true, message: '请选择协议', trigger: 'change' }],
  port: [
    { required: true, message: '请输入端口', trigger: 'blur' },
    { 
      validator: (rule, value, callback) => {
        if (!value) {
          callback()
          return
        }
        if (!portCheckAvailable.value && portCheckMessage.value) {
          callback(new Error(portCheckMessage.value))
          return
        }
        callback()
      }, 
      trigger: 'blur' 
    }
  ]
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
      flow: protocolSettings.vless.flow || ''
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

const handleAdd = async () => {
  dialogTitle.value = '添加节点'
  editingId.value = null
  // 先重置表单，再打开对话框
  resetForm()
  // 使用 nextTick 确保表单重置完成后再打开对话框
  setTimeout(async () => {
    dialogVisible.value = true
    // 自动获取随机端口
    await getRandomPort()
  }, 0)
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
    await ElMessageBox.confirm(
      `确定要删除节点 "${row.name}" 吗？\n\n` +
      `删除操作是同步的，将会：\n` +
      `• 从服务器上删除该节点的Xray配置\n` +
      `• 重新部署剩余节点的配置（如果有）\n` +
      `• 如果服务器上没有其他节点，将清空Xray配置\n\n` +
      `此操作无法撤销，请谨慎操作。`,
      '确认删除节点',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
        dangerouslyUseHTMLString: false
      }
    )
    
    // 显示加载提示
    const loadingMessage = ElMessage({
      message: '正在删除节点并同步删除服务器配置...',
      type: 'info',
      duration: 0, // 不自动关闭
      showClose: false
    })
    
    try {
      const response = await api.delete(`/proxies/${row.id}/`)
      loadingMessage.close()
      
      if (response.data.message) {
        ElMessage.success(response.data.message || '节点删除成功，已同步删除服务器配置')
      } else {
        ElMessage.success('节点删除成功')
      }
      await fetchProxies()
    } catch (deleteError) {
      loadingMessage.close()
      throw deleteError
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除节点失败:', error)
      ElMessage.error(error.response?.data?.error || error.response?.data?.detail || '删除失败')
    }
  }
}

const handleViewLog = (row) => {
  currentProxyId.value = row.id
  currentLog.value = row.deployment_log || '暂无日志'
  logDialogVisible.value = true
  
  // 如果正在部署中，启动自动刷新日志
  if (row.deployment_status === 'running') {
    startLogAutoRefresh()
  } else {
    stopLogAutoRefresh()
  }
}

const handleRefreshLog = async () => {
  if (!currentProxyId.value) return
  
  await fetchProxies()
  const proxy = proxies.value.find(p => p.id === currentProxyId.value)
  if (proxy) {
    currentLog.value = proxy.deployment_log || '暂无日志'
    
    // 如果部署已完成，停止自动刷新
    if (proxy.deployment_status !== 'running') {
      stopLogAutoRefresh()
    }
  }
}

const getProxyById = (id) => {
  return proxies.value.find(p => p.id === id)
}

// 启动日志自动刷新（仅在日志对话框打开且部署中时）
const startLogAutoRefresh = () => {
  // 如果已经有定时器在运行，不重复启动
  if (logRefreshInterval) {
    return
  }
  
  logRefreshInterval = setInterval(() => {
    if (logDialogVisible.value && currentProxyId.value) {
      handleRefreshLog()
    } else {
      stopLogAutoRefresh()
    }
  }, 2000)  // 每2秒刷新一次日志
}

// 停止日志自动刷新
const stopLogAutoRefresh = () => {
  if (logRefreshInterval) {
    clearInterval(logRefreshInterval)
    logRefreshInterval = null
  }
}

const handleStopDeployment = async (row) => {
  try {
    await ElMessageBox.confirm('确定要停止部署吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    stopping.value[row.id] = true
    try {
      await api.post(`/proxies/${row.id}/stop_deployment/`)
      ElMessage.success('部署已停止')
      
      // 刷新列表
      await fetchProxies()
      stopping.value[row.id] = false
    } catch (error) {
      stopping.value[row.id] = false
      ElMessage.error('停止部署失败: ' + (error.response?.data?.detail || error.message))
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('停止部署错误:', error)
    }
  }
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
      
      // 启动自动刷新（如果还没有启动）
      startAutoRefresh()
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

// 启动自动刷新（当有部署中的节点时）
const startAutoRefresh = () => {
  // 如果已经有定时器在运行，不重复启动
  if (refreshInterval) {
    return
  }
  
  refreshInterval = setInterval(() => {
    fetchProxies().then(() => {
      // 检查是否还有部署中的节点
      const hasRunning = proxies.value.some(p => p.deployment_status === 'running')
      if (!hasRunning) {
        // 没有部署中的节点，停止自动刷新
        stopAutoRefresh()
      }
    })
  }, 3000)  // 每3秒刷新一次
}

// 停止自动刷新
const stopAutoRefresh = () => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
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
        await fetchProxies()
        
        // 如果是新建，启动自动刷新
        if (!editingId.value) {
          startAutoRefresh()
        }
      } catch (error) {
        console.error('提交失败:', error)
        ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
      }
    }
  })
}

const resetForm = () => {
  // 重置编辑ID
  editingId.value = null
  
  portCheckMessage.value = ''
  portCheckAvailable.value = true
  
  // 重置基础表单
  Object.assign(form, {
    name: '',
    server: null,
    remark: '',
    enable: true,
    protocol: 'vless',
    listen: '',
    port: null,
    totalGB: 0,
    expiryTime: null,
    agent_connect_host: '',
    agent_connect_port: null,
    heartbeat_mode: 'push'  // 默认推送模式
  })
  
  // 重置协议设置（完全重置对象）
  Object.assign(protocolSettings, {
    vless: { id: '', flow: '' },
    vmess: { id: '', disableInsecure: false },
    trojan: { password: '' },
    shadowsocks: { method: 'aes-256-gcm', password: '', network: 'tcp,udp' }
  })
  
  // 重置传输设置（完全重置对象）
  Object.assign(streamSettings, {
    network: 'tcp',
    security: 'none',
    useReality: false,
    ws: { path: '/', headers: [] },
    grpc: { serviceName: '', authority: '', multiMode: false },
    quic: { security: 'none', key: '', type: 'none' },
    tls: { serverName: '', alpn: ['h2', 'http/1.1'] },
    reality: {
      show: false,
      dest: 'www.microsoft.com:443',
      serverNames: '',
      privateKey: '',
      publicKey: '',
      shortIds: ''
    }
  })
  
  // 重置嗅探设置（完全重置对象）
  Object.assign(sniffingSettings, {
    enabled: true,
    destOverride: ['http', 'tls', 'quic'],
    metadataOnly: false,
    routeOnly: false
  })
  
  activeTab.value = 'basic'
  formRef.value?.resetFields()
}

// Caddy 管理相关函数
const handleManageCaddy = (row) => {
  currentCaddyProxyId.value = row.id
  caddyDialogVisible.value = true
  caddyActiveTab.value = 'edit'
  caddyfileContent.value = ''
  caddyResult.value = ''
  caddyResultDetail.value = ''
  caddyLoading.value = true  // 立即显示加载状态
  certificates.value = []  // 清空证书列表
  // 自动读取 Caddyfile
  handleLoadCaddyfile()
  // 自动加载证书列表
  handleLoadCertificates()
}

const handleLoadCaddyfile = async () => {
  if (!currentCaddyProxyId.value) return
  
  caddyLoading.value = true
  caddyResult.value = ''
  caddyResultDetail.value = ''
  caddyfileContent.value = ''  // 清空内容，显示加载状态
  
  try {
    const response = await api.get(`/proxies/${currentCaddyProxyId.value}/get_caddyfile/`)
    if (response.data.content) {
      caddyfileContent.value = response.data.content
      caddyResult.value = '读取成功'
      caddyResultType.value = 'success'
      caddyResultDetail.value = response.data.message || 'Caddyfile 读取成功'
    } else {
      caddyResult.value = '读取失败'
      caddyResultType.value = 'error'
      caddyResultDetail.value = response.data.error || 'Caddyfile 不存在或读取失败'
      caddyActiveTab.value = 'result'
    }
  } catch (error) {
    caddyResult.value = '读取失败'
    caddyResultType.value = 'error'
    caddyResultDetail.value = error.response?.data?.error || error.message || '读取 Caddyfile 失败'
    caddyActiveTab.value = 'result'
    ElMessage.error('读取 Caddyfile 失败')
  } finally {
    caddyLoading.value = false
  }
}

const handleSaveCaddyfile = async () => {
  if (!currentCaddyProxyId.value) return
  
  if (!caddyfileContent.value.trim()) {
    ElMessage.warning('Caddyfile 内容不能为空')
    return
  }
  
  caddyLoading.value = true
  caddyResult.value = ''
  caddyResultDetail.value = ''
  
  try {
    const response = await api.post(`/proxies/${currentCaddyProxyId.value}/update_caddyfile/`, {
      content: caddyfileContent.value
    })
    
    if (response.data.message) {
      caddyResult.value = '保存成功'
      caddyResultType.value = 'success'
      caddyResultDetail.value = response.data.result || response.data.message
      ElMessage.success('Caddyfile 保存并验证成功')
    } else {
      caddyResult.value = '保存失败'
      caddyResultType.value = 'error'
      caddyResultDetail.value = response.data.error || response.data.result || '保存失败'
      ElMessage.error('Caddyfile 保存失败')
    }
    caddyActiveTab.value = 'result'
  } catch (error) {
    caddyResult.value = '保存失败'
    caddyResultType.value = 'error'
    caddyResultDetail.value = error.response?.data?.error || error.response?.data?.result || error.message || '保存 Caddyfile 失败'
    caddyActiveTab.value = 'result'
    ElMessage.error('保存 Caddyfile 失败')
  } finally {
    caddyLoading.value = false
  }
}

const handleValidateCaddyfile = async () => {
  if (!currentCaddyProxyId.value) return
  
  caddyLoading.value = true
  caddyResult.value = ''
  caddyResultDetail.value = ''
  
  try {
    const response = await api.post(`/proxies/${currentCaddyProxyId.value}/validate_caddyfile/`)
    
    if (response.data.valid) {
      caddyResult.value = '配置验证成功'
      caddyResultType.value = 'success'
      caddyResultDetail.value = response.data.result || response.data.message || '配置验证成功'
      ElMessage.success('Caddyfile 配置验证成功')
    } else {
      caddyResult.value = '配置验证失败'
      caddyResultType.value = 'error'
      caddyResultDetail.value = response.data.error || response.data.result || '配置验证失败'
      ElMessage.error('Caddyfile 配置验证失败')
    }
    caddyActiveTab.value = 'result'
  } catch (error) {
    caddyResult.value = '验证失败'
    caddyResultType.value = 'error'
    caddyResultDetail.value = error.response?.data?.error || error.response?.data?.result || error.message || '验证 Caddyfile 失败'
    caddyActiveTab.value = 'result'
    ElMessage.error('验证 Caddyfile 失败')
  } finally {
    caddyLoading.value = false
  }
}

const handleReloadCaddy = async () => {
  if (!currentCaddyProxyId.value) return
  
  caddyLoading.value = true
  caddyResult.value = ''
  caddyResultDetail.value = ''
  
  try {
    const response = await api.post(`/proxies/${currentCaddyProxyId.value}/reload_caddy/`)
    
    if (response.data.message) {
      caddyResult.value = '重载成功'
      caddyResultType.value = 'success'
      caddyResultDetail.value = response.data.result || response.data.message
      ElMessage.success('Caddy 重载成功')
    } else {
      caddyResult.value = '重载失败'
      caddyResultType.value = 'error'
      caddyResultDetail.value = response.data.error || response.data.result || '重载失败'
      ElMessage.error('Caddy 重载失败')
    }
    caddyActiveTab.value = 'result'
  } catch (error) {
    caddyResult.value = '重载失败'
    caddyResultType.value = 'error'
    caddyResultDetail.value = error.response?.data?.error || error.response?.data?.result || error.message || '重载 Caddy 失败'
    caddyActiveTab.value = 'result'
    ElMessage.error('重载 Caddy 失败')
  } finally {
    caddyLoading.value = false
  }
}

const resetCaddyForm = () => {
  caddyfileContent.value = ''
  caddyResult.value = ''
  caddyResultDetail.value = ''
  caddyActiveTab.value = 'edit'
  currentCaddyProxyId.value = null
  certificates.value = []
}

// 证书管理相关函数
const handleLoadCertificates = async () => {
  if (!currentCaddyProxyId.value) return
  
  try {
    const response = await api.get(`/proxies/${currentCaddyProxyId.value}/list_certificates/`)
    if (response.data.certificates) {
      certificates.value = response.data.certificates
    } else {
      certificates.value = []
    }
  } catch (error) {
    console.error('加载证书列表失败:', error)
    certificates.value = []
    ElMessage.error('加载证书列表失败')
  }
}

const handleAddCertificate = () => {
  certEditing.value = false
  resetCertForm()
  certDialogVisible.value = true
}

const handleEditCertificate = async (row) => {
  certEditing.value = true
  certForm.domain = row.domain
  certForm.cert_path = row.cert_path
  certForm.key_path = row.key_path
  certForm.cert_content = ''
  certForm.key_content = ''
  certDialogVisible.value = true
  
  // 读取证书内容
  certLoading.value = true
  try {
    const response = await api.get(`/proxies/${currentCaddyProxyId.value}/get_certificate/`, {
      params: {
        cert_path: row.cert_path,
        key_path: row.key_path
      }
    })
    if (response.data.cert_content && response.data.key_content) {
      certForm.cert_content = response.data.cert_content
      certForm.key_content = response.data.key_content
    } else {
      ElMessage.warning('读取证书内容失败，请手动输入')
    }
  } catch (error) {
    console.error('读取证书失败:', error)
    ElMessage.warning('读取证书内容失败，请手动输入')
  } finally {
    certLoading.value = false
  }
}

const handleSaveCertificate = async () => {
  if (!certForm.domain || !certForm.cert_path || !certForm.key_path) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  if (!certForm.cert_content || !certForm.key_content) {
    ElMessage.warning('请填写证书和密钥内容')
    return
  }
  
  certLoading.value = true
  try {
    const response = await api.post(`/proxies/${currentCaddyProxyId.value}/upload_certificate/`, {
      domain: certForm.domain,
      cert_path: certForm.cert_path,
      key_path: certForm.key_path,
      cert_content: certForm.cert_content,
      key_content: certForm.key_content
    })
    
    if (response.data.message) {
      ElMessage.success('证书保存成功')
      certDialogVisible.value = false
      // 重新加载证书列表
      handleLoadCertificates()
    } else {
      ElMessage.error(response.data.error || '证书保存失败')
    }
  } catch (error) {
    console.error('保存证书失败:', error)
    ElMessage.error(error.response?.data?.error || '证书保存失败')
  } finally {
    certLoading.value = false
  }
}

const handleDeleteCertificate = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除证书 "${row.domain}" 吗？\n证书路径: ${row.cert_path}\n密钥路径: ${row.key_path}`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    const response = await api.delete(`/proxies/${currentCaddyProxyId.value}/delete_certificate/`, {
      data: {
        cert_path: row.cert_path,
        key_path: row.key_path
      }
    })
    
    if (response.data.message) {
      ElMessage.success('证书删除成功')
      // 重新加载证书列表
      handleLoadCertificates()
    } else {
      ElMessage.error(response.data.error || '证书删除失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除证书失败:', error)
      ElMessage.error(error.response?.data?.error || '证书删除失败')
    }
  }
}

const resetCertForm = () => {
  certForm.domain = ''
  certForm.cert_path = ''
  certForm.key_path = ''
  certForm.cert_content = ''
  certForm.key_content = ''
  certEditing.value = false
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
  fetchProxies().then(() => {
    // 检查是否有部署中的节点，如果有则启动自动刷新
    const hasRunning = proxies.value.some(p => p.deployment_status === 'running')
    if (hasRunning) {
      startAutoRefresh()
    }
  })
  fetchServers()
})

// 组件卸载时清理定时器
onUnmounted(() => {
  stopAutoRefresh()
  stopLogAutoRefresh()
})

// 监听日志对话框关闭
watch(logDialogVisible, (visible) => {
  if (!visible) {
    stopLogAutoRefresh()
    currentProxyId.value = null
  }
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

/* 代理节点表单优化样式 */
.proxy-form {
  padding: 16px 20px;
}

.proxy-form .form-row-two-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 6px;
}

.proxy-form .form-row-two-cols .el-form-item {
  margin-bottom: 18px;
}

.proxy-form .form-row-three-cols {
  display: grid;
  grid-template-columns: 1.8fr 1.5fr 1fr;
  gap: 12px;
  margin-bottom: 6px;
}

.proxy-form .form-row-three-cols .el-form-item {
  margin-bottom: 18px;
}

/* 表单项样式 */
.proxy-form :deep(.el-form-item__label) {
  font-size: 14px;
  padding-right: 8px;
}

.proxy-form :deep(.el-form-item__content) {
  font-size: 14px;
}

.proxy-form :deep(.el-input__inner),
.proxy-form :deep(.el-textarea__inner) {
  font-size: 14px;
}

.proxy-form .form-tip {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}

/* Divider样式 */
.proxy-form :deep(.el-divider) {
  margin: 22px 0 16px 0;
}

.proxy-form :deep(.el-divider.first-divider) {
  margin-top: 0;
}

.proxy-form :deep(.el-divider__text) {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  background: #fff;
  padding: 0 12px;
}

/* 对话框样式 */
.proxy-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.proxy-dialog :deep(.el-tabs__content) {
  padding: 0;
}
</style>

