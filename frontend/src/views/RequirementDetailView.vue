<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, getStoredUser } from '../api'
import {
  REQ_STATUSES,
  STAGE_STATUSES,
  PRODUCT_LINES,
  REQ_CATEGORIES,
  statusMeta,
  stageLabel,
  fmtTime,
} from '../format'

const props = defineProps({ id: { type: String, required: true } })
const emit = defineEmits(['notification-may-change'])

const detail = ref(null)
const loading = ref(false)
const users = ref([])
const me = ref(getStoredUser())
const statusUpdating = ref(false)
const AUTO_STATUS = '__auto__'

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

async function updateRequirementStatus(value) {
  const status = value === AUTO_STATUS ? null : value
  if (status === detail.value.manual_status || statusUpdating.value) return
  statusUpdating.value = true
  try {
    await api.patch(`/requirements/${detail.value.id}/status`, { status })
    ElMessage.success(status === null ? '已恢复按环节自动计算状态' : '需求状态已更新')
    await load()
    emit('notification-may-change')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    statusUpdating.value = false
  }
}

// 需求明细编辑
const editVisible = ref(false)
const editForm = ref({})

function openEdit() {
  editForm.value = {
    title: detail.value.title,
    product_line: detail.value.product_line,
    category: detail.value.category,
    source: detail.value.source || '',
    priority: detail.value.priority,
    description: detail.value.description || '',
    remark: detail.value.remark || '',
  }
  editVisible.value = true
}

async function submitEdit() {
  if (!editForm.value.title?.trim()) {
    ElMessage.warning('请填写需求名称')
    return
  }
  editVisible.value = false
  op(
    () => api.patch(`/requirements/${detail.value.id}`, {
      ...editForm.value,
      title: editForm.value.title.trim(),
      description: editForm.value.description || null,
      source: editForm.value.source || null,
      remark: editForm.value.remark || null,
    }),
    '需求明细已更新',
  )
}

function stageTimeText(value) {
  return value ? fmtTime(value) : ''
}

function normalizeStageTime(value, field) {
  const raw = String(value || '').trim().replaceAll('/', '-')
  if (!raw) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
    return `${raw}T${field === 'planned_start' ? '00:00:00' : '23:59:59'}+08:00`
  }
  return undefined
}

async function updateStageTime(stage, field, value) {
  const normalized = normalizeStageTime(value, field)
  if (!normalized) {
    ElMessage.warning('请输入有效日期，例如 2026-08-18')
    return
  }
  if (stage[field] === normalized) return
  try {
    const reason = await askReason('修改环节时间的原因（必填）')
    const body = { reason }
    body[field] = normalized
    await op(
      () => api.patch(`/stages/${stage.id}/plan`, body),
      '环节时间已更新',
    )
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e.message || '操作已取消')
  }
}

const fieldLabel = {
  title: '需求名称', description: '需求描述', remark: '备注', product_line: '产品线',
  category: '需求分类', source: '需求来源', priority: '优先级', project_id: '所属项目',
  responsible_pm_id: '负责 PM', status: '需求状态',
}

function modificationText(log) {
  if (log.change_type === 'stage_time') {
    const [stage, field] = log.field.split(':')
    return `${stageLabel(stage)} ${field === 'planned_start' ? '开始日期' : '结束日期'}`
  }
  if (log.change_type === 'revert') return '环节回退'
  if (log.field.startsWith('stage_assignee:')) return `${stageLabel(log.field.split(':')[1])}负责人`
  return fieldLabel[log.field] || log.field
}

function modificationValue(log, value) {
  if (value === null || value === '') return '（空）'
  if (log.change_type === 'stage_time') return fmtTime(value)
  if (log.change_type === 'revert') return stageLabel(value)
  if (log.change_type === 'status') return statusMeta(REQ_STATUSES, value).label
  return value
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
              <span v-if="detail.product_line">{{ detail.product_line }}</span>
              <span>{{ detail.category || '未分类' }}</span>
              <span>优先级 {{ detail.priority }}</span>
              <span>负责人 {{ detail.pm_name || `#${detail.responsible_pm_id}` }}</span>
              <span>当前 {{ detail.current_stage || '—' }}</span>
            </div>
            <div class="detail-focus">
              <div class="detail-focus-label">需求明细</div>
              <div class="head-desc" :class="{ muted: !detail.description }">
                {{ detail.description || '暂未填写需求描述' }}
              </div>
              <div v-if="detail.remark" class="head-remark"><span>备注</span>{{ detail.remark }}</div>
            </div>
          </div>
          <div v-if="canWrite" class="head-actions">
            <el-button size="small" type="primary" @click="openEdit">编辑明细</el-button>
            <el-select
              class="status-select"
              :model-value="detail.manual_status ?? AUTO_STATUS"
              :disabled="statusUpdating"
              size="small"
              aria-label="修改需求状态"
              @change="updateRequirementStatus"
            >
              <el-option label="状态：自动计算" :value="AUTO_STATUS" />
              <el-option v-for="item in REQ_STATUSES" :key="item.value" :label="`状态：${item.label}`" :value="item.value" />
            </el-select>
            <el-button v-if="!['paused', 'done'].includes(detail.status)" size="small" @click="pause">暂停</el-button>
            <el-button v-if="detail.status === 'paused'" size="small" type="warning" @click="resume">恢复（顺延排期）</el-button>
            <el-button v-if="detail.manual_delayed" size="small" type="danger" plain @click="unmarkDelayed">解除人工延期</el-button>
            <el-button v-else-if="detail.status !== 'done'" size="small" type="danger" plain @click="markDelayed">标记延期</el-button>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="block stage-card">
        <template #header>
          <div class="section-head">
            <div><span class="card-title">环节安排</span><span class="section-subtitle">点击时间可直接调整计划</span></div>
            <span class="stage-count">{{ detail.stages.length }} 个环节</span>
          </div>
        </template>
        <el-table :data="detail?.stages || []" size="small" class="compact-stage-table">
          <el-table-column label="环节" width="120">
            <template #default="{ row, $index }"><span class="stage-index">{{ String($index + 1).padStart(2, '0') }}</span>{{ stageLabel(row.stage_type) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="94">
            <template #default="{ row }">
              <el-tag :type="statusMeta(STAGE_STATUSES, row.status).type" size="small" round>
                {{ statusMeta(STAGE_STATUSES, row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="日期" min-width="255">
            <template #default="{ row }">
              <div v-if="canWrite && row.status !== 'done'" class="stage-time-inputs">
                <el-input
                  :model-value="stageTimeText(row.planned_start)"
                  placeholder="开始日期"
                  class="stage-date-picker"
                  @change="(value) => updateStageTime(row, 'planned_start', value)"
                />
                <span>至</span>
                <el-input
                  :model-value="stageTimeText(row.planned_end)"
                  placeholder="结束日期"
                  class="stage-date-picker"
                  @change="(value) => updateStageTime(row, 'planned_end', value)"
                />
              </div>
              <span v-else>{{ fmtTime(row.planned_start) }} → {{ fmtTime(row.planned_end) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="负责人" width="135">
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
          <el-table-column label="操作" min-width="160">
            <template #default="{ row }">
              <template v-if="row.status !== 'done'">
                <el-button v-if="row.status === 'not_started'" size="small" type="primary" @click="startStage(row)">开始</el-button>
                <el-button v-if="row.status === 'in_progress'" size="small" type="success" @click="completeStage(row)">完成</el-button>
                <el-button v-if="REVERT_TARGETS[row.stage_type]" size="small" type="warning" plain @click="openRevert(row)">回退</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-row class="block">
        <el-col :span="24">
          <el-card shadow="never" class="log-card">
            <template #header>
              <div class="section-head">
                <div><span class="card-title">需求修改记录</span><span class="section-subtitle">按最新操作倒序展示</span></div>
                <span class="stage-count">{{ detail.modification_logs?.length || 0 }} 条</span>
              </div>
            </template>
            <el-empty v-if="!detail?.modification_logs?.length" description="暂无修改记录" :image-size="60" />
            <div v-else class="modification-log-list">
              <div v-for="log in detail.modification_logs" :key="log.id" class="modification-log-line" :class="{ warning: log.change_type === 'revert' }">
                <time>{{ fmtTime(log.created_at) }}</time>
                <span class="log-actor">{{ users.find((u) => u.id === log.changed_by)?.display_name || (log.changed_by ? `#${log.changed_by}` : '系统') }}</span>
                <strong>{{ modificationText(log) }}</strong>
                <span class="log-value">{{ modificationValue(log, log.old_value) }} <i>→</i> {{ modificationValue(log, log.new_value) }}</span>
                <span v-if="log.reason" class="log-reason" :title="log.reason">原因：{{ log.reason }}</span>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-dialog v-model="editVisible" title="编辑需求明细" width="620px">
      <el-form label-width="90px">
        <el-form-item label="需求名称" required>
          <el-input v-model="editForm.title" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="产品线">
          <el-select v-model="editForm.product_line" clearable style="width: 100%">
            <el-option v-for="item in PRODUCT_LINES" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="需求分类">
          <el-radio-group v-model="editForm.category">
            <el-radio-button v-for="item in REQ_CATEGORIES" :key="item" :value="item">{{ item }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="editForm.priority">
            <el-radio-button v-for="item in ['P0', 'P1', 'P2', 'P3']" :key="item" :value="item">{{ item }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="需求来源">
          <el-input v-model="editForm.source" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="需求描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" maxlength="4000" show-word-limit />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="3" maxlength="4000" show-word-limit placeholder="填写补充说明、风险或协作备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存修改</el-button>
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
  overflow: hidden;
  background: linear-gradient(120deg, #fff 0%, #f5f9ff 100%);
  border-color: #e6edf7;
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
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.35px;
}

.head-meta {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  color: var(--pm-text-sub);
}

.head-meta span {
  padding: 4px 9px;
  border: 1px solid #e4eaf2;
  border-radius: 999px;
  background: rgb(255 255 255 / 70%);
}

.detail-focus {
  margin-top: 18px;
  padding: 15px 17px;
  border-left: 3px solid var(--el-color-primary);
  border-radius: 0 10px 10px 0;
  background: rgb(255 255 255 / 76%);
}

.detail-focus-label {
  margin-bottom: 7px;
  color: var(--pm-text-sub);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .08em;
}

.head-desc {
  color: #303b4c;
  font-size: 15px;
  line-height: 1.75;
  white-space: pre-wrap;
}

.head-desc.muted {
  color: #9ba7b8;
}

.head-remark {
  margin-top: 10px;
  color: var(--pm-text-sub);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.head-remark span {
  display: inline-block;
  margin-right: 8px;
  padding: 1px 6px;
  color: #6580a3;
  font-size: 11px;
  background: #edf4ff;
  border-radius: 4px;
}

.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.status-select {
  width: 132px;
}

.block {
  margin-bottom: 14px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-subtitle {
  margin-left: 10px;
  color: var(--pm-text-sub);
  font-size: 12px;
  font-weight: 400;
}

.stage-count {
  color: #758399;
  font-size: 12px;
}

.stage-card :deep(.el-card__header),
.log-card :deep(.el-card__header) {
  padding: 13px 18px;
}

.stage-index {
  display: inline-block;
  width: 24px;
  color: #a2adbc;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.compact-stage-table :deep(.el-table__cell) {
  padding: 6px 0;
}

.compact-stage-table :deep(.el-table__header .el-table__cell) {
  padding: 8px 0;
}

.stage-date-picker {
  width: 108px;
}

.stage-date-picker :deep(.el-input__inner) {
  font-size: 12px;
}

.stage-time-inputs {
  display: flex;
  align-items: center;
  gap: 5px;
  color: #9aa7b7;
  font-size: 12px;
}

.modification-log-list {
  margin: -4px 0;
}

.modification-log-line {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 9px;
  height: 38px;
  padding: 0 4px;
  border-bottom: 1px solid #f0f3f7;
  color: #3e4b5c;
  font-size: 13px;
  white-space: nowrap;
}

.modification-log-line:last-child {
  border-bottom: 0;
}

.modification-log-line time {
  flex: 0 0 120px;
  color: #8b97a8;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.log-actor {
  flex: 0 0 64px;
  overflow: hidden;
  color: #62748b;
  text-overflow: ellipsis;
}

.log-value {
  overflow: hidden;
  color: #66758a;
  text-overflow: ellipsis;
}

.log-value i {
  margin: 0 3px;
  color: #9aa7b7;
  font-style: normal;
}

.log-reason {
  overflow: hidden;
  min-width: 0;
  margin-left: auto;
  color: #8895a6;
  text-overflow: ellipsis;
}

.modification-log-line.warning strong {
  color: #c6842b;
}

.revert-hint {
  color: #e6a23c;
  font-size: 13px;
}
</style>
