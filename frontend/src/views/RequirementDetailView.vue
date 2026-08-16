<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, getStoredUser } from '../api'
import {
  REQ_STATUSES,
  STAGE_STATUSES,
  statusMeta,
  stageLabel,
  fmtTime,
  fmtDate,
} from '../format'

const props = defineProps({ id: { type: String, required: true } })
const emit = defineEmits(['notification-may-change'])

const detail = ref(null)
const loading = ref(false)
const users = ref([])
const me = ref(getStoredUser())

// 允许的回退路径（design.md 3.1）
const REVERT_TARGETS = {
  review: ['research'],
  testing: ['backend_dev', 'frontend_dev', 'api_dev'],
}

const canWrite = computed(() => {
  if (!detail.value || !me.value) return false
  return me.value.role === 'admin' || detail.value.responsible_pm_id === me.value.id
})

async function load() {
  loading.value = true
  try {
    detail.value = await api.get(`/requirements/${props.id}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function ensureUsers() {
  if (!users.value.length) users.value = await api.get('/users/directory')
}

async function op(fn, successMsg) {
  try {
    await fn()
    ElMessage.success(successMsg)
    await load()
    emit('notification-may-change')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function askReason(title, placeholder) {
  const { value } = await ElMessageBox.prompt(title, placeholder, {
    inputPlaceholder: placeholder || '请输入原因（必填）',
    inputValidator: (v) => (v && v.trim() ? true : '原因不能为空'),
  })
  return value.trim()
}

const startStage = (s) => op(() => api.post(`/stages/${s.id}/start`), `「${stageLabel(s.stage_type)}」已开始`)
const completeStage = (s) => op(() => api.post(`/stages/${s.id}/complete`), `「${stageLabel(s.stage_type)}」已完成`)

async function pause() {
  const reason = await askReason('暂停原因')
  op(() => api.post(`/requirements/${detail.value.id}/pause`, { reason }), '需求已暂停')
}

async function resume() {
  op(() => api.post(`/requirements/${detail.value.id}/resume`, { reason: '恢复' }), '需求已恢复（排期自动顺延）')
}

async function markDelayed() {
  const reason = await askReason('标记延期的原因')
  op(() => api.post(`/requirements/${detail.value.id}/mark-delayed`, { reason }), '已标记延期')
}

async function unmarkDelayed() {
  const reason = await askReason('解除延期的原因')
  op(() => api.post(`/requirements/${detail.value.id}/unmark-delayed`, { reason }), '已解除人工延期')
}

// 改期对话框
const planVisible = ref(false)
const planStage = ref(null)
const planForm = ref({ planned_start: '', planned_end: '' })

function openPlan(stage) {
  planStage.value = stage
  planForm.value = {
    planned_start: (stage.planned_start || '').slice(0, 10),
    planned_end: (stage.planned_end || '').slice(0, 10),
  }
  planVisible.value = true
}

async function submitPlan() {
  const reason = await askReason('修改预估时间的原因（延期原因必填）')
  const body = {}
  // 日期型选择：开始取当日 00:00，结束取当日 23:59:59
  if (planForm.value.planned_start) body.planned_start = `${planForm.value.planned_start}T00:00:00+08:00`
  if (planForm.value.planned_end) body.planned_end = `${planForm.value.planned_end}T23:59:59+08:00`
  body.reason = reason
  planVisible.value = false
  op(() => api.patch(`/stages/${planStage.value.id}/plan`, body), '预估时间已更新（写入变更历史）')
}

// 回退对话框
const revertVisible = ref(false)
const revertStage = ref(null)
const revertForm = ref({ target: '', reason: '' })

function openRevert(stage) {
  revertStage.value = stage
  revertForm.value = { target: '', reason: '' }
  revertVisible.value = true
}

const revertTargets = computed(() =>
  (REVERT_TARGETS[revertStage.value?.stage_type] || []).map((t) => ({
    value: detail.value?.stages.find((s) => s.stage_type === t)?.id,
    label: stageLabel(t),
  })),
)

async function submitRevert() {
  if (!revertForm.value.target) {
    ElMessage.warning('请选择回退目标环节')
    return
  }
  if (!revertForm.value.reason.trim()) {
    ElMessage.warning('请填写回退原因')
    return
  }
  revertVisible.value = false
  op(
    () =>
      api.post(`/stages/${revertStage.value.id}/revert`, {
        reason: revertForm.value.reason.trim(),
        target_stage_id: revertForm.value.target,
      }),
    '已回退，下游环节已重置',
  )
}

// 指派
async function assign(stage, userId) {
  op(() => api.patch(`/stages/${stage.id}/assignee`, { assignee_id: userId }), '负责人已更新')
}

onMounted(async () => {
  await load()
  ensureUsers().catch(() => {})
})
</script>

<template>
  <div v-loading="loading" class="page">
    <template v-if="detail">
      <el-card shadow="never" class="head-card">
        <div class="head-row">
          <div class="head-main">
            <div class="head-title">
              <el-button link class="back" @click="$router.push('/requirements')">← 返回</el-button>
              <span class="title-text">{{ detail.title }}</span>
              <el-tag :type="statusMeta(REQ_STATUSES, detail.status).type" effect="dark" round>
                {{ statusMeta(REQ_STATUSES, detail.status).label }}
              </el-tag>
              <el-tag v-if="detail.manual_delayed" type="danger" effect="plain" round>人工标记延期</el-tag>
            </div>
            <div class="head-meta">
              <span v-if="detail.product_line">产品线 {{ detail.product_line }}</span>
              <span>优先级 {{ detail.priority }}</span>
              <span>负责 PM {{ detail.pm_name || `#${detail.responsible_pm_id}` }}</span>
              <span>所属项目 {{ detail.project_id ?? '—' }}</span>
              <span>当前环节 {{ detail.current_stage || '—' }}</span>
            </div>
            <div v-if="detail.description" class="head-desc">{{ detail.description }}</div>
          </div>
          <div v-if="canWrite" class="head-actions">
            <el-button v-if="!['paused', 'done'].includes(detail.status)" size="small" @click="pause">暂停</el-button>
            <el-button v-if="detail.status === 'paused'" size="small" type="warning" @click="resume">恢复（顺延排期）</el-button>
            <el-button v-if="detail.manual_delayed" size="small" type="danger" plain @click="unmarkDelayed">解除人工延期</el-button>
            <el-button v-else-if="detail.status !== 'done'" size="small" type="danger" plain @click="markDelayed">标记延期</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="block">
        <template #header><span class="card-title">环节时间线</span></template>
        <el-table :data="detail?.stages || []" size="default">
          <el-table-column label="环节" width="110">
            <template #default="{ row }">{{ stageLabel(row.stage_type) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="statusMeta(STAGE_STATUSES, row.status).type" size="small" round>
                {{ statusMeta(STAGE_STATUSES, row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="预计" width="240">
            <template #default="{ row }">
              {{ fmtDate(row.planned_start) }} → {{ fmtDate(row.planned_end) }}
            </template>
          </el-table-column>
          <el-table-column label="实际" width="300">
            <template #default="{ row }">
              {{ fmtTime(row.actual_start) }} → {{ fmtTime(row.actual_end) }}
            </template>
          </el-table-column>
          <el-table-column label="负责人" width="150">
            <template #default="{ row }">
              <el-select
                v-if="canWrite && row.status !== 'done'"
                :model-value="row.assignee_id"
                clearable
                placeholder="（待指派）"
                size="small"
                @change="(v) => assign(row, v)"
              >
                <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
              </el-select>
              <span v-else>{{ users.find((u) => u.id === row.assignee_id)?.display_name || (row.assignee_id ?? '—') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="230">
            <template #default="{ row }">
              <template v-if="row.status !== 'done'">
                <el-button v-if="row.status === 'not_started'" size="small" type="primary" @click="startStage(row)">开始</el-button>
                <el-button v-if="row.status === 'in_progress'" size="small" type="success" @click="completeStage(row)">完成</el-button>
                <el-button size="small" @click="openPlan(row)">改期</el-button>
                <el-button v-if="REVERT_TARGETS[row.stage_type]" size="small" type="warning" plain @click="openRevert(row)">回退</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-row :gutter="14" class="block">
        <el-col :span="detail?.revert_logs?.length ? 12 : 24">
          <el-card shadow="never">
            <template #header><span class="card-title">预估时间变更历史</span></template>
            <el-empty v-if="!detail?.change_logs?.length" description="暂无变更" :image-size="60" />
            <el-timeline v-else>
              <el-timeline-item v-for="log in detail.change_logs" :key="log.id" :timestamp="fmtTime(log.created_at)" :type="log.auto_generated ? 'info' : 'primary'">
                {{ stageLabel(detail.stages.find((s) => s.id === log.stage_id)?.stage_type || '') }}
                {{ log.field === 'planned_start' ? '预计开始' : '预计结束' }}：
                {{ fmtTime(log.old_value) }} → {{ fmtTime(log.new_value) }}
                <el-tag v-if="log.auto_generated" size="small" type="info" style="margin-left: 6px">系统顺延</el-tag>
                <div class="log-reason">原因：{{ log.reason }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
        <el-col v-if="detail?.revert_logs?.length" :span="12">
          <el-card shadow="never">
            <template #header><span class="card-title">回退历史</span></template>
            <el-timeline>
              <el-timeline-item v-for="log in detail.revert_logs" :key="log.id" :timestamp="fmtTime(log.created_at)" type="warning">
                {{ stageLabel(detail.stages.find((s) => s.id === log.from_stage_id)?.stage_type || '') }}
                →
                {{ stageLabel(detail.stages.find((s) => s.id === log.to_stage_id)?.stage_type || '') }}
                <div class="log-reason">原因：{{ log.reason }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-dialog v-model="planVisible" :title="`修改预估时间 — ${stageLabel(planStage?.stage_type || '')}`" width="520px">
      <el-form label-width="90px">
        <el-form-item label="预计开始">
          <el-date-picker v-model="planForm.planned_start" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="预计结束">
          <el-date-picker v-model="planForm.planned_end" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="planVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPlan">下一步（填原因）</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="revertVisible" :title="`回退 — ${stageLabel(revertStage?.stage_type || '')}`" width="480px">
      <el-form label-width="90px">
        <el-form-item label="回退目标">
          <el-select v-model="revertForm.target" placeholder="选择目标环节" style="width: 100%">
            <el-option v-for="t in revertTargets" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="revertForm.reason" type="textarea" :rows="2" placeholder="回退原因（必填，留痕）" />
        </el-form-item>
      </el-form>
      <div class="revert-hint">目标环节之后的下游环节将被重置为未开始</div>
      <template #footer>
        <el-button @click="revertVisible = false">取消</el-button>
        <el-button type="warning" @click="submitRevert">确认回退</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head-card {
  margin-bottom: 14px;
}

.head-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.head-main {
  min-width: 0;
}

.head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.back {
  color: var(--pm-text-sub);
  padding: 0;
  margin-right: 2px;
}

.title-text {
  font-size: 18px;
  font-weight: 700;
}

.head-meta {
  margin-top: 8px;
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--pm-text-sub);
}

.head-desc {
  margin-top: 8px;
  font-size: 13px;
  color: #4b5668;
  line-height: 1.6;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.block {
  margin-bottom: 14px;
}

.log-reason {
  color: var(--pm-text-sub);
  font-size: 13px;
}

.revert-hint {
  color: #e6a23c;
  font-size: 13px;
}
</style>
