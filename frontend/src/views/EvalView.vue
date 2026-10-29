<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const datasets = ref([])
const runs = ref([])
const selected = ref(null)
const modes = ref(['L4'])
const report = ref(null)
const busy = ref(false)

async function load() {
  datasets.value = (await api.datasets()).items
  runs.value = (await api.runs()).items
}

async function start() {
  if (!selected.value) return ElMessage.warning('先选一个数据集')
  busy.value = true
  try {
    const { run_id } = await api.createRun({ dataset_id: selected.value, modes: modes.value, name: `run-${Date.now()}` })
    ElMessage.success('已提交评测')
    await waitRun(run_id)
  } finally {
    busy.value = false
  }
}

async function waitRun(runId) {
  for (let i = 0; i < 600; i++) {
    const run = runs.value.find((r) => r.run_id === runId)
    if (run && ['succeeded', 'failed', 'partial'].includes(run.status)) {
      await showReport(runId)
      return
    }
    await new Promise((r) => setTimeout(r, 2000))
    await load()
  }
}

async function showReport(runId) {
  report.value = await api.report(runId)
}

onMounted(load)
</script>

<template>
  <div class="eval">
    <el-card shadow="never">
      <template #header>新建评测</template>
      <div class="row">
        <span>数据集</span>
        <el-select v-model="selected" placeholder="选择数据集" style="width: 260px">
          <el-option v-for="d in datasets" :key="d.id" :label="`${d.name}（${d.question_count} 题）`" :value="d.id" />
        </el-select>
        <span>模式</span>
        <el-checkbox-group v-model="modes">
          <el-checkbox value="L1">L1 纯模型</el-checkbox>
          <el-checkbox value="L2">L2 +检索</el-checkbox>
          <el-checkbox value="L3">L3 +约束</el-checkbox>
          <el-checkbox value="L4">L4 全机制</el-checkbox>
        </el-checkbox-group>
        <el-button type="primary" :loading="busy" @click="start">开始评测</el-button>
      </div>
      <el-alert
        type="info" :closable="false" show-icon
        title="L1/L2 仅校验结构，L3/L4 做引用校验与兜底——这是对照实验的自变量"
      />
    </el-card>

    <el-card shadow="never" class="mt">
      <template #header>历史批次</template>
      <el-table :data="runs" size="small">
        <el-table-column prop="run_id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column label="进度" width="120">
          <template #default="{ row }">{{ row.finished }}/{{ row.total }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="primary" @click="showReport(row.run_id)">报告</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="report" shadow="never" class="mt">
      <template #header>评测报告 · {{ report.dataset }}</template>
      <el-table :data="Object.entries(report.metrics).map(([m, v]) => ({ mode: m, ...v }))" size="small">
        <el-table-column prop="mode" label="模式" width="80" />
        <el-table-column prop="accuracy" label="正确率" width="100" />
        <el-table-column prop="partial" label="部分正确" width="110" />
        <el-table-column prop="error" label="错误率" width="100" />
        <el-table-column prop="hallucination_rate" label="幻觉率" width="100" />
        <el-table-column prop="abstention_accuracy" label="正确拒答" width="110" />
        <el-table-column prop="false_abstention" label="误拒率" width="100" />
        <el-table-column prop="recall5" label="Recall@5" width="110" />
        <el-table-column prop="p50_ms" label="P50(ms)" width="100" />
        <el-table-column prop="p95_ms" label="P95(ms)" width="100" />
      </el-table>
      <el-alert
        class="mt" type="warning" :closable="false" show-icon
        title="未接入 LLM 时所有可答题都会走 llm_unavailable 兜底，正确率必然为 0——这是环境限制，不是系统缺陷"
      />
    </el-card>
  </div>
</template>

<style scoped>
.row { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 10px; }
.mt { margin-top: 14px; }
</style>
