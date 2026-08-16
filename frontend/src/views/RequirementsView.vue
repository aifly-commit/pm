<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { REQ_STATUSES, STAGE_TYPES, PRODUCT_LINES, statusMeta, fmtTime } from '../format'

const router = useRouter()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const filters = reactive({
  status: '',
  stage_type: '',
  product_line: '',
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
  priority: 'P2',
  description: '',
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
    for (const k of ['status', 'stage_type', 'product_line', 'keyword', 'page', 'page_size'])
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

async function openCreate() {
  createVisible.value = true
  if (!users.value.length) {
    try {
      users.value = await api.get('/users/directory')
    } catch {
      /* 目录拉取失败不阻塞创建 */
    }
  }
}

async function submitCreate() {
  if (!createForm.title.trim()) {
    ElMessage.warning('请填写需求标题')
    return
  }
  creating.value = true
  try {
    // 日期型选择：开始取当日 00:00，结束取当日 23:59:59（+08:00）
    const stages = createForm.stages
      .filter((s) => s.planned_start || s.planned_end)
      .map((s) => ({
        stage_type: s.stage_type,
        planned_start: s.planned_start ? `${s.planned_start}T00:00:00+08:00` : null,
        planned_end: s.planned_end ? `${s.planned_end}T23:59:59+08:00` : null,
        assignee_id: s.assignee_id,
      }))
    const created = await api.post('/requirements', {
      title: createForm.title,
      product_line: createForm.product_line || null,
      priority: createForm.priority,
      description: createForm.description || null,
      stages,
    })
    ElMessage.success('需求已创建')
    createVisible.value = false
    createForm.title = ''
    createForm.product_line = ''
    createForm.description = ''
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

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">需求管理</h2>
        <p class="page-sub">全流程跟踪：调研 → 审评 → 开发 → 测试 → 上线</p>
      </div>
      <el-button type="primary" @click="openCreate">+ 新建需求</el-button>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="toolbar">
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 120px" @change="search">
          <el-option v-for="s in REQ_STATUSES" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="filters.stage_type" placeholder="当前环节" clearable style="width: 120px" @change="search">
          <el-option v-for="s in STAGE_TYPES" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
        <el-select v-model="filters.product_line" placeholder="产品线" clearable style="width: 150px" @change="search">
          <el-option v-for="p in PRODUCT_LINES" :key="p" :label="p" :value="p" />
        </el-select>
        <el-input
          v-model="filters.keyword"
          placeholder="标题关键词"
          style="width: 200px"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <el-button type="primary" plain @click="search">查询</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" @row-click="(r) => router.push(`/requirements/${r.id}`)" style="cursor: pointer">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="product_line" label="产品线" width="130">
          <template #default="{ row }">
            <el-tag v-if="row.product_line" effect="plain" round>{{ row.product_line }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90">
          <template #default="{ row }">
            <el-tag :type="row.priority === 'P0' ? 'danger' : row.priority === 'P1' ? 'warning' : 'info'" effect="plain">
              {{ row.priority }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="current_stage" label="当前环节" width="140">
          <template #default="{ row }">{{ row.current_stage || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMeta(REQ_STATUSES, row.status).type" effect="dark" round>
              {{ statusMeta(REQ_STATUSES, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="负责 PM" width="110">
          <template #default="{ row }">{{ row.pm_name || `#${row.responsible_pm_id}` }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.updated_at) }}</template>
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

    <el-dialog v-model="createVisible" title="新建需求" width="860px" top="6vh">
      <el-form label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="createForm.title" maxlength="200" />
        </el-form-item>
        <el-form-item label="产品线">
          <el-select v-model="createForm.product_line" clearable placeholder="选择产品线" style="width: 100%">
            <el-option v-for="p in PRODUCT_LINES" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="createForm.priority">
            <el-radio-button v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :value="p">{{ p }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-divider content-position="left">环节排期（可留空，顺序约束自动校验）</el-divider>
        <el-table :data="createForm.stages" size="small">
          <el-table-column prop="label" label="环节" width="100" />
          <el-table-column label="预计开始">
            <template #default="{ row }">
              <el-date-picker v-model="row.planned_start" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
            </template>
          </el-table-column>
          <el-table-column label="预计结束">
            <template #default="{ row }">
              <el-date-picker v-model="row.planned_end" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
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
.filter-card {
  margin-bottom: 14px;
}

.filter-card :deep(.el-card__body) {
  padding: 14px 20px;
}

.table-card :deep(.el-card__body) {
  padding: 8px 12px 16px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
