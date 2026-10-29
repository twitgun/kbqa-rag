<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'

const health = ref(null)
const stats = ref(null)
let timer = null

const label = { mysql: 'MySQL', chroma: '向量库', bm25: 'BM25', embedding: '向量模型', reranker: '重排模型', deepseek: 'DeepSeek', disk: '磁盘' }

async function load() {
  try {
    health.value = await api.health()
    stats.value = await api.stats()
  } catch { /* 拦截器已提示 */ }
}

const type = (s) => ({ ok: 'success', degraded: 'warning', down: 'danger' }[s] || 'info')

onMounted(() => { load(); timer = setInterval(load, 10000) })
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <el-card shadow="never">
      <template #header>依赖健康</template>
      <div class="grid">
        <div v-for="c in health?.checks || []" :key="c.name" class="cell">
          <div class="name">{{ label[c.name] || c.name }}</div>
          <el-tag :type="type(c.status)" size="small">{{ c.status }}</el-tag>
          <div class="detail">{{ c.detail }}</div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="mt">
      <template #header>运行统计</template>
      <el-row :gutter="16">
        <el-col :span="4"><el-statistic title="文档" :value="stats?.documents?.total ?? 0" /></el-col>
        <el-col :span="4"><el-statistic title="片段" :value="stats?.chunks ?? 0" /></el-col>
        <el-col :span="4"><el-statistic title="会话" :value="stats?.sessions ?? 0" /></el-col>
        <el-col :span="4"><el-statistic title="问答" :value="stats?.qa?.total ?? 0" /></el-col>
        <el-col :span="4"><el-statistic title="兜底率" :value="stats?.qa?.fallback_rate ?? 0" /></el-col>
        <el-col :span="4"><el-statistic title="版本" :value="health?.version ?? '-'" /></el-col>
      </el-row>
    </el-card>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.cell { border: 1px solid #e6e8eb; border-radius: 6px; padding: 12px; }
.name { font-weight: 600; margin-bottom: 6px; }
.detail { font-size: 12px; color: #909399; margin-top: 6px; word-break: break-all; }
.mt { margin-top: 14px; }
</style>
