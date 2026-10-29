<script setup>
import { nextTick, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const question = ref('')
const loading = ref(false)
const messages = ref([])
const sessionId = ref(null)
const bodyEl = ref(null)

async function send() {
  const q = question.value.trim()
  if (!q || loading.value) return
  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true
  scrollDown()
  try {
    const data = await api.ask(q, sessionId.value)
    sessionId.value = data.session_id
    messages.value.push({ role: 'assistant', ...data })
  } catch (e) {
    messages.value.push({ role: 'assistant', answer: '请求失败：' + e.message, answer_status: 'error' })
  } finally {
    loading.value = false
    scrollDown()
  }
}

function scrollDown() {
  nextTick(() => {
    if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight
  })
}

function scoreTag(score) {
  if (score >= 0.6) return 'success'
  if (score >= 0.45) return 'warning'
  return 'info'
}

async function rate(m, rating) {
  let reason = null
  if (rating === -1) {
    try {
      const { value } = await ElMessageBox.prompt(
        '选择错因：无依据 / 答非所问 / 引用错误 / 内容过时 / 其他',
        '反馈', { inputPlaceholder: '可留空，直接确定即为「其他」' },
      )
      reason = value || 'other'
    } catch { return }
  }
  await api.feedback(m.qa_id, rating, reason, '')
  ElMessage.success('已记录，谢谢反馈')
}
</script>

<template>
  <div class="chat">
    <div ref="bodyEl" class="messages">
      <el-empty v-if="!messages.length" description="问点什么，例如「怎么配置 CORS？」" />
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.content }}</div>

        <div v-else class="bubble bot-bubble" :class="{ fallback: m.is_fallback }">
          <div v-if="m.rewritten_question" class="rewrite">
            已理解为：{{ m.rewritten_question }}
          </div>

          <div class="answer">{{ m.answer }}</div>

          <div v-if="m.citations && m.citations.length" class="citations">
            <div class="section-title">来源</div>
            <div v-for="c in m.citations" :key="c.chunk_uid" class="citation">
              <span class="idx">[{{ c.index }}]</span>
              <span class="doc">{{ c.doc_title }}</span>
              <span class="loc">{{ c.section_path || ('第 ' + c.page_no + ' 页') }}</span>
              <el-tag size="small" :type="scoreTag(c.score)" effect="plain">
                {{ c.score }}
              </el-tag>
            </div>
          </div>

          <el-collapse v-if="m.retrieval" class="debug">
            <el-collapse-item title="检索调试">
              <div class="debug-line">
                max_score = {{ m.retrieval.max_score }}
                ｜ 阈值 = {{ m.retrieval.tau }}
                ｜ {{ m.retrieval.passed ? '通过' : '未通过（证据不足）' }}
                ｜ 重排降级 = {{ m.retrieval.rerank_degraded }}
              </div>
              <el-table :data="m.retrieval.candidates || []" size="small" max-height="220">
                <el-table-column prop="chunk_uid" label="片段" width="120" />
                <el-table-column prop="rrf" label="RRF" width="90" />
                <el-table-column prop="vector" label="向量" width="90" />
                <el-table-column prop="rerank" label="重排" width="90" />
              </el-table>
            </el-collapse-item>
          </el-collapse>

          <div class="meta">
            {{ m.latency_ms }} ms ｜ {{ m.answer_status === 'ok' ? '正常作答' : '兜底：' + m.fallback_reason }}
            <span v-if="m.qa_id" class="rate">
              <el-button link size="small" @click="rate(m, 1)">👍</el-button>
              <el-button link size="small" @click="rate(m, -1)">👎</el-button>
            </span>
          </div>
        </div>
      </div>
      <div v-if="loading" class="msg assistant">
        <div class="bubble bot-bubble loading">检索中…</div>
      </div>
    </div>

    <div class="input-bar">
      <el-input
        v-model="question"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send"
      />
      <el-button type="primary" :loading="loading" @click="send">发送</el-button>
    </div>
  </div>
</template>

<style scoped>
.chat { display: flex; flex-direction: column; height: calc(100vh - 120px); }
.messages { flex: 1; overflow-y: auto; padding-right: 8px; }
.msg { display: flex; margin-bottom: 14px; }
.msg.user { justify-content: flex-end; }
.bubble { max-width: 78%; padding: 12px 14px; border-radius: 8px; line-height: 1.7; white-space: pre-wrap; }
.user-bubble { background: #409eff; color: #fff; }
.bot-bubble { background: #fff; border: 1px solid #e6e8eb; }
.bot-bubble.fallback { background: #fdf6ec; border-color: #f5dab1; }
.rewrite { font-size: 12px; color: #909399; margin-bottom: 8px; }
.citations { margin-top: 12px; border-top: 1px dashed #e6e8eb; padding-top: 8px; }
.section-title { font-size: 12px; color: #909399; margin-bottom: 6px; }
.citation { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 3px 0; }
.idx { color: #409eff; }
.doc { font-weight: 500; }
.loc { color: #909399; font-size: 12px; }
.debug { margin-top: 10px; }
.debug-line { font-size: 12px; color: #606266; margin-bottom: 6px; }
.meta { font-size: 12px; color: #c0c4cc; margin-top: 8px; }
.input-bar { display: flex; gap: 10px; padding-top: 12px; border-top: 1px solid #e6e8eb; }
.input-bar .el-button { height: 54px; }
</style>
