<template>
  <div class="cloudflare-dns-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>Cloudflare DNS 管理</span>
          <el-button type="primary" @click="loadAllData">刷新</el-button>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <!-- Cloudflare 账户配置 -->
        <el-tab-pane label="账户配置" name="accounts">
          <div class="accounts-container">
            <div class="toolbar">
              <el-button type="primary" @click="handleAddAccount">添加账户</el-button>
              <el-button @click="loadAccounts">刷新</el-button>
            </div>

            <el-table
              :data="accounts"
              v-loading="accountsLoading"
              stripe
              style="width: 100%; margin-top: 20px"
            >
              <el-table-column prop="name" label="账户名称" width="150" />
              <el-table-column prop="account_name" label="Cloudflare账户" width="200" />
              <el-table-column prop="account_id" label="账户ID" width="150" />
              <el-table-column prop="is_active" label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">
                    {{ row.is_active ? '启用' : '禁用' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="last_check" label="最后检查" width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.last_check) }}
                </template>
              </el-table-column>
              <el-table-column prop="last_check_status" label="检查状态" width="120">
                <template #default="{ row }">
                  <el-tag v-if="row.last_check_status" :type="row.last_check_status === 'success' ? 'success' : 'danger'">
                    {{ row.last_check_status === 'success' ? '正常' : '失败' }}
                  </el-tag>
                  <span v-else style="color: #909399;">-</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="250" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="handleTestAccount(row)">测试连接</el-button>
                  <el-button size="small" @click="handleEditAccount(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="handleDeleteAccount(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 域名（Zone）管理 -->
        <el-tab-pane label="域名管理" name="zones">
          <div class="zones-container">
            <div class="toolbar">
              <el-button type="primary" @click="handleSyncZones">同步域名</el-button>
              <el-button @click="loadZones">刷新</el-button>
            </div>

            <el-table
              :data="zones"
              v-loading="zonesLoading"
              stripe
              style="width: 100%; margin-top: 20px"
            >
              <el-table-column prop="zone_name" label="域名" width="200">
                <template #default="{ row }">
                  <code style="font-size: 14px; font-weight: bold;">{{ row.zone_name }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="account_name" label="账户" width="150" />
              <el-table-column prop="status" label="状态" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'active' ? 'success' : 'warning'">
                    {{ row.status || '-' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="is_active" label="启用" width="100">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.is_active"
                    @change="handleToggleZone(row)"
                    :loading="row.toggling"
                  />
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="创建时间" width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="viewZoneDNSRecords(row)">查看DNS记录</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- DNS 记录管理 -->
        <el-tab-pane label="DNS记录" name="dns-records">
          <div class="dns-records-container">
            <div class="toolbar">
              <div class="toolbar-left">
                <el-button type="primary" @click="handleAddDNSRecord">添加记录</el-button>
                <el-button @click="loadDNSRecords">刷新</el-button>
              </div>
              <div class="toolbar-right">
                <el-select
                  v-model="dnsRecordZoneFilter"
                  placeholder="筛选域名"
                  clearable
                  style="width: 200px; margin-right: 10px"
                  @change="handleDNSRecordFilter"
                >
                  <el-option
                    v-for="zone in zones"
                    :key="zone.id"
                    :label="zone.zone_name"
                    :value="zone.id"
                  >
                    <span>{{ zone.zone_name }}</span>
                    <span style="color: #8492a6; font-size: 12px; margin-left: 8px;">({{ zone.account_name }})</span>
                  </el-option>
                </el-select>
                <el-input
                  v-model="dnsRecordSearch"
                  placeholder="搜索记录名称"
                  clearable
                  style="width: 200px"
                  @input="handleDNSRecordSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
              </div>
            </div>

            <el-table
              :data="filteredDNSRecords"
              v-loading="dnsRecordsLoading"
              stripe
              style="width: 100%; margin-top: 20px"
              :max-height="600"
            >
              <el-table-column prop="zone_name" label="域名" width="200">
                <template #default="{ row }">
                  <code>{{ row.zone_name }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="name" label="记录名称" width="200">
                <template #default="{ row }">
                  <code>{{ row.name }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="record_type" label="类型" width="100">
                <template #default="{ row }">
                  <el-tag>{{ row.record_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="content" label="内容" min-width="200" show-overflow-tooltip />
              <el-table-column prop="proxied" label="代理" width="100">
                <template #default="{ row }">
                  <el-tag :type="row.proxied ? 'success' : 'info'">
                    {{ row.proxied ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="ttl" label="TTL" width="100">
                <template #default="{ row }">
                  {{ row.ttl === 1 ? '自动' : row.ttl }}
                </template>
              </el-table-column>
              <el-table-column prop="is_active" label="状态" width="100">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.is_active"
                    @change="handleToggleDNSRecord(row)"
                    :loading="row.toggling"
                  />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="handleEditDNSRecord(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="handleDeleteDNSRecord(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- 子域名词库管理 -->
        <el-tab-pane label="子域名词库" name="subdomain-words">
          <div class="subdomain-words-container">
            <!-- 工具栏 -->
            <div class="toolbar">
              <div class="toolbar-left">
                <el-button type="primary" @click="handleAddWord">添加词</el-button>
                <el-button type="success" @click="handleBatchAdd">批量添加</el-button>
                <el-button type="info" @click="handleInitDefaults">初始化默认词库</el-button>
                <el-button @click="loadSubdomainWords">刷新</el-button>
              </div>
              <div class="toolbar-right">
                <el-input
                  v-model="searchText"
                  placeholder="搜索词或分类"
                  clearable
                  style="width: 200px; margin-right: 10px"
                  @input="handleSearch"
                >
                  <template #prefix>
                    <el-icon><Search /></el-icon>
                  </template>
                </el-input>
                <el-select
                  v-model="filterCategory"
                  placeholder="筛选分类"
                  clearable
                  style="width: 150px"
                  @change="handleFilter"
                >
                  <el-option label="全部" value="" />
                  <el-option label="通用" value="common" />
                  <el-option label="服务" value="service" />
                  <el-option label="应用" value="app" />
                  <el-option label="其他" value="other" />
                </el-select>
              </div>
            </div>

            <!-- 词库列表 -->
            <el-table
              :data="filteredSubdomainWords"
              v-loading="subdomainWordsLoading"
              stripe
              style="width: 100%; margin-top: 20px"
              :max-height="600"
            >
              <el-table-column prop="word" label="词" width="150" sortable>
                <template #default="{ row }">
                  <code style="font-size: 14px; font-weight: bold;">{{ row.word }}</code>
                </template>
              </el-table-column>
              <el-table-column prop="category" label="分类" width="120">
                <template #default="{ row }">
                  <el-tag v-if="row.category" :type="getCategoryType(row.category)">
                    {{ getCategoryText(row.category) }}
                  </el-tag>
                  <span v-else style="color: #909399;">-</span>
                </template>
              </el-table-column>
              <el-table-column prop="usage_count" label="使用次数" width="120" sortable>
                <template #default="{ row }">
                  <el-tag :type="row.usage_count > 0 ? 'success' : 'info'">
                    {{ row.usage_count }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="is_active" label="状态" width="100">
                <template #default="{ row }">
                  <el-switch
                    v-model="row.is_active"
                    @change="handleToggleActive(row)"
                    :loading="row.toggling"
                  />
                </template>
              </el-table-column>
              <el-table-column prop="created_by_username" label="创建者" width="120" />
              <el-table-column prop="created_at" label="创建时间" width="180">
                <template #default="{ row }">
                  {{ formatDateTime(row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" type="primary" @click="handleEditWord(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="handleDeleteWord(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 添加/编辑账户对话框 -->
    <el-dialog
      v-model="accountDialogVisible"
      :title="editingAccount ? '编辑账户' : '添加账户'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form
        :model="accountForm"
        label-width="120px"
      >
        <el-form-item label="账户名称" required>
          <el-input
            v-model="accountForm.name"
            placeholder="例如: 主账户、备用账户"
            maxlength="100"
          />
        </el-form-item>
        <el-form-item label="认证方式" required>
          <el-radio-group v-model="accountForm.auth_method">
            <el-radio label="token">API Token（推荐）</el-radio>
            <el-radio label="key">Global API Key + Email</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="accountForm.auth_method === 'token'" label="API Token" required>
          <el-input
            v-model="accountForm.api_token"
            type="password"
            placeholder="输入 Cloudflare API Token"
            show-password
            clearable
          />
          <div class="form-tip">在 Cloudflare 控制台创建 API Token，需要 Zone 和 DNS 编辑权限</div>
        </el-form-item>
        <template v-else>
          <el-form-item label="Global API Key" required>
            <el-input
              v-model="accountForm.api_key"
              type="password"
              placeholder="输入 Global API Key"
              show-password
              clearable
            />
          </el-form-item>
          <el-form-item label="API Email" required>
            <el-input
              v-model="accountForm.api_email"
              type="email"
              placeholder="输入 Cloudflare 账户邮箱"
              clearable
            />
          </el-form-item>
        </template>
        <el-divider />
        <el-form-item label="账户 ID">
          <el-input
            v-model="accountForm.account_id"
            placeholder="测试连接后自动获取，或手动输入"
            clearable
          />
          <div class="form-tip">Cloudflare 账户 ID，测试连接时会自动获取</div>
        </el-form-item>
        <el-form-item label="账户名称">
          <el-input
            v-model="accountForm.account_name"
            placeholder="测试连接后自动获取"
            readonly
          />
          <div class="form-tip">从 Cloudflare API 自动获取的账户名称</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveAccount" :loading="accountSaving">确定</el-button>
      </template>
    </el-dialog>

    <!-- 添加/编辑 DNS 记录对话框 -->
    <el-dialog
      v-model="dnsRecordDialogVisible"
      :title="editingDNSRecord ? '编辑DNS记录' : '添加DNS记录'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form
        :model="dnsRecordForm"
        label-width="120px"
      >
        <el-form-item label="域名" required>
          <el-select
            v-model="dnsRecordForm.zone"
            placeholder="选择域名"
            style="width: 100%"
            :disabled="!!editingDNSRecord"
          >
            <el-option
              v-for="zone in zones"
              :key="zone.id"
              :label="zone.zone_name"
              :value="zone.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="记录类型" required>
          <el-select
            v-model="dnsRecordForm.record_type"
            placeholder="选择记录类型"
            style="width: 100%"
            :disabled="!!editingDNSRecord"
          >
            <el-option label="A" value="A" />
            <el-option label="AAAA" value="AAAA" />
            <el-option label="CNAME" value="CNAME" />
          </el-select>
        </el-form-item>
        <el-form-item label="记录名称" required>
          <el-input
            v-model="dnsRecordForm.name"
            placeholder="例如: www, api, chat"
            maxlength="255"
          />
          <div class="form-tip">子域名，不包含域名后缀</div>
        </el-form-item>
        <el-form-item label="记录内容" required>
          <el-input
            v-model="dnsRecordForm.content"
            placeholder="IP地址或CNAME目标"
            maxlength="255"
          />
        </el-form-item>
        <el-form-item label="TTL">
          <el-input-number
            v-model="dnsRecordForm.ttl"
            :min="1"
            :max="86400"
            style="width: 100%"
          />
          <div class="form-tip">1 表示自动，其他值表示秒数</div>
        </el-form-item>
        <el-form-item label="启用代理">
          <el-switch v-model="dnsRecordForm.proxied" />
          <div class="form-tip">通过 Cloudflare CDN 代理流量</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dnsRecordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveDNSRecord" :loading="dnsRecordSaving">确定</el-button>
      </template>
    </el-dialog>

    <!-- 添加/编辑子域名词对话框 -->
    <el-dialog
      v-model="wordDialogVisible"
      :title="editingWord ? '编辑子域名词' : '添加子域名词'"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form
        :model="wordForm"
        label-width="100px"
      >
        <el-form-item label="词" required>
          <el-input
            v-model="wordForm.word"
            placeholder="例如: www, chat, api"
            :disabled="!!editingWord"
            maxlength="50"
            show-word-limit
          />
          <div class="form-tip">子域名词，用于生成 DNS 记录的子域名</div>
        </el-form-item>
        <el-form-item label="分类">
          <el-select
            v-model="wordForm.category"
            placeholder="选择分类（可选）"
            clearable
            style="width: 100%"
          >
            <el-option label="通用" value="common" />
            <el-option label="服务" value="service" />
            <el-option label="应用" value="app" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="wordForm.is_active" />
          <div class="form-tip">禁用后，该词将不会在随机生成时被使用</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="wordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveWord">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量添加子域名词对话框 -->
    <el-dialog
      v-model="batchAddDialogVisible"
      title="批量添加子域名词"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form
        :model="batchAddForm"
        label-width="100px"
      >
        <el-form-item label="词列表" required>
          <el-input
            v-model="batchAddForm.words"
            type="textarea"
            :rows="10"
            placeholder="每行一个词，或使用逗号、空格分隔&#10;例如：&#10;www&#10;api&#10;chat, mail, ftp"
          />
          <div class="form-tip">支持换行、逗号、空格分隔多个词</div>
        </el-form-item>
        <el-form-item label="分类">
          <el-select
            v-model="batchAddForm.category"
            placeholder="选择分类（可选，将应用到所有词）"
            clearable
            style="width: 100%"
          >
            <el-option label="通用" value="common" />
            <el-option label="服务" value="service" />
            <el-option label="应用" value="app" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchAddDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleBatchAddSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import api from '@/api'

const activeTab = ref('accounts')

// 账户相关
const accounts = ref([])
const accountsLoading = ref(false)
const accountDialogVisible = ref(false)
const editingAccount = ref(null)
const accountSaving = ref(false)
const accountForm = reactive({
  name: '',
  auth_method: 'token',
  api_token: '',
  api_key: '',
  api_email: '',
  account_id: '',
  account_name: ''
})

// 域名（Zone）相关
const zones = ref([])
const zonesLoading = ref(false)

// DNS 记录相关
const dnsRecords = ref([])
const dnsRecordsLoading = ref(false)
const dnsRecordDialogVisible = ref(false)
const editingDNSRecord = ref(null)
const dnsRecordSaving = ref(false)
const dnsRecordZoneFilter = ref('')
const dnsRecordSearch = ref('')
const dnsRecordForm = reactive({
  zone: '',
  record_type: 'A',
  name: '',
  content: '',
  ttl: 1,
  proxied: false
})

// 子域名词库相关
const subdomainWords = ref([])
const subdomainWordsLoading = ref(false)
const searchText = ref('')
const filterCategory = ref('')
const wordDialogVisible = ref(false)
const batchAddDialogVisible = ref(false)
const editingWord = ref(null)
const wordForm = reactive({
  word: '',
  category: '',
  is_active: true
})
const batchAddForm = reactive({
  words: '',
  category: ''
})

// 加载所有数据
const loadAllData = () => {
  loadAccounts()
  loadZones()
  loadDNSRecords()
  loadSubdomainWords()
}

// 账户管理
const loadAccounts = async () => {
  accountsLoading.value = true
  try {
    const response = await api.get('/settings/cloudflare/accounts/')
    const data = Array.isArray(response.data) 
      ? response.data 
      : (response.data.results || response.data || [])
    accounts.value = data
  } catch (error) {
    console.error('加载账户失败:', error)
    ElMessage.error('加载账户失败: ' + (error.response?.data?.detail || error.message))
    accounts.value = []
  } finally {
    accountsLoading.value = false
  }
}

const handleAddAccount = () => {
  editingAccount.value = null
  accountForm.name = ''
  accountForm.auth_method = 'token'
  accountForm.api_token = ''
  accountForm.api_key = ''
  accountForm.api_email = ''
  accountForm.account_id = ''
  accountForm.account_name = ''
  accountDialogVisible.value = true
}

const handleEditAccount = (row) => {
  editingAccount.value = row
  accountForm.name = row.name
  accountForm.auth_method = row.api_token ? 'token' : 'key'
  accountForm.api_token = row.api_token || ''
  accountForm.api_key = row.api_key || ''
  accountForm.api_email = row.api_email || ''
  accountForm.account_id = row.account_id || ''
  accountForm.account_name = row.account_name || ''
  accountDialogVisible.value = true
}

const handleSaveAccount = async () => {
  if (!accountForm.name || !accountForm.name.trim()) {
    ElMessage.warning('请输入账户名称')
    return
  }

  if (accountForm.auth_method === 'token' && !accountForm.api_token) {
    ElMessage.warning('请输入 API Token')
    return
  }

  if (accountForm.auth_method === 'key' && (!accountForm.api_key || !accountForm.api_email)) {
    ElMessage.warning('请输入 Global API Key 和 Email')
    return
  }

  try {
    const data = {
      name: accountForm.name,
      api_token: accountForm.auth_method === 'token' ? accountForm.api_token : null,
      api_key: accountForm.auth_method === 'key' ? accountForm.api_key : null,
      api_email: accountForm.auth_method === 'key' ? accountForm.api_email : null,
      account_id: accountForm.account_id || null,
      account_name: accountForm.account_name || null
    }

    accountSaving.value = true
    if (editingAccount.value) {
      await api.put(`/settings/cloudflare/accounts/${editingAccount.value.id}/`, data)
      ElMessage.success('更新成功')
    } else {
      await api.post('/settings/cloudflare/accounts/', data)
      ElMessage.success('添加成功')
    }
    accountDialogVisible.value = false
    loadAccounts()
  } catch (error) {
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.message))
  }
}

const handleTestAccount = async (row) => {
  try {
    const response = await api.post(`/settings/cloudflare/accounts/${row.id}/test/`)
    if (response.data.status === 'success') {
      ElMessage.success('连接测试成功')
    } else {
      ElMessage.error('连接测试失败: ' + (response.data.message || '未知错误'))
    }
    loadAccounts()
  } catch (error) {
    console.error('测试账户失败:', error)
    console.error('错误详情:', error.response?.data)
    
    // 提取错误信息
    let errorMessage = '测试失败'
    if (error.response?.data) {
      if (error.response.data.message) {
        errorMessage = error.response.data.message
      } else if (error.response.data.detail) {
        errorMessage = error.response.data.detail
      } else if (typeof error.response.data === 'string') {
        errorMessage = error.response.data
      } else {
        errorMessage = JSON.stringify(error.response.data)
      }
    } else if (error.message) {
      errorMessage = error.message
    }
    
    ElMessage.error('测试失败: ' + errorMessage)
    loadAccounts()
  }
}

const handleDeleteAccount = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除 Cloudflare 账户 "${row.name}" 吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await api.delete(`/settings/cloudflare/accounts/${row.id}/`)
    ElMessage.success('删除成功')
    loadAccounts()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除账户失败:', error)
      ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

// 域名（Zone）管理
const loadZones = async () => {
  zonesLoading.value = true
  try {
    const response = await api.get('/settings/cloudflare/zones/')
    const data = Array.isArray(response.data) 
      ? response.data 
      : (response.data.results || response.data || [])
    zones.value = data.map(zone => ({ ...zone, toggling: false }))
  } catch (error) {
    console.error('加载域名失败:', error)
    ElMessage.error('加载域名失败: ' + (error.response?.data?.detail || error.message))
    zones.value = []
  } finally {
    zonesLoading.value = false
  }
}

const handleSyncZones = async () => {
  try {
    // 选择账户
    if (accounts.value.length === 0) {
      ElMessage.warning('请先添加 Cloudflare 账户')
      return
    }
    
    let accountId = null
    if (accounts.value.length === 1) {
      accountId = accounts.value[0].id
    } else {
      // 如果有多个账户，让用户输入账户 ID
      const { value } = await ElMessageBox.prompt(
        '请输入要同步的账户 ID',
        '选择账户',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          inputPattern: /^\d+$/,
          inputErrorMessage: '请输入有效的账户 ID'
        }
      )
      accountId = parseInt(value)
    }
    
    const response = await api.post('/settings/cloudflare/zones/sync/', {
      account_id: accountId
    })
    
    ElMessage.success(response.data.message || '同步成功')
    loadZones()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('同步域名失败:', error)
      ElMessage.error('同步失败: ' + (error.response?.data?.detail || error.response?.data?.error || error.message))
    }
  }
}

const handleToggleZone = async (row) => {
  row.toggling = true
  try {
    await api.patch(`/settings/cloudflare/zones/${row.id}/`, { is_active: row.is_active })
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (error) {
    row.is_active = !row.is_active
    console.error('更新 Zone 状态失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    row.toggling = false
  }
}

const viewZoneDNSRecords = (row) => {
  activeTab.value = 'dns-records'
  dnsRecordZoneFilter.value = row.id
  handleDNSRecordFilter()
}

// DNS 记录管理
const loadDNSRecords = async () => {
  dnsRecordsLoading.value = true
  try {
    const response = await api.get('/settings/cloudflare/dns-records/')
    const data = Array.isArray(response.data) 
      ? response.data 
      : (response.data.results || response.data || [])
    dnsRecords.value = data.map(record => ({ ...record, toggling: false }))
  } catch (error) {
    console.error('加载DNS记录失败:', error)
    ElMessage.error('加载DNS记录失败: ' + (error.response?.data?.detail || error.message))
    dnsRecords.value = []
  } finally {
    dnsRecordsLoading.value = false
  }
}

const filteredDNSRecords = computed(() => {
  let filtered = dnsRecords.value

  if (dnsRecordZoneFilter.value) {
    filtered = filtered.filter(record => record.zone === dnsRecordZoneFilter.value)
  }

  if (dnsRecordSearch.value) {
    const search = dnsRecordSearch.value.toLowerCase()
    filtered = filtered.filter(record =>
      record.name.toLowerCase().includes(search) ||
      record.content.toLowerCase().includes(search)
    )
  }

  return filtered
})

const handleDNSRecordFilter = () => {
  // 过滤逻辑已在 computed 中处理
}

const handleDNSRecordSearch = () => {
  // 搜索逻辑已在 computed 中处理
}

const handleAddDNSRecord = () => {
  editingDNSRecord.value = null
  dnsRecordForm.zone = ''
  dnsRecordForm.record_type = 'A'
  dnsRecordForm.name = ''
  dnsRecordForm.content = ''
  dnsRecordForm.ttl = 1
  dnsRecordForm.proxied = false
  dnsRecordDialogVisible.value = true
}

const handleEditDNSRecord = (row) => {
  editingDNSRecord.value = row
  dnsRecordForm.zone = row.zone
  dnsRecordForm.record_type = row.record_type
  dnsRecordForm.name = row.name
  dnsRecordForm.content = row.content
  dnsRecordForm.ttl = row.ttl
  dnsRecordForm.proxied = row.proxied
  dnsRecordDialogVisible.value = true
}

const handleSaveDNSRecord = async () => {
  if (!dnsRecordForm.zone || !dnsRecordForm.name || !dnsRecordForm.content) {
    ElMessage.warning('请填写完整信息')
    return
  }

  try {
    dnsRecordSaving.value = true
    if (editingDNSRecord.value) {
      await api.put(`/settings/cloudflare/dns-records/${editingDNSRecord.value.id}/`, dnsRecordForm)
      ElMessage.success('更新成功')
    } else {
      await api.post('/settings/cloudflare/dns-records/', dnsRecordForm)
      ElMessage.success('添加成功')
    }
    dnsRecordDialogVisible.value = false
    loadDNSRecords()
  } catch (error) {
    console.error('保存DNS记录失败:', error)
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.response?.data?.error || error.message))
  } finally {
    dnsRecordSaving.value = false
  }
}

const handleToggleDNSRecord = async (row) => {
  row.toggling = true
  try {
    await api.patch(`/settings/cloudflare/dns-records/${row.id}/`, { is_active: row.is_active })
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (error) {
    row.is_active = !row.is_active
    console.error('更新DNS记录状态失败:', error)
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.response?.data?.error || error.message))
  } finally {
    row.toggling = false
  }
}

const handleDeleteDNSRecord = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除DNS记录 "${row.name}" 吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await api.delete(`/settings/cloudflare/dns-records/${row.id}/`)
    ElMessage.success('删除成功')
    loadDNSRecords()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除DNS记录失败:', error)
      ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.response?.data?.error || error.message))
    }
  }
}

// 子域名词库管理
const loadSubdomainWords = async () => {
  subdomainWordsLoading.value = true
  try {
    // 请求所有数据，不分页
    const response = await api.get('/settings/subdomain-words/', {
      params: {
        page_size: 1000  // 请求足够大的页面大小以获取所有数据
      }
    })
    
    // 调试：打印原始响应数据
    console.log('子域名词库 API 响应:', response.data)
    console.log('响应数据类型:', typeof response.data)
    console.log('是否为数组:', Array.isArray(response.data))
    console.log('是否有 results:', response.data?.results)
    
    // 处理分页结果或直接数组
    let data = []
    if (response.data) {
      if (Array.isArray(response.data)) {
        // 直接是数组
        data = response.data
        console.log('使用直接数组格式，数量:', data.length)
      } else if (response.data.results && Array.isArray(response.data.results)) {
        // 分页结果
        data = response.data.results
        console.log('使用分页结果格式，数量:', data.length)
      } else if (typeof response.data === 'object') {
        // 可能是单个对象或其他格式，尝试提取数据
        console.warn('响应数据是对象但不是分页格式:', response.data)
        // 尝试从对象中提取可能的数组字段
        if (response.data.data && Array.isArray(response.data.data)) {
          data = response.data.data
        } else {
          data = []
        }
      }
    }
    
    // 确保 data 是数组
    if (!Array.isArray(data)) {
      console.error('子域名词库数据格式异常:', response.data)
      console.error('data 类型:', typeof data, '值:', data)
      data = []
    }
    
    console.log('处理后的数据数量:', data.length)
    
    subdomainWords.value = data.map(word => ({
      ...word,
      toggling: false
    }))
    
    console.log('最终 subdomainWords 数量:', subdomainWords.value.length)
    
    // 如果词库为空，提示用户（系统会在启动时自动初始化，但如果用户删除了所有词，可以手动初始化）
    if (subdomainWords.value.length === 0) {
      console.warn('子域名词库为空，但 API 返回了数据:', response.data)
      ElMessage.info({
        message: '子域名词库为空，系统会在启动时自动初始化。如需手动初始化，请点击"初始化默认词库"按钮',
        duration: 4000,
        showClose: true
      })
    }
  } catch (error) {
    console.error('加载子域名词库失败:', error)
    console.error('错误详情:', error.response?.data)
    ElMessage.error('加载子域名词库失败: ' + (error.response?.data?.detail || error.message))
    subdomainWords.value = []
  } finally {
    subdomainWordsLoading.value = false
  }
}

const filteredSubdomainWords = computed(() => {
  let filtered = subdomainWords.value

  if (searchText.value) {
    const search = searchText.value.toLowerCase()
    filtered = filtered.filter(word =>
      word.word.toLowerCase().includes(search) ||
      (word.category && word.category.toLowerCase().includes(search))
    )
  }

  if (filterCategory.value) {
    filtered = filtered.filter(word => word.category === filterCategory.value)
  }

  return filtered
})

const handleSearch = () => {
  // 搜索逻辑已在 computed 中处理
}

const handleFilter = () => {
  // 过滤逻辑已在 computed 中处理
}

const handleAddWord = () => {
  editingWord.value = null
  wordForm.word = ''
  wordForm.category = ''
  wordForm.is_active = true
  wordDialogVisible.value = true
}

const handleEditWord = (row) => {
  editingWord.value = row
  wordForm.word = row.word
  wordForm.category = row.category || ''
  wordForm.is_active = row.is_active
  wordDialogVisible.value = true
}

const handleSaveWord = async () => {
  if (!wordForm.word || !wordForm.word.trim()) {
    ElMessage.warning('请输入子域名词')
    return
  }

  try {
    if (editingWord.value) {
      await api.put(`/settings/subdomain-words/${editingWord.value.id}/`, wordForm)
      ElMessage.success('更新成功')
    } else {
      await api.post('/settings/subdomain-words/', wordForm)
      ElMessage.success('添加成功')
    }
    wordDialogVisible.value = false
    loadSubdomainWords()
  } catch (error) {
    ElMessage.error('保存失败: ' + (error.response?.data?.detail || error.response?.data?.word?.[0] || error.message))
  }
}

const handleDeleteWord = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除子域名词 "${row.word}" 吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await api.delete(`/settings/subdomain-words/${row.id}/`)
    ElMessage.success('删除成功')
    loadSubdomainWords()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const handleToggleActive = async (row) => {
  row.toggling = true
  try {
    await api.patch(`/settings/subdomain-words/${row.id}/`, {
      is_active: row.is_active
    })
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (error) {
    row.is_active = !row.is_active
    ElMessage.error('操作失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    row.toggling = false
  }
}

const handleBatchAdd = () => {
  batchAddForm.words = ''
  batchAddForm.category = ''
  batchAddDialogVisible.value = true
}

const handleInitDefaults = async () => {
  try {
    await ElMessageBox.confirm(
      '确定要初始化默认子域名词库吗？\n\n将添加以下常用词：\n通用类：www, api, app, web, site\n服务类：chat, mail, ftp, ssh, vpn, proxy, agent, node, server, cdn\n应用类：admin, dashboard, panel, portal, console\n其他：test, dev, staging, demo\n\n已存在的词将被跳过。',
      '初始化默认词库',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }
    )
    
    const response = await api.post('/settings/subdomain-words/init-defaults/')
    const { message, created, skipped, total } = response.data
    
    let successMessage = message
    if (created.length > 0) {
      successMessage += `\n新增的词：${created.map(w => w.word).join(', ')}`
    }
    if (skipped.length > 0) {
      successMessage += `\n已存在的词：${skipped.join(', ')}`
    }
    
    ElMessage.success(successMessage)
    loadSubdomainWords()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('初始化失败: ' + (error.response?.data?.detail || error.message))
    }
  }
}

const handleBatchAddSubmit = async () => {
  if (!batchAddForm.words || !batchAddForm.words.trim()) {
    ElMessage.warning('请输入要添加的词')
    return
  }

  const wordsText = batchAddForm.words.trim()
  const wordsList = wordsText
    .split(/[\n,，\s]+/)
    .map(w => w.trim())
    .filter(w => w.length > 0)

  if (wordsList.length === 0) {
    ElMessage.warning('请输入有效的词')
    return
  }

  try {
    const wordsData = wordsList.map(word => ({
      word: word,
      category: batchAddForm.category || null
    }))

    const response = await api.post('/settings/subdomain-words/batch-add/', {
      words: wordsData
    })

    const { created, skipped, errors, summary } = response.data
    let message = `批量添加完成：成功 ${summary.created_count} 个`
    if (summary.skipped_count > 0) {
      message += `，跳过 ${summary.skipped_count} 个（已存在）`
    }
    if (summary.error_count > 0) {
      message += `，失败 ${summary.error_count} 个`
    }

    ElMessage.success(message)
    batchAddDialogVisible.value = false
    loadSubdomainWords()
  } catch (error) {
    ElMessage.error('批量添加失败: ' + (error.response?.data?.detail || error.message))
  }
}

const getCategoryType = (category) => {
  const types = {
    'common': 'primary',
    'service': 'success',
    'app': 'warning',
    'other': 'info'
  }
  return types[category] || 'info'
}

const getCategoryText = (category) => {
  const texts = {
    'common': '通用',
    'service': '服务',
    'app': '应用',
    'other': '其他'
  }
  return texts[category] || category
}

const formatDateTime = (dateTime) => {
  if (!dateTime) return '-'
  const date = new Date(dateTime)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

onMounted(() => {
  loadAllData()
})
</script>

<style scoped>
.cloudflare-dns-page {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.toolbar-left {
  display: flex;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>

