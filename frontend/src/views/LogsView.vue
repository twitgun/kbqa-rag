<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const filters = ref({ is_fallback: null, reason: '', keyword: '' })
const detail = ref(null)
const drawer = ref(false)

async function load() {
  const params = { page: page.value, size: 20 }
  if (filters.value.is_fallback !== null) params.is_fallback = filters.value.is_fallback
  if (filters.value.reason) params.reason = filters.value.reason
  if (filters.value.keyword) params.keyword = filters.value.keyword
  const data = await api.logs(params)
  rows.value = data.items
  total.value = data.total
}

async function open(row) {
  detail.value = await api.logDetail(row.id)
  drawer.value = true
}

function exportCsv() {
  window.open('/api/v1/logs/qa/export?fmt=csv', '_blank')
}

onMounted(load)
</script>

<template>
  <div>
    <el-card shadow="never">
      <div class="toolbar">
        <el-select v-model="filters.is_fallback" placeholder="全部状态" clearable style="width: 130px">
          <el-option label="正常作答" :value="false" />
          <el-option label="兜底" :value="true" />
        </el-select>
        <el-select v-model="filters.reason" placeholder="兜底原因" clearable style="width: 180px">
          <el-option label="证据不足" value="insufficient_evidence" />
          <el-option label="模型不可用" value="llm_unavailable" />
          <el-option label="校验失败" value="validation_failed" />
        </el-select>
        <el-input v-model="filters.keyword" placeholder="问题关键字" clearable style="width: 220px" @change="page = 1; load()" />
        <el-button @click="page = 1; load()">查询</el-button>
        <span class="spacer" />
        <el-button @click="exportCsv">导出 CSV</el-button>
      </div>

      <el-table :data="rows" size="small">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="answer_preview" label="答案摘要" min-width="240" show-overflow-tooltip />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.fallback_reason" type="warning" size="small">{{ row.fallback_reason }}</el-tag>
            <el-tag v-else type="success" size="small">正常</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="max_score" label="max_score" width="110" />
        <el-table-column prop="latency_ms" label="耗时(ms)" width="100" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination v-model:current-page="page" :page-size="20" :total="total"
                     layout="total, prev, pager, next" @current-change="load" />
    </el-card>

    <el-drawer v-model="drawer" size="46%" title="问答详情">
      <template v-if="detail">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="问题">{{ detail.question }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.rewritten_question" label="改写">{{ detail.rewritten_question }}</el-descriptions-item>
          <el-descriptions-item label="答案">{{ detail.answer }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.answer_status }} / {{ detail.fallback_reason || '—' }}</el-descriptions-item>
          <el-descriptions-item label="检索">{{ JSON.stringify(detail.retrieval_meta) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ JSON.stringify(detail.latency_breakdown) }}</el-descriptions-item>
          <el-descriptions-item label="配置快照">{{ JSON.stringify(detail.config_snapshot).slice(0, 300) }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.spacer { flex: 1; }
</style>
