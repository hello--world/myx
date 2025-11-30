<template>
  <el-container class="layout-container">
    <el-header class="header">
      <div class="header-left">
        <div class="logo-container" v-html="siteIcon || defaultIcon"></div>
        <div class="title-container">
          <h2>{{ siteTitle }}</h2>
          <span v-if="siteSubtitle" class="subtitle">{{ siteSubtitle }}</span>
        </div>
      </div>
      <div class="header-right">
        <el-dropdown @command="handleCommand">
          <span class="user-info">
            <el-icon><User /></el-icon>
            {{ authStore.user?.username }}
            <el-icon class="el-icon--right"><arrow-down /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    <el-container>
      <el-aside width="200px" class="aside">
        <el-menu
          :default-active="activeMenu"
          router
          class="menu"
        >
          <el-menu-item index="/">
            <el-icon><Odometer /></el-icon>
            <span>仪表板</span>
          </el-menu-item>
          <el-menu-item index="/servers">
            <el-icon><Monitor /></el-icon>
            <span>服务器管理</span>
          </el-menu-item>
          <el-menu-item index="/proxies">
            <el-icon><Connection /></el-icon>
            <span>代理节点</span>
          </el-menu-item>
          <el-menu-item index="/subscriptions">
            <el-icon><Link /></el-icon>
            <span>订阅管理</span>
          </el-menu-item>
          <el-menu-item index="/deployments">
            <el-icon><Tools /></el-icon>
            <span>部署任务</span>
          </el-menu-item>
          <el-menu-item index="/agents">
            <el-icon><Monitor /></el-icon>
            <span>Agent管理</span>
          </el-menu-item>
          <el-menu-item index="/settings">
            <el-icon><Setting /></el-icon>
            <span>系统设置</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { User, ArrowDown, Odometer, Monitor, Connection, Link, Tools, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeMenu = computed(() => route.path)
const siteTitle = ref('MyX - 科学技术管理平台')
const siteSubtitle = ref('')
const siteIcon = ref('')
const defaultIcon = '<img src="/favicon.svg" alt="MyX Logo" class="logo" />'

const loadSettings = async () => {
  try {
    const response = await api.get('/settings/')
    siteTitle.value = response.data.site_title || 'MyX - 科学技术管理平台'
    siteSubtitle.value = response.data.site_subtitle || ''
    siteIcon.value = response.data.site_icon || ''
    document.title = siteTitle.value
    updateFavicon()
  } catch (error) {
    console.error('加载设置失败:', error)
  }
}

const updateFavicon = () => {
  // 移除旧的favicon链接
  const oldFavicon = document.querySelector('link[rel="icon"]')
  if (oldFavicon) {
    oldFavicon.remove()
  }

  if (siteIcon.value && siteIcon.value.trim()) {
    // 创建新的favicon链接（使用SVG）
    const link = document.createElement('link')
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    // 将SVG转换为data URI
    const svgBlob = new Blob([siteIcon.value], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(svgBlob)
    link.href = url
    document.head.appendChild(link)
  } else {
    // 使用默认图标
    const link = document.createElement('link')
    link.rel = 'icon'
    link.type = 'image/svg+xml'
    link.href = '/favicon.svg'
    document.head.appendChild(link)
  }
}

const handleSettingsUpdate = (event) => {
  if (event.detail) {
    siteTitle.value = event.detail.site_title || 'MyX - 科学技术管理平台'
    siteSubtitle.value = event.detail.site_subtitle || ''
    siteIcon.value = event.detail.site_icon || ''
    document.title = siteTitle.value
    updateFavicon()
  }
}

onMounted(() => {
  loadSettings()
  window.addEventListener('settings-updated', handleSettingsUpdate)
})

onUnmounted(() => {
  window.removeEventListener('settings-updated', handleSettingsUpdate)
})

const handleCommand = async (command) => {
  if (command === 'logout') {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await authStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-left .logo-container {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-left .logo-container :deep(svg) {
  width: 32px;
  height: 32px;
}

.header-left .logo-container :deep(img) {
  width: 32px;
  height: 32px;
}

.header-left .title-container {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-left h2 {
  margin: 0;
  color: #303133;
  font-size: 18px;
  line-height: 1.2;
}

.header-left .subtitle {
  font-size: 12px;
  color: #909399;
  line-height: 1;
}

.header-right {
  display: flex;
  align-items: center;
}

.user-info {
  display: flex;
  align-items: center;
  cursor: pointer;
  color: #606266;
}

.aside {
  background: #fff;
  border-right: 1px solid #e4e7ed;
}

.menu {
  border-right: none;
}

.main {
  background: #f5f7fa;
  padding: 20px;
}
</style>

