<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from './api'

const route = useRoute()
const health = ref(null)
const title = computed(() => route.meta?.title || '知源')

onMounted(async () => {
  try { health.value = await api.health() } catch { health.value = null }
})

const statusType = computed(() => {
  const s = health.value?.status
  if (s === 'ok') return 'success'
  if (s === 'degraded') return 'warning'
  return 'danger'
})
const statusText = computed(() => ({
  ok: '运行正常', degraded: '部分降级', down: '服务不可用',
}[health.value?.status] || '未连接'))
</script>

<template>
  <el-container class="app">
    <el-aside width="200px" class="aside">
      <div class="brand">
        <div class="logo">知源</div>
        <div class="sub">知识库问答</div>
      </div>
      <el-menu :default-active="route.path" router class="menu">
        <el-menu-item index="/chat">问答</el-menu-item>
        <el-menu-item index="/knowledge">知识库</el-menu-item>
        <el-menu-item index="/eval">评测台</el-menu-item>
        <el-menu-item index="/logs">问答日志</el-menu-item>`n        <el-menu-item index="/config">参数配置</el-menu-item>`n        <el-menu-item index="/system">系统状态</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="page-title">{{ title }}</span>
        <span class="spacer" />
        <el-tag :type="statusType" effect="plain">{{ statusText }}</el-tag>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style>
html, body, #app { height: 100%; margin: 0; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; background: #f5f7fa; }
.app { height: 100%; }
.aside { background: #1f2d3d; color: #fff; }
.brand { padding: 20px 18px 12px; }
.logo { font-size: 20px; font-weight: 600; letter-spacing: 2px; }
.sub { font-size: 12px; color: #8fa3b8; margin-top: 4px; }
.menu { border-right: none; background: transparent; }
.menu .el-menu-item { color: #c8d3e0; }
.menu .el-menu-item.is-active { color: #fff; background: #2b3d52; }
.header { background: #fff; border-bottom: 1px solid #e6e8eb; display: flex; align-items: center; gap: 12px; }
.page-title { font-weight: 600; }
.spacer { flex: 1; }
.main { padding: 18px; }
</style>
