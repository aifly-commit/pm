<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Filter } from '@element-plus/icons-vue'
import { api } from '../api'
import { REQ_STATUSES, STAGE_TYPES, PRODUCT_LINES, REQ_CATEGORIES, statusMeta, fmtTime } from '../format'

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const filters = reactive({
  status: '',
  stage_type: '',
  product_line: '',
  category: '',
  priority: '',
  pm_id: null,
  keyword: '',
  page: 1,
  page_size: 20,
})

// 新建需求
const createVisible = ref(false)
const creating = ref(false)
const users = ref([])
const createForm = reactive({
  title: '',
  product_line: '',
  category: '',
  source: '',
  planned_release: '', // 预计上线时间（必填），映射为 release 环节 planned_end
  priority: 'P2',
  description: '',
  remark: '',
  stages: STAGE_TYPES.map((s) => ({
    stage_type: s.value,
    label: s.label,
    planned_start: '',
    planned_end: '',
    assignee_id: null,
  })),
})

async function load() {
  loading.value = true
  try {
    const params = {}
    for (const k of ['status', 'stage_type', 'product_line', 'category', 'priority', 'pm_id', 'keyword', 'page', 'page_size'])
      if (filters[k] !== '' && filters[k] != null) params[k] = filters[k]
    const data = await api.get('/requirements?' + new URLSearchParams(params))
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

function applySelectFilter(key, value) {
  // 不依赖 Popover 内部组件的 change 冒泡；值一更新就明确发起一次查询。
  filters[key] = value ?? ''
  search()
}

function applyKeywordFilter() {
  search()
}

async function openCreate() {
  createVisible.value = true
  await loadUsers()
}

async function loadUsers() {
  if (!users.value.length) {
    try {
      users.value = await api.get('/users/directory')
    } catch {
      /* 目录拉取失败不阻塞创建 */
    }
  }
}

function normalizeDate(value) {
  const day = String(value || '').trim().replaceAll('/', '-')
  if (!day) return null
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return undefined
  const parsed = new Date(`${day}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== day
    ? undefined
    : day
}

function toApiDate(value, isEnd = false) {
  const day = normalizeDate(value)
  if (!day) return null
  return `${day}T${isEnd ? '23:59:59' : '00:00:00'}+08:00`
}

async function submitCreate() {
  // 必填项保存时校验：需求名称、产品线、预计上线时间
  if (!createForm.title.trim()) {
    ElMessage.warning('请填写需求名称')
    return
  }
  if (!createForm.product_line) {
    ElMessage.warning('请选择产品线')
    return
  }
  if (!normalizeDate(createForm.planned_release)) {
    ElMessage.warning('请填写有效的预计上线日期，例如 2026-08-18')
    return
  }
  const stageDateValues = createForm.stages.flatMap((stage) => [stage.planned_start, stage.planned_end])
  if (stageDateValues.some((value) => value && !normalizeDate(value))) {
    ElMessage.warning('环节日期请输入有效格式，例如 2026-08-18')
    return
  }
  creating.value = true
  try {
    const stages = createForm.stages
      .filter((s) => s.planned_start || s.planned_end)
      .map((s) => ({
        stage_type: s.stage_type,
        planned_start: toApiDate(s.planned_start),
        planned_end: toApiDate(s.planned_end, true),
        assignee_id: s.assignee_id,
      }))
    // 预计上线时间 = release 环节 planned_end（若表格中未单独填 release 行则注入）
    const releaseRow = stages.find((s) => s.stage_type === 'release')
    if (releaseRow) {
      releaseRow.planned_end = toApiDate(createForm.planned_release, true)
    } else {
      stages.push({
        stage_type: 'release',
        planned_start: null,
        planned_end: toApiDate(createForm.planned_release, true),
        assignee_id: null,
      })
    }
    const created = await api.post('/requirements', {
      title: createForm.title,
      product_line: createForm.product_line,
      category: createForm.category || null,
      source: createForm.source || null,
      priority: createForm.priority,
      description: createForm.description || null,
      remark: createForm.remark || null,
      stages,
    })
    ElMessage.success('需求已创建')
    createVisible.value = false
    createForm.title = ''
    createForm.product_line = ''
    createForm.category = ''
    createForm.source = ''
    createForm.planned_release = ''
    createForm.description = ''
    createForm.remark = ''
    createForm.priority = 'P2'
    createForm.stages.forEach((s) => {
      s.planned_start = ''
      s.planned_end = ''
      s.assignee_id = null
    })
    router.push(`/requirements/${created.id}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    creating.value = false
  }
}

onMounted(() => {
  load()
  loadUsers()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div class="page-heading">
        <h2 class="page-title">需求管理</h2>
        <p class="page-sub">全流程跟踪：调研 → 审评 → 开发 → 测试 → 上线</p>
      </div>
      <el-button type="primary" @click="openCreate">+ 新建需求</el-button>
    </div>

    <el-card shadow="never" class="table-card">
      <div class="table-heading">
        <div><strong>需求清单</strong><span>点击行可查看完整流转记录</span></div>
        <span class="table-total">共 {{ total }} 条</span>
      </div>
      <el-table :data="rows" v-loading="loading" @row-click="(r) => router.push(`/requirements/${r.id}`)" style="cursor: pointer">
        <el-table-column prop="id" label="序号" width="70" />
        <el-table-column prop="product_line" width="120">
          <template #header>
            <div class="table-filter-header"><span>产品线</span><el-popover placement="bottom-start" :width="190" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.product_line }" title="筛选产品线"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.product_line" placeholder="全部产品线" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('product_line', value)"><el-option v-for="p in PRODUCT_LINES" :key="p" :label="p" :value="p" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">
            <el-tag v-if="row.product_line" effect="plain" round>{{ row.product_line }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="category" width="108">
          <template #header>
            <div class="table-filter-header"><span>需求分类</span><el-popover placement="bottom-start" :width="190" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.category }" title="筛选需求分类"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.category" placeholder="全部分类" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('category', value)"><el-option v-for="c in REQ_CATEGORIES" :key="c" :label="c" :value="c" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">{{ row.category || '—' }}</template>
        </el-table-column>
        <el-table-column prop="title" min-width="180" show-overflow-tooltip>
          <template #header>
            <div class="table-filter-header"><span>需求名称</span><el-popover placement="bottom-start" :width="220" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.keyword }" title="按需求名称筛选"><el-icon><Filter /></el-icon></button></template><el-input v-model="filters.keyword" placeholder="输入名称关键词" clearable @keyup.enter="applyKeywordFilter" @clear="applyKeywordFilter" /></el-popover></div>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="需求来源" width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source || '—' }}</template>
        </el-table-column>
        <el-table-column prop="priority" width="88">
          <template #header>
            <div class="table-filter-header"><span>优先级</span><el-popover placement="bottom-start" :width="150" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.priority }" title="筛选优先级"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.priority" placeholder="全部优先级" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('priority', value)"><el-option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :label="p" :value="p" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">
            <el-tag :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'" effect="plain">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="current_stage" width="118">
          <template #header>
            <div class="table-filter-header"><span>当前环节</span><el-popover placement="bottom-start" :width="180" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.stage_type }" title="筛选当前环节"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.stage_type" placeholder="全部环节" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('stage_type', value)"><el-option v-for="s in STAGE_TYPES" :key="s.value" :label="s.label" :value="s.value" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">{{ row.current_stage || '—' }}</template>
        </el-table-column>
        <el-table-column width="98">
          <template #header>
            <div class="table-filter-header"><span>状态</span><el-popover placement="bottom-start" :width="160" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.status }" title="筛选状态"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.status" placeholder="全部状态" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('status', value)"><el-option v-for="s in REQ_STATUSES" :key="s.value" :label="s.label" :value="s.value" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">
            <el-tag :type="statusMeta(REQ_STATUSES, row.status).type" effect="dark" round>
              {{ statusMeta(REQ_STATUSES, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column width="108">
          <template #header>
            <div class="table-filter-header"><span>负责人</span><el-popover placement="bottom-start" :width="190" trigger="click"><template #reference><button class="header-filter-button" :class="{ active: filters.pm_id }" title="筛选负责人"><el-icon><Filter /></el-icon></button></template><el-select :model-value="filters.pm_id" placeholder="全部负责人" clearable style="width: 100%" @update:model-value="(value) => applySelectFilter('pm_id', value)"><el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" /></el-select></el-popover></div>
          </template>
          <template #default="{ row }">{{ row.pm_name || `#${row.responsible_pm_id}` }}</template>
        </el-table-column>
        <el-table-column label="预计上线" width="126">
          <template #default="{ row }"><span class="release-date">{{ fmtTime(row.planned_release) }}</span></template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="filters.page"
        :page-size="filters.page_size"
        :total="total"
        layout="total, prev, pager, next"
        class="pager"
        @current-change="load"
      />
    </el-card>

    <el-dialog v-model="createVisible" title="新建需求" width="880px" top="6vh">
      <el-form label-width="90px">
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item label="需求名称" required>
              <el-input v-model="createForm.title" maxlength="200" placeholder="请输入需求名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="产品线" required>
              <el-select v-model="createForm.product_line" clearable placeholder="选择产品线（必填）" style="width: 100%">
                <el-option v-for="p in PRODUCT_LINES" :key="p" :label="p" :value="p" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="预计上线" required>
              <el-input v-model="createForm.planned_release" maxlength="10" placeholder="YYYY-MM-DD（必填）" inputmode="numeric" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="需求分类">
              <el-radio-group v-model="createForm.category">
                <el-radio-button v-for="c in REQ_CATEGORIES" :key="c" :value="c">{{ c }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="优先级">
              <el-radio-group v-model="createForm.priority">
                <el-radio-button v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :value="p">{{ p }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="需求来源">
              <el-input v-model="createForm.source" maxlength="128" placeholder="如：客户反馈 / 内部规划 / 售前支持" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="描述">
              <el-input v-model="createForm.description" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input
                v-model="createForm.remark"
                type="textarea"
                :rows="2"
                maxlength="4000"
                show-word-limit
                placeholder="填写补充说明、风险或协作备注"
              />
            </el-form-item>
          </el-col>
        </el-row>
        <el-divider content-position="left">环节排期（支持手动填写 YYYY-MM-DD，可留空）</el-divider>
        <el-table :data="createForm.stages" size="small">
          <el-table-column prop="label" label="环节" width="100" />
          <el-table-column label="预计开始日期">
            <template #default="{ row }">
              <el-input v-model="row.planned_start" maxlength="10" placeholder="YYYY-MM-DD" inputmode="numeric" />
            </template>
          </el-table-column>
          <el-table-column label="预计结束日期">
            <template #default="{ row }">
              <el-input v-model="row.planned_end" maxlength="10" placeholder="YYYY-MM-DD" inputmode="numeric" />
            </template>
          </el-table-column>
          <el-table-column label="负责人">
            <template #default="{ row }">
              <el-select v-model="row.assignee_id" clearable placeholder="（待指派）" style="width: 100%">
                <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
              </el-select>
            </template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.table-card :deep(.el-card__body) {
  padding: 0 12px 16px;
}

.table-heading span { color: var(--pm-text-sub); font-size: 12px; }
.table-heading { display: flex; justify-content: space-between; align-items: center; padding: 17px 8px 11px; }
.table-heading strong { color: #34415f; font-size: 15px; margin-right: 10px; }
.table-total { padding: 4px 9px; border-radius: 999px; background: #f0f3fa; }
.table-filter-header { display: inline-flex; align-items: center; gap: 2px; white-space: nowrap; }
.header-filter-button { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: #8490a9; cursor: pointer; }
.header-filter-button:hover, .header-filter-button.active { background: #e9edff; color: var(--pm-primary); }
.release-date { display: inline-block; white-space: nowrap; font-variant-numeric: tabular-nums; }

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

@media (max-width: 760px) {
}
</style>
