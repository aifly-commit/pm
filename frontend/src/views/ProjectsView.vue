<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, getStoredUser } from '../api'
import { PROJECT_STATUSES, REQ_STATUSES, statusMeta, fmtDate } from '../format'

const props = defineProps({ id: { type: String, default: '' } })
const loading = ref(false)
const rows = ref([])
const detail = ref(null)
const me = ref(getStoredUser())

const filters = reactive({ status: '', owner_id: null })

const createVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  name: '',
  description: '',
  planned_start: '',
  planned_end: '',
  contacts: [{ name: '', phone: '' }],
})

const attachVisible = ref(false)
const attachId = ref(null)
const allRequirements = ref([])

async function loadList() {
  loading.value = true
  try {
    const params = {}
    if (filters.status) params.status = filters.status
    const data = await api.get('/projects?' + new URLSearchParams(params))
    rows.value = data.items
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadDetail(id) {
  loading.value = true
  try {
    detail.value = await api.get(`/projects/${id}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function reload() {
  props.id ? loadDetail(props.id) : loadList()
}

async function submitCreate() {
  if (!createForm.name.trim()) {
    ElMessage.warning('请填写项目名称')
    return
  }
  creating.value = true
  try {
    const created = await api.post('/projects', {
      name: createForm.name,
      description: createForm.description || null,
      planned_start: createForm.planned_start || null,
      planned_end: createForm.planned_end || null,
      contacts: createForm.contacts.filter((c) => c.name.trim()).map((c) => ({ name: c.name, phone: c.phone || null })),
    })
    ElMessage.success('项目已创建')
    createVisible.value = false
    createForm.name = ''
    createForm.description = ''
    createForm.planned_start = ''
    createForm.planned_end = ''
    createForm.contacts = [{ name: '', phone: '' }]
    history.pushState({}, '', `/projects/${created.id}`)
    loadDetail(created.id)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    creating.value = false
  }
}

async function openAttach() {
  try {
    const data = await api.get('/requirements?page_size=100')
    allRequirements.value = data.items.filter((r) => !r.project_id)
    attachVisible.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function attach() {
  if (!attachId.value) return
  try {
    detail.value = await api.post(`/projects/${detail.value.id}/requirements`, {
      requirement_id: attachId.value,
    })
    ElMessage.success('已挂接')
    attachVisible.value = false
    attachId.value = null
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function detach(rid) {
  try {
    detail.value = await api.delete(`/projects/${detail.value.id}/requirements/${rid}`)
    ElMessage.success('已解除挂接')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeProject() {
  try {
    await api.delete(`/projects/${detail.value.id}`)
    ElMessage.success('项目已删除（对接需求已解除挂接并保留）')
    history.pushState({}, '', '/projects')
    detail.value = null
    loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const canWriteProject = (p) => me.value && (me.value.role === 'admin' || p.owner_id === me.value.id)

onMounted(reload)
</script>

<template>
  <!-- 列表 -->
  <div v-if="!props.id && !detail">
    <div class="toolbar">
      <el-select v-model="filters.status" placeholder="项目状态" clearable style="width: 140px" @change="loadList">
        <el-option v-for="s in PROJECT_STATUSES" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>
      <el-button type="primary" @click="loadList">查询</el-button>
      <el-button type="success" @click="createVisible = true">新建项目</el-button>
    </div>
    <el-table :data="rows" v-loading="loading" @row-click="(r) => $router.push(`/projects/${r.id}`)" style="cursor: pointer">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="项目名称" min-width="200" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusMeta(PROJECT_STATUSES, row.status).type">{{ statusMeta(PROJECT_STATUSES, row.status).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="人工进度" width="180">
        <template #default="{ row }">
          <el-progress :percentage="row.progress_percent" :stroke-width="10" />
        </template>
      </el-table-column>
      <el-table-column label="计划周期" width="220">
        <template #default="{ row }">{{ fmtDate(row.planned_start) }} ~ {{ fmtDate(row.planned_end) }}</template>
      </el-table-column>
      <el-table-column prop="owner_id" label="负责人" width="90" />
    </el-table>

    <el-dialog v-model="createVisible" title="新建项目" width="560px">
      <el-form label-width="90px">
        <el-form-item label="名称" required><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="createForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="计划开始">
          <el-date-picker v-model="createForm.planned_start" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="计划结束">
          <el-date-picker v-model="createForm.planned_end" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item v-for="(c, i) in createForm.contacts" :key="i" :label="`接口人${i + 1}`">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input v-model="c.name" placeholder="姓名" />
            <el-input v-model="c.phone" placeholder="电话/邮箱/IM" />
          </div>
        </el-form-item>
        <el-button size="small" @click="createForm.contacts.push({ name: '', phone: '' })">+ 添加接口人</el-button>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>

  <!-- 详情 -->
  <div v-else v-loading="loading">
    <el-page-header @back="() => { detail = null; $router.push('/projects'); loadList() }" style="margin-bottom: 16px">
      <template #content><b>{{ detail?.name }}</b></template>
    </el-page-header>

    <el-descriptions v-if="detail" :column="4" border size="small" style="margin-bottom: 16px">
      <el-descriptions-item label="状态">
        <el-tag :type="statusMeta(PROJECT_STATUSES, detail.status).type">{{ statusMeta(PROJECT_STATUSES, detail.status).label }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="负责人">{{ detail.owner_id }}</el-descriptions-item>
      <el-descriptions-item label="计划周期">{{ fmtDate(detail.planned_start) }} ~ {{ fmtDate(detail.planned_end) }}</el-descriptions-item>
      <el-descriptions-item label="自动完成率">{{ (detail.completion_rate * 100).toFixed(1) }}%（{{ detail.done_count }}/{{ detail.total }}）</el-descriptions-item>
      <el-descriptions-item label="接口人" :span="2">
        {{ (detail.contacts || []).map((c) => `${c.name}(${c.phone || c.email || c.im || '—'})`).join('、') || '—' }}
      </el-descriptions-item>
      <el-descriptions-item label="进展" :span="2">
        <el-progress :percentage="detail.progress_percent" />
        <span style="font-size: 13px; color: #909399">{{ detail.progress_note || '' }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <div v-if="detail && canWriteProject(detail)" style="margin-bottom: 12px; display: flex; gap: 8px">
      <el-button type="primary" @click="openAttach">挂接需求</el-button>
      <el-button type="danger" plain @click="removeProject">删除项目</el-button>
    </div>

    <el-card shadow="never">
      <template #header><b>对接需求清单</b></template>
      <el-table :data="detail?.requirements || []">
        <el-table-column label="需求" min-width="220">
          <template #default="{ row }">
            <router-link :to="`/requirements/${row.id}`">{{ row.title }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="priority" label="优先级" width="90" />
        <el-table-column prop="current_stage" label="当前环节" width="140">
          <template #default="{ row }">{{ row.current_stage || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusMeta(REQ_STATUSES, row.status).type">{{ statusMeta(REQ_STATUSES, row.status).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button v-if="canWriteProject(detail)" size="small" link type="danger" @click="detach(row.id)">解除挂接</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="attachVisible" title="挂接需求" width="480px">
      <el-select v-model="attachId" placeholder="选择未挂接的需求" filterable style="width: 100%">
        <el-option v-for="r in allRequirements" :key="r.id" :label="`#${r.id} ${r.title}`" :value="r.id" />
      </el-select>
      <template #footer>
        <el-button @click="attachVisible = false">取消</el-button>
        <el-button type="primary" @click="attach">挂接</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
</style>
