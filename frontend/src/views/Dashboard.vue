<template>
  <div class="dashboard">
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-value">{{ stats.servers }}</div>
            <div class="stat-label">服务器总数</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-value">{{ stats.proxies }}</div>
            <div class="stat-label">代理节点</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-value">{{ stats.subscriptions }}</div>
            <div class="stat-label">订阅链接</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card>
          <div class="stat-item">
            <div class="stat-value">{{ stats.deployments }}</div>
            <div class="stat-label">部署任务</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api'

const stats = ref({
  servers: 0,
  proxies: 0,
  subscriptions: 0,
  deployments: 0
})

const fetchStats = async () => {
  try {
    const [serversRes, proxiesRes, subscriptionsRes, deploymentsRes] = await Promise.all([
      api.get('/servers/'),
      api.get('/proxies/'),
      api.get('/subscriptions/'),
      api.get('/deployments/')
    ])
    
    // DRF 可能返回 {count: number, results: []} 或直接返回数组
    const getCount = (data) => {
      if (data.count !== undefined) return data.count
      if (Array.isArray(data)) return data.length
      if (data.results && Array.isArray(data.results)) return data.results.length
      return 0
    }
    
    stats.value = {
      servers: getCount(serversRes.data),
      proxies: getCount(proxiesRes.data),
      subscriptions: getCount(subscriptionsRes.data),
      deployments: getCount(deploymentsRes.data)
    }
  } catch (error) {
    console.error('获取统计信息失败:', error)
    // 发生错误时保持默认值 0
  }
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.dashboard {
  padding: 20px;
}

.stat-item {
  text-align: center;
}

.stat-value {
  font-size: 36px;
  font-weight: bold;
  color: #409eff;
  margin-bottom: 10px;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}
</style>

