<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const groups = ref([])
const dirty = ref({})
const saving = ref(false)

async function load() {
  const data = await api.configs()
  groups.value = data.groups
  dirty.value = {}
}

function mark(key) { dirty.value = { ...dirty.value, [key]: true } }

async function save() {
  const updates = {}
  for (const g of groups.value) {
    for (const it of g.items) {
      const v = it.value
      if (dirty.value[it.key] !== undefined) updates[it.key] = v
    }
  }
  if (!Object.keys(updates).length) return ElMessage.info('没有改动')
  saving.value = true
  try {
    const res = await api.updateConfigs(updates)
    ElMessage.success(res.effective === 'hot'
      ? `已保存 ${res.updated} 项，立即生效`
      : `已保存 ${res.updated} 项，部分需重启：${res.restart_keys.join(', ')}`)
    await load()
  } finally {
    saving.value = false
  }
}

function control(it) {
  if (it.type === 'bool') return 'switch'
  if (it.type === 'enum') return 'select'
  if (it.type === 'json') return 'json'
  return 'number'
}

onMounted(load)
</script>

<template>
  <div>
    <el-alert
      type="info" :closable="false" show-icon class="mb"
      title="参数保存后立即写入数据库并留审计；标注「需重启」的项要重启服务才生效"
    />

    <el-card v-for="g in groups" :key="g.group" shadow="never" class="mb">
      <template #header>{{ g.label }}（{{ g.group }}）</template>
      <el-table :data="g.items" size="small">
        <el-table-column prop="key" label="配置项" width="280">
          <template #default="{ row }"><code>{{ row.key }}</code></template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="260" show-overflow-tooltip />
        <el-table-column label="值" width="260">
          <template #default="{ row }">
            <el-switch v-if="control(row) === 'switch'" v-model="row.value" @change="mark(row.key)" />
            <el-select v-else-if="control(row) === 'select'" v-model="row.value" @change="mark(row.key)">
              <el-option v-for="v in row.enum_values" :key="v" :label="v" :value="v" />
            </el-select>
            <el-input-number
              v-else-if="control(row) === 'number'" v-model="row.value"
              :min="row.min ?? undefined" :max="row.max ?? undefined"
              :step="row.type === 'float' ? 0.01 : 1" :precision="row.type === 'float' ? 2 : 0"
              @change="mark(row.key)"
            />
            <el-input v-else v-model="row.value" @change="mark(row.key)" />
          </template>
        </el-table-column>
        <el-table-column label="范围 / 枚举" width="200">
          <template #default="{ row }">
            <span class="muted">{{ row.enum_values ? row.enum_values.join(' / ') : (row.min !== null ? row.min + ' ~ ' + row.max : '—') }}</span>
          </template>
        </el-table-column>
        <el-table-column label="热更新" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.hot_reloadable ? 'success' : 'info'">
              {{ row.hot_reloadable ? '是' : '需重启' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <div class="footer">
      <el-button type="primary" :loading="saving" @click="save">保存改动</el-button>
      <el-button @click="load">放弃并刷新</el-button>
    </div>
  </div>
</template>

<style scoped>
.mb { margin-bottom: 14px; }
.muted { color: #909399; font-size: 12px; }
.footer { position: sticky; bottom: 0; background: #f5f7fa; padding: 12px 0; }
</style>
