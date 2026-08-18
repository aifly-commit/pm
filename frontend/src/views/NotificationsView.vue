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
  <div class="page">
    <div class="page-header">
      <div class="page-heading">
        <h2 class="page-title">通知中心</h2>
        <p class="page-sub">环节临期 / 逾期提醒与状态变更通知</p>
      </div>
      <div class="controls">
        <el-switch v-model="unreadOnly" active-text="只看未读" @change="load" />
        <el-button size="small" @click="readAll">全部已读</el-button>
      </div>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading">
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="typeMeta[row.type]?.type || 'info'" size="small" round>{{ typeMeta[row.type]?.label || row.type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="内容" min-width="380">
          <template #default="{ row }">
            <div class="noti" :class="{ unread: !row.is_read }">
              <span class="dot" v-if="!row.is_read" />
              <div class="noti-body">
                <div class="noti-title">{{ row.title }}</div>
                <div class="noti-content">{{ row.content }}</div>
              </div>
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
        class="pager"
        @current-change="load"
      />
    </el-card>
  </div>
</template>

<style scoped>
.controls {
  display: flex;
  gap: 12px;
  align-items: center;
}

.table-card :deep(.el-card__body) {
  padding: 8px 12px 16px;
}

.noti {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--pm-primary);
  margin-top: 7px;
  flex-shrink: 0;
}

.noti-title {
  font-weight: 400;
  color: #4b5668;
}

.noti.unread .noti-title {
  font-weight: 600;
  color: var(--pm-text-main);
}

.noti-content {
  color: var(--pm-text-sub);
  font-size: 13px;
  font-weight: 400;
  margin-top: 2px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
