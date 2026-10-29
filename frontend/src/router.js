import { createRouter, createWebHashHistory } from 'vue-router'
import ChatView from './views/ChatView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import EvalView from './views/EvalView.vue'
import SystemView from './views/SystemView.vue'
import LogsView from './views/LogsView.vue'
import ConfigView from './views/ConfigView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', component: ChatView, meta: { title: '问答' } },
  { path: '/knowledge', component: KnowledgeView, meta: { title: '知识库' } },
  { path: '/eval', component: EvalView, meta: { title: '评测台' } },
  { path: '/logs', component: LogsView, meta: { title: '问答日志' } },
  { path: '/config', component: ConfigView, meta: { title: '参数配置' } },
  { path: '/system', component: SystemView, meta: { title: '系统状态' } },
]

export default createRouter({ history: createWebHashHistory(), routes })
