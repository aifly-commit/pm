<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { REQ_STATUSES, PROJECT_STATUSES, STAGE_TYPES, statusMeta, stageLabel, fmtTime } from '../format'

const tab = ref('requirements')
const weekDate = ref(new Date().toISOString().slice(0, 10))
const month = ref(new Date().toISOString().slice(0, 7))

const overview = ref(null)
const reqReport = ref(null)
const projReport = ref(null)

async function load() {
  try {
    overview.value = await api.get('/stats/overview')
    reqReport.value = await api.get(
      `/stats/requirements/weekly?date=${weekDate.value}`,
    )
    projReport.value = await api.get(
      `/stats/projects/weekly?date=${weekDate.value}&status=all`,
    )
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function loadMonthly() {
  try {
    reqReport.value = await api.get(`/stats/requirements/monthly?month=${month.value}`)
    projReport.value = await api.get(`/stats/projects/monthly?month=${month.value}&status=all`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

const period = ref('weekly')
function switchPeriod(p) {
  period.value = p
  p === 'weekly' ? load() : loadMonthly()
}

onMounted(load)
</script>

<template>
  <div>
    <el-radio-group :model-value="period" @update:model-value="switchPeriod" style="margin-bottom: 16px">
      <el-radio-button value="weekly">周报</el-radio-button>
      <el-radio-button value="monthly">月报</el-radio-button>
    </el-radio-group>
    <el-date-picker
      v-if="period === 'weekly'"
      v-model="weekDate"
      type="date"
      value-format="YYYY-MM-DD"
      placeholder="选择日期（取所在自然周）"
      @change="load"
      style="margin-left: 12px"
    />
    <el-date-picker
      v-else
      v-model="month"
      type="month"
      value-format="YYYY-MM"
      placeholder="选择月份"
      @change="loadMonthly"
      style="margin-left: 12px"
    />

    <!-- 当前总览 -->
    <el-row v-if="overview" :gutter="12" style="margin: 16px 0">
      <el-col v-for="s in REQ_STATUSES" :key="s.value" :span="4">
        <el-card shadow="never">
          <el-statistic :title="s.label" :value="overview.status_distribution[s.value] || 0" />
        </el-card>
      </el-col>
    </el-row>

    <el-row v-if="overview" :gutter="12" style="margin-bottom: 16px">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><b>环节在途分布</b></template>
          <div v-for="st in STAGE_TYPES" :key="st.value" class="stage-row">
            <span style="width: 80px">{{ st.label }}</span>
            <el-progress
              :percentage="Math.min(100, (overview.stage_distribution[st.value] || 0) * 20)"
              :format="() => String(overview.stage_distribution[st.value] || 0)"
              style="flex: 1"
            />
          </div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>当前延期清单</b></template>
          <el-empty v-if="!overview.delayed_list.length" description="暂无延期需求" :image-size="60" />
          <div v-for="d in overview.delayed_list" :key="d.requirement_id" class="delayed-item">
            <router-link :to="`/requirements/${d.requirement_id}`">{{ d.title }}</router-link>
            <div style="color: #909399; font-size: 13px">
              <template v-if="d.overdue_stages.length">
                {{ d.overdue_stages.map((s) => `${s.stage_label} 逾期 ${s.overdue_days} 天`).join('；') }}
              </template>
              <template v-else>人工标记：{{ d.manual_delay_reason }}</template>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 需求周/月报 -->
    <el-card v-if="reqReport" shadow="never" style="margin-bottom: 16px">
      <template #header>
        <b>需求{{ period === 'weekly' ? '周报' : '月报' }}</b>
        <span style="color: #909399; font-size: 13px; margin-left: 12px">
          {{ fmtTime(reqReport.period_start) }} ~ {{ fmtTime(reqReport.period_end) }}
        </span>
      </template>
      <el-row :gutter="12">
        <el-col :span="4"><el-statistic title="本期新增" :value="reqReport.new_count" /></el-col>
        <el-col :span="4"><el-statistic title="本期完成" :value="reqReport.completed_count" /></el-col>
        <el-col :span="4"><el-statistic title="新产生延期" :value="reqReport.new_delayed_count" /></el-col>
        <el-col :span="4"><el-statistic title="当前延期" :value="reqReport.current_delayed_count" /></el-col>
        <el-col :span="4">
          <el-statistic title="延期率" :value="(reqReport.delay_rate * 100)" suffix="%" :precision="1" />
        </el-col>
        <el-col :span="4"><el-statistic title="未完成总数" :value="reqReport.unfinished_count" /></el-col>
      </el-row>
      <el-divider />
      <span style="margin-right: 16px">顺延调整：{{ reqReport.postponed_count }} 次</span>
      <span style="margin-right: 16px">提前调整：{{ reqReport.advanced_count }} 次</span>
      <span>
        Top 延期原因：
        <el-tag v-for="r in reqReport.top_delay_reasons" :key="r.reason" size="small" style="margin-right: 6px">
          {{ r.reason }} × {{ r.count }}
        </el-tag>
        <span v-if="!reqReport.top_delay_reasons.length" style="color: #909399">—</span>
      </span>
      <template v-if="reqReport.weekly_trend">
        <el-divider content-position="left">每周趋势（新增 / 完成 / 新产生延期）</el-divider>
        <el-table :data="reqReport.weekly_trend" size="small">
          <el-table-column label="周起始" width="160">
            <template #default="{ row }">{{ fmtTime(row.week_start) }}</template>
          </el-table-column>
          <el-table-column prop="new_count" label="新增" width="100" />
          <el-table-column prop="completed_count" label="完成" width="100" />
          <el-table-column prop="new_delayed_count" label="新产生延期" />
        </el-table>
      </template>
    </el-card>

    <!-- 项目周/月报 -->
    <el-card v-if="projReport" shadow="never">
      <template #header><b>项目{{ period === 'weekly' ? '周报' : '月报' }}（全部状态）</b></template>
      <el-table :data="projReport.projects" size="small">
        <el-table-column prop="name" label="项目" min-width="150" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusMeta(PROJECT_STATUSES, row.status).type" size="small">
              {{ statusMeta(PROJECT_STATUSES, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="需求（完成/总数）" width="140">
          <template #default="{ row }">{{ row.done_count }} / {{ row.total_requirements }}</template>
        </el-table-column>
        <el-table-column label="自动完成率" width="160">
          <template #default="{ row }">
            <el-progress :percentage="Math.round(row.completion_rate * 100)" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column prop="completed_in_period" label="本期完成" width="90" />
        <el-table-column label="延期需求" min-width="260">
          <template #default="{ row }">
            <template v-if="row.delayed_requirements.length">
              <div v-for="d in row.delayed_requirements" :key="d.requirement_id" style="font-size: 13px">
                {{ d.title }}
                <span style="color: #909399">（{{ d.overdue_stages.map((s) => stageLabel(s.stage_type)).join('、') || '人工标记' }}）</span>
              </div>
            </template>
            <span v-else style="color: #909399">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.stage-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.delayed-item {
  margin-bottom: 10px;
}
</style>
