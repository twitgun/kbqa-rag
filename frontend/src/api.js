import axios from 'axios'
import { ElMessage } from 'element-plus'

const client = axios.create({ baseURL: '/api/v1', timeout: 120000 })

client.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && body.code === 0) return body.data
    const msg = body?.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(new Error(msg))
  },
  (err) => {
    const msg = err.response ? `请求失败（HTTP ${err.response.status}）` : '无法连接本地服务'
    ElMessage.error(msg)
    return Promise.reject(err)
  },
)

export const api = {
  health: () => client.get('/system/health'),
  stats: () => client.get('/system/stats'),
  documents: (params) => client.get('/documents', { params }),
  document: (id) => client.get(`/documents/${id}`),
  chunks: (id, params) => client.get(`/documents/${id}/chunks`, { params }),
  upload: (file, autoIndex = true) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('auto_index', String(autoIndex))
    return client.post('/documents/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  removeDoc: (id) => client.delete(`/documents/${id}`),
  reindex: (id) => client.post(`/documents/${id}/reindex`),
  job: (id) => client.get(`/jobs/${id}`),
  search: (query, topK = 10) => client.post('/retrieval/search', { query, top_k: topK }),
  ask: (question, sessionId = null) =>
    client.post('/chat/ask', { question, session_id: sessionId }),
  sessions: () => client.get('/sessions'),
  messages: (id) => client.get(`/sessions/${id}/messages`),
  datasets: () => client.get('/eval/datasets'),
  runs: () => client.get('/eval/runs'),
  createRun: (payload) => client.post('/eval/runs', payload),
  report: (id) => client.get(`/eval/runs/${id}/report`),
  logs: (params) => client.get('/logs/qa', { params }),
  logDetail: (id) => client.get(`/logs/qa/${id}`),
  configs: () => client.get('/configs'),
  updateConfigs: (updates) => client.put('/configs', { updates }),
  feedback: (qaId, rating, reasonCode, comment) =>
    client.post('/feedback', { qa_id: qaId, rating, reason_code: reasonCode, comment }),
}

export default client
