<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const status = ref('')
const keyword = ref('')
const polling = ref(true)
let timer = null

const probe = ref('')
const probing = ref(false)
const probeResult = ref(null)

async function runProbe() {
  const q = probe.value.trim()
  if (!q) return
  probing.value = true
  try {
    probeResult.value = await api.search(q, 10)
  } finally {
    probing.value = false
  }
}

const statusText = { pending: '待处理', parsing: '解析中', indexing: '索引中', ready: '就绪', failed: '失败' }
const statusType = { pending: 'info', parsing: 'warning', indexing: 'warning', ready: 'success', failed: 'danger' }

async function load() {
  const data = await api.documents({ page: page.value, size: 20, status: status.value || undefined, keyword: keyword.value || undefined })
  rows.value = data.items
  total.value = data.total
}

async function uploadFile(opt) {
  try {
    const res = await api.upload(opt.file)
    ElMessage.success(res.is_duplicate ? '文件已存在，可直接重建索引' : '已进入索引队列')
    if (res.job_id) pollJob(res.job_id)
    await load()
  } catch (e) {
    ElMessage.error('上传失败：' + e.message)
  }
}

async function pollJob(jobId) {
  for (let i = 0; i < 300; i++) {
    const job = await api.job(jobId)
    if (['succeeded', 'failed', 'canceled'].includes(job.status)) {
      job.status === 'succeeded'
        ? ElMessage.success(`索引完成：${job.document_title || ''}`)
        : ElMessage.error(`索引失败：${job.error_detail || job.status}`)
      await load()
      return
    }
    await new Promise((r) => setTimeout(r, 1000))
  }
}

async function reindex(row) {
  const jobId = (await api.reindex(row.id)).job_id
  ElMessage.info('已提交重建任务')
  pollJob(jobId)
}

async function remove(row) {
  await ElMessageBox.confirm(`将删除《${row.title}》及其 ${row.chunk_count} 个片段，不可恢复`, '确认删除', { type: 'warning' })
  await api.removeDoc(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(() => {
  load()
  timer = setInterval(() => { if (polling.value) load() }, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <el-card shadow="never" class="upload-card">
      <el-upload drag :show-file-list="false" :http-request="uploadFile" multiple accept=".md,.txt,.docx,.pdf,.xlsx">
        <div class="drop">把文档拖到这里，或点击选择</div>
        <div class="hint">支持 md / txt / docx / pdf / xlsx，单文件 ≤ 50MB</div>
      </el-upload>
    </el-card>

    <el-card shadow="never" class="upload-card probe-card">
      <template #header>
        检索测试
        <span class="hint-inline">不调用大模型，只看向量 + BM25 + RRF 的召回与打分</span>
      </template>
      <div class="probe-row">
        <el-input v-model="probe" placeholder="例如：怎么配置 CORS" @keyup.enter="runProbe" />
        <el-button type="primary" :loading="probing" @click="runProbe">检索</el-button>
      </div>

      <template v-if="probeResult">
        <div class="debug-line">
          max_score = <b>{{ probeResult.debug.max_score }}</b>
          ｜ 阈值 = <b>{{ probeResult.debug.tau }}</b>
          ｜ 判定 =
          <el-tag size="small" :type="probeResult.debug.passed ? 'success' : 'warning'">
            {{ probeResult.debug.passed ? '证据充分' : '证据不足（会触发兜底）' }}
          </el-tag>
          ｜ 耗时 {{ probeResult.debug.elapsed_ms }}ms
          ｜ 重排降级 {{ probeResult.debug.rerank_degraded }}
        </div>
        <el-table :data="probeResult.candidates" size="small" max-height="320">
          <el-table-column prop="rank" label="#" width="50" />
          <el-table-column prop="section_path" label="章节" min-width="220" show-overflow-tooltip />
          <el-table-column prop="doc_title" label="文档" width="180" show-overflow-tooltip />
          <el-table-column prop="vector_score" label="向量" width="80" />
          <el-table-column prop="bm25_score" label="BM25" width="80" />
          <el-table-column prop="rrf_score" label="RRF" width="90" />
        </el-table>
      </template>
    </el-card>

    <el-card shadow="never">
      <div class="toolbar">
        <el-radio-group v-model="status" @change="page = 1; load()">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="ready">就绪</el-radio-button>
          <el-radio-button value="indexing">索引中</el-radio-button>
          <el-radio-button value="failed">失败</el-radio-button>
        </el-radio-group>
        <el-input v-model="keyword" placeholder="按标题搜索" clearable style="width: 220px" @change="page = 1; load()" />
        <span class="spacer" />
        <el-switch v-model="polling" active-text="自动刷新" />
      </div>

      <el-table :data="rows" size="default" v-loading="false">
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="file_ext" label="格式" width="80" />
        <el-table-column prop="chunk_count" label="片段" width="90" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType[row.status]" size="small">{{ statusText[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="char_count" label="字数" width="100" />
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button link type="primary" @click="reindex(row)">重建</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <div>错误信息：{{ row.error_detail || '无' }}</div>
              <div>文件：{{ row.original_filename }}（{{ row.file_size }} 字节）</div>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page" :page-size="20" :total="total"
        layout="total, prev, pager, next" @current-change="load"
      />
    </el-card>
  </div>
</template>

<style scoped>
.upload-card { margin-bottom: 14px; }
.drop { font-size: 15px; color: #606266; padding: 12px 0; }
.hint { font-size: 12px; color: #c0c4cc; }
.toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; }
.spacer { flex: 1; }
.detail { padding: 8px 16px; color: #606266; font-size: 13px; }
.probe-card { margin-bottom: 14px; }
.hint-inline { color: #909399; font-size: 12px; font-weight: normal; margin-left: 8px; }
.probe-row { display: flex; gap: 10px; margin-bottom: 10px; }
.debug-line { font-size: 13px; color: #606266; margin-bottom: 8px; }
</style>
