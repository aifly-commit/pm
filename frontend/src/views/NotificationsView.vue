<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { fmtTime } from '../format'

const emit = defineEmits(['notification-may-change'])
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const unreadOnly = ref(false)
const page = reactive({ page: 1, page_size: 20 })

const typeMeta = {
  stage_due_soon: { label: '临期提醒', type: 'warning' },
  stage_overdue: { label: '环节逾期', type: 'danger' },
  stage_start_soon: { label: '临开始', type: 'info' },
  status_changed: { label: '状态变更', type: 'primary' },
}

async function load() {
  loading.value = true
  try {
    const params = { ...page }
    if (unreadOnly.value) params.unread_only = 'true'
    const data = await api.get('/notifications?' + new URLSearchParams(params))
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function markRead(row) {
  try {
    await api.post(`/notifications/${row.id}/read`)
    row.is_read = true
    emit('notification-may-change')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function readAll() {
  try {
    await api.post('/notifications/read-all')
    ElMessage.success('已全部标记为已读')
    await load()
    emit('notification-may-change')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div style="display: flex; justify-content: space-between; align-items: center">
        <b>通知中心</b>
        <div style="display: flex; gap: 12px">
          <el-switch v-model="unreadOnly" active-text="只看未读" @change="load" />
          <el-button size="small" @click="readAll">全部已读</el-button>
        </div>
      </div>
    </template>
    <el-table :data="rows" v-loading="loading">
      <el-table-column label="类型" width="110">
        <template #default="{ row }">
          <el-tag :type="typeMeta[row.type]?.type || 'info'" size="small">{{ typeMeta[row.type]?.label || row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="内容" min-width="380">
        <template #default="{ row }">
          <div :style="{ fontWeight: row.is_read ? 400 : 600 }">
            {{ row.title }}
            <div style="color: #909399; font-size: 13px; font-weight: 400">{{ row.content }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180">
        <template #default="{ row }">
          <router-link v-if="row.requirement_id" :to="`/requirements/${row.requirement_id}`" style="margin-right: 10px">
            <el-button size="small" link type="primary">查看需求</el-button>
          </router-link>
          <el-button v-if="!row.is_read" size="small" link @click="markRead(row)">标为已读</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page.page"
      :page-size="page.page_size"
      :total="total"
      layout="total, prev, pager, next"
      style="margin-top: 16px; justify-content: flex-end"
      @current-change="load"
    />
  </el-card>
</template>
