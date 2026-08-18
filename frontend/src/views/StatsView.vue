<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { REQ_STATUSES, PROJECT_STATUSES, STAGE_TYPES, statusMeta, stageLabel, fmtTime } from '../format'

const weekDate = ref(new Date().toISOString().slice(0, 10))
const month = ref(new Date().toISOString().slice(0, 7))
const overview = ref(null)
const reqReport = ref(null)
const projReport = ref(null)
const period = ref('weekly')
const refreshing = ref(false)
const delayedExpanded = ref(false)
const DELAYED_PREVIEW_COUNT = 3

const STATUS_COLORS = { not_started: '#a8b1c2', in_progress: '#5475f7', delayed: '#ed6a5e', paused: '#e5a04f', done: '#48ad83' }
const statusTotal = computed(() => Object.values(overview.value?.status_distribution || {}).reduce((sum, count) => sum + count, 0))
const statusSlices = computed(() => REQ_STATUSES.map((status) => ({ ...status, count: overview.value?.status_distribution?.[status.value] || 0, color: STATUS_COLORS[status.value] })))
const stageMax = computed(() => Math.max(1, ...Object.values(overview.value?.stage_distribution || {})))
const stagePercent = (stage) => Math.round(((overview.value?.stage_distribution?.[stage] || 0) / stageMax.value) * 100)
const trendMax = computed(() => Math.max(1, ...(reqReport.value?.weekly_trend || []).flatMap((item) => [item.new_count, item.completed_count, item.new_delayed_count])))
const trendHeight = (value) => `${value ? Math.max(12, Math.round((value / trendMax.value) * 100)) : 3}%`
const reasonMax = computed(() => Math.max(1, ...(reqReport.value?.top_delay_reasons || []).map((item) => item.count)))
const reasonPercent = (count) => Math.round((count / reasonMax.value) * 100)
const visibleDelayed = computed(() => {
  const items = overview.value?.delayed_list || []
  return delayedExpanded.value ? items : items.slice(0, DELAYED_PREVIEW_COUNT)
})
const hasMoreDelayed = computed(() => (overview.value?.delayed_list?.length || 0) > DELAYED_PREVIEW_COUNT)

async function refreshReports() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const suffix = period.value === 'weekly'
      ? `weekly?date=${weekDate.value}`
      : `monthly?month=${month.value}`
    const [nextOverview, nextReqReport, nextProjReport] = await Promise.all([
      api.get('/stats/overview'),
      api.get(`/stats/requirements/${suffix}`),
      api.get(`/stats/projects/${suffix}&status=all`),
    ])
    overview.value = nextOverview
    reqReport.value = nextReqReport
    projReport.value = nextProjReport
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    refreshing.value = false
  }
}
function load() { refreshReports() }
function loadMonthly() { refreshReports() }
function switchPeriod(value) {
  period.value = value
  delayedExpanded.value = false
  refreshReports()
}
function toggleDelayed() { delayedExpanded.value = !delayedExpanded.value }

let refreshTimer
onMounted(() => {
  refreshReports()
  refreshTimer = window.setInterval(refreshReports, 60_000)
  window.addEventListener('focus', refreshReports)
})
onBeforeUnmount(() => {
  window.clearInterval(refreshTimer)
  window.removeEventListener('focus', refreshReports)
})
</script>

<template>
  <div class="page stats-page">
    <div class="page-header">
      <div class="page-heading"><h2 class="page-title">统计分析</h2><p class="page-sub">当前进展总览 · 需求与项目周/月报</p></div>
      <div class="controls">
        <el-radio-group :model-value="period" @update:model-value="switchPeriod"><el-radio-button value="weekly">周报</el-radio-button><el-radio-button value="monthly">月报</el-radio-button></el-radio-group>
        <el-date-picker v-if="period === 'weekly'" v-model="weekDate" type="date" value-format="YYYY-MM-DD" placeholder="选择日期（取所在自然周）" @change="load" />
        <el-date-picker v-else v-model="month" type="month" value-format="YYYY-MM" placeholder="选择月份" @change="loadMonthly" />
      </div>
    </div>

    <el-row v-if="overview" :gutter="12" class="summary-grid block">
      <el-col v-for="status in statusSlices" :key="status.value" :xs="12" :sm="8" :md="4"><el-card shadow="never" class="stat-card"><span class="stat-accent" :style="{ background: status.color }" /><div class="stat-value">{{ status.count }}</div><div class="stat-label">{{ status.label }}</div></el-card></el-col>
      <el-col :xs="12" :sm="8" :md="4"><el-card shadow="never" class="stat-card stat-total"><span class="stat-accent" /><div class="stat-value">{{ statusTotal }}</div><div class="stat-label">需求总数</div></el-card></el-col>
    </el-row>

    <el-row v-if="overview" :gutter="14" class="block overview-row">
      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="visual-card"><template #header><div class="card-header-line"><span class="card-title">环节在途分布</span><span class="card-note">按当前在途环节统计</span></div></template>
          <div class="stage-chart" role="img" aria-label="各环节在途数量"><div v-for="stage in STAGE_TYPES" :key="stage.value" class="stage-row"><span class="stage-name">{{ stage.label }}</span><div class="stage-track"><div class="stage-fill" :style="{ width: `${stagePercent(stage.value)}%` }" /></div><strong>{{ overview.stage_distribution[stage.value] || 0 }}</strong></div></div>
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="10" class="delayed-col">
        <el-card shadow="never" class="visual-card delayed-card"><template #header><div class="card-header-line"><span class="card-title">当前延期关注</span><span class="card-note">{{ overview.delayed_list.length }} 项 · 自动同步</span></div></template>
          <el-empty v-if="!overview.delayed_list.length" description="暂无延期需求" :image-size="54" />
          <template v-else><div class="delayed-list" :class="{ expanded: delayedExpanded }"><router-link v-for="item in visibleDelayed" :key="item.requirement_id" :to="`/requirements/${item.requirement_id}`" class="delayed-item"><span class="delayed-alert">!</span><div class="delayed-content"><strong>{{ item.title }}</strong><p v-if="item.overdue_stages.length">{{ item.overdue_stages.map((stage) => `${stage.stage_label} 逾期 ${stage.overdue_days} 天`).join('；') }}</p><p v-else>人工标记：{{ item.manual_delay_reason || '待补充原因' }}</p></div></router-link></div><el-button v-if="hasMoreDelayed" link class="delayed-toggle" @click="toggleDelayed">{{ delayedExpanded ? '收起延期清单' : `展开更多延期需求（${overview.delayed_list.length - DELAYED_PREVIEW_COUNT}）` }} <span>{{ delayedExpanded ? '⌃' : '⌄' }}</span></el-button></template>
        </el-card>
      </el-col>
    </el-row>

    <el-card v-if="reqReport" shadow="never" class="block report-card"><template #header><div class="card-header-line"><span class="card-title">需求{{ period === 'weekly' ? '周报' : '月报' }}</span><span class="period-range">{{ fmtTime(reqReport.period_start) }} ～ {{ fmtTime(reqReport.period_end) }}</span></div></template>
      <el-row :gutter="10" class="report-metrics">
        <el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>本期新增</span><strong>{{ reqReport.new_count }}</strong></div></el-col><el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>本期完成</span><strong class="success">{{ reqReport.completed_count }}</strong></div></el-col><el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>新产生延期</span><strong class="danger">{{ reqReport.new_delayed_count }}</strong></div></el-col><el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>当前延期</span><strong class="danger">{{ reqReport.current_delayed_count }}</strong></div></el-col><el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>延期率</span><strong class="warning">{{ (reqReport.delay_rate * 100).toFixed(1) }}%</strong></div></el-col><el-col :xs="12" :sm="8" :md="4"><div class="report-metric"><span>未完成总数</span><strong>{{ reqReport.unfinished_count }}</strong></div></el-col>
      </el-row>
      <div class="report-insights">
        <section class="adjustment-panel"><div class="insight-title">排期调整</div><div class="adjustment-values"><span>顺延 <strong>{{ reqReport.postponed_count }}</strong></span><span>提前 <strong>{{ reqReport.advanced_count }}</strong></span></div><div class="adjustment-bar"><i class="postponed" :style="{ width: `${reqReport.postponed_count + reqReport.advanced_count ? (reqReport.postponed_count / (reqReport.postponed_count + reqReport.advanced_count)) * 100 : 50}%` }" /></div><div class="adjustment-key"><span><i class="postponed" />顺延</span><span><i class="advanced" />提前</span></div></section>
        <section class="reason-panel"><div class="insight-title">Top 延期原因</div><div v-if="reqReport.top_delay_reasons.length" class="reason-bars"><div v-for="reason in reqReport.top_delay_reasons" :key="reason.reason" class="reason-row"><span :title="reason.reason">{{ reason.reason }}</span><div><i :style="{ width: `${reasonPercent(reason.count)}%` }" /></div><strong>{{ reason.count }}</strong></div></div><div v-else class="empty-text">本期暂无顺延调整记录</div></section>
      </div>
      <template v-if="reqReport.weekly_trend"><el-divider content-position="left">每周趋势</el-divider><div class="trend-legend"><span><i class="new" />新增</span><span><i class="complete" />完成</span><span><i class="delay" />新产生延期</span></div><div class="trend-chart" role="img" aria-label="每周新增、完成和延期趋势"><div v-for="item in reqReport.weekly_trend" :key="item.week_start" class="trend-group" :title="`${fmtTime(item.week_start)}：新增 ${item.new_count}，完成 ${item.completed_count}，延期 ${item.new_delayed_count}`"><div class="trend-columns"><i class="new" :style="{ height: trendHeight(item.new_count) }" /><i class="complete" :style="{ height: trendHeight(item.completed_count) }" /><i class="delay" :style="{ height: trendHeight(item.new_delayed_count) }" /></div><span>{{ fmtTime(item.week_start).slice(5) }}</span></div></div></template>
      <div v-else class="weekly-tip">切换至月报，可查看按自然周聚合的新增、完成与延期趋势。</div>
    </el-card>

    <el-card v-if="projReport" shadow="never" class="project-card"><template #header><div class="card-header-line"><span class="card-title">项目{{ period === 'weekly' ? '周报' : '月报' }}</span><span class="card-note">项目完成与延期情况</span></div></template>
      <el-empty v-if="!projReport.projects.length" description="暂无项目数据" :image-size="54" />
      <template v-else><el-table :data="projReport.projects" size="small" class="project-table"><el-table-column prop="name" label="项目" min-width="150" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusMeta(PROJECT_STATUSES, row.status).type" size="small" round>{{ statusMeta(PROJECT_STATUSES, row.status).label }}</el-tag></template></el-table-column><el-table-column label="需求（完成/总数）" width="140"><template #default="{ row }">{{ row.done_count }} / {{ row.total_requirements }}</template></el-table-column><el-table-column label="完成率" width="150"><template #default="{ row }"><el-progress :percentage="Math.round(row.completion_rate * 100)" :stroke-width="9" /></template></el-table-column><el-table-column prop="completed_in_period" label="本期完成" width="90" /><el-table-column label="延期需求" min-width="260"><template #default="{ row }"><template v-if="row.delayed_requirements.length"><div v-for="item in row.delayed_requirements" :key="item.requirement_id" class="delayed-proj">{{ item.title }} <span>（{{ item.overdue_stages.map((stage) => stageLabel(stage.stage_type)).join('、') || '人工标记' }}）</span></div></template><span v-else class="empty-text">—</span></template></el-table-column></el-table>
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.controls{display:flex;gap:12px;align-items:center}.block{margin-bottom:14px}.summary-grid{margin-bottom:14px}.stat-card{position:relative;overflow:hidden;text-align:left;border-color:#e8edf5;background:linear-gradient(140deg,#fff 0%,#f8faff 100%)}.stat-card :deep(.el-card__body){padding:17px}.stat-accent{display:block;position:absolute;top:0;left:0;width:100%;height:3px}.stat-total .stat-accent{background:#293a59}.stat-value{font-size:29px;font-weight:760;line-height:1.2;color:#25334d;font-variant-numeric:tabular-nums}.stat-label{margin-top:6px;font-size:13px;color:var(--pm-text-sub)}.visual-card,.delayed-card,.report-card,.project-card{border-color:#e5ebf4}.card-header-line{display:flex;align-items:baseline;justify-content:space-between;gap:10px}.card-note,.period-range{color:var(--pm-text-sub);font-size:12px;font-weight:400}.donut-layout{display:flex;align-items:center;gap:24px;min-height:185px;padding:4px}.status-donut{display:grid;flex:0 0 148px;width:148px;height:148px;place-items:center;border-radius:50%}.donut-hole{display:flex;width:98px;height:98px;flex-direction:column;align-items:center;justify-content:center;border-radius:50%;background:#fff;box-shadow:0 2px 14px rgb(42 63 96 / 8%)}.donut-hole strong{color:#273750;font-size:28px;line-height:1}.donut-hole span{margin-top:5px;color:var(--pm-text-sub);font-size:11px}.status-legend{flex:1;min-width:0}.legend-row{display:grid;grid-template-columns:8px minmax(42px,1fr) auto 31px;align-items:center;gap:7px;padding:5px 0;color:#526076;font-size:12px}.legend-dot{width:8px;height:8px;border-radius:50%}.legend-row strong{color:#34425b;font-variant-numeric:tabular-nums}.legend-row small{color:#9aa6b9;text-align:right}.stage-chart{padding:3px 2px}.stage-row{display:grid;grid-template-columns:92px minmax(80px,1fr) 28px;align-items:center;gap:10px;margin:13px 0}.stage-name{color:#506077;font-size:13px}.stage-track,.project-progress-track{overflow:hidden;height:9px;border-radius:999px;background:#edf1f7}.stage-fill{height:100%;min-width:3px;border-radius:inherit;background:linear-gradient(90deg,#7d95ff,#5373f7);transition:width .35s ease}.stage-row strong{color:#43516a;font-size:13px;text-align:right}.delayed-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:10px}.delayed-item{display:flex;gap:10px;align-items:center;min-width:0;padding:12px;border:1px solid #fee4e1;border-radius:9px;background:linear-gradient(115deg,#fffafa,#fff);color:inherit;text-decoration:none}.delayed-alert{display:grid;width:23px;height:23px;flex:0 0 23px;place-items:center;border-radius:50%;background:#fce4e1;color:#dd5c53;font-weight:800}.delayed-content{min-width:0;flex:1}.delayed-content strong{display:block;overflow:hidden;color:#3f4a5d;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.delayed-content p{margin:4px 0 0;color:#9b655f;font-size:12px;line-height:1.45}.delayed-arrow{color:#d99790;font-size:23px}.report-metrics{margin-bottom:18px}.report-metric{min-height:82px;padding:13px 14px;border:1px solid #e9edf4;border-radius:9px;background:#fbfcfe}.report-metric span{display:block;color:var(--pm-text-sub);font-size:12px}.report-metric strong{display:block;margin-top:6px;color:#34425b;font-size:24px;line-height:1;font-variant-numeric:tabular-nums}.report-metric .success{color:#46a679}.report-metric .danger{color:#df655a}.report-metric .warning{color:#d68e3e}.report-insights{display:grid;grid-template-columns:minmax(220px,.8fr) minmax(300px,1.4fr);gap:14px}.adjustment-panel,.reason-panel{padding:15px;border-radius:10px;background:#f7f9fd}.insight-title{margin-bottom:13px;color:#45536b;font-size:13px;font-weight:700}.adjustment-values{display:flex;justify-content:space-between;color:#78859a;font-size:12px}.adjustment-values strong{margin-left:4px;color:#3f4c63;font-size:18px}.adjustment-bar{display:flex;overflow:hidden;height:8px;margin:11px 0;border-radius:99px;background:#7bc3a7}.adjustment-bar .postponed{display:block;height:100%;background:#ee927d}.adjustment-key,.trend-legend{display:flex;gap:14px;color:#8190a5;font-size:11px}.adjustment-key span,.trend-legend span{display:inline-flex;align-items:center;gap:5px}.adjustment-key i,.trend-legend i{display:inline-block;width:7px;height:7px;border-radius:2px}.postponed,.delay{background:#ed8978}.advanced,.complete{background:#65b48f}.new{background:#627ff6}.reason-bars{display:grid;gap:8px}.reason-row{display:grid;grid-template-columns:minmax(90px,1fr) minmax(52px,1.7fr) 18px;gap:8px;align-items:center;color:#64728a;font-size:12px}.reason-row>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.reason-row>div{overflow:hidden;height:7px;border-radius:999px;background:#e8edf6}.reason-row i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#ffad92,#ed7f70)}.reason-row strong{color:#5d6b82;font-size:12px}.trend-legend{justify-content:flex-end;margin:-31px 0 10px}.trend-chart{display:flex;height:174px;align-items:flex-end;gap:8px;padding:8px 4px 0;border-bottom:1px solid #e8edf5}.trend-group{display:flex;height:100%;min-width:42px;flex:1;flex-direction:column;align-items:center;justify-content:flex-end;gap:7px}.trend-columns{display:flex;width:100%;height:136px;align-items:flex-end;justify-content:center;gap:4px}.trend-columns i{display:block;width:min(15px,24%);min-height:3px;border-radius:4px 4px 1px 1px}.trend-group>span{color:#8b97a9;font-size:11px;white-space:nowrap}.weekly-tip{margin-top:17px;padding:10px 12px;border-radius:7px;background:#f6f8fc;color:#8090a5;font-size:12px}.project-progress-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:12px}.project-progress-item{padding:12px 13px;border:1px solid #e7ecf4;border-radius:9px;background:#fbfcff}.project-progress-head{display:flex;justify-content:space-between;gap:8px}.project-progress-head strong{overflow:hidden;color:#435069;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.project-progress-head span{color:#4f73ed;font-size:13px;font-weight:700}.project-progress-track{margin:10px 0 8px}.project-progress-track i{display:block;height:100%;min-width:3px;border-radius:inherit;background:linear-gradient(90deg,#6e8aff,#5473ef)}.project-progress-item small{color:#8996a8;font-size:11px}.delayed-proj{margin:2px 0;color:#536078;font-size:13px}.delayed-proj span{color:#b07068}.empty-text{color:var(--pm-text-sub);font-size:12px}@media(max-width:900px){.stage-col{margin-top:14px}.report-insights{grid-template-columns:1fr}.summary-grid :deep(.el-col){margin-bottom:12px}}@media(max-width:640px){.controls{width:100%;flex-wrap:wrap}.controls :deep(.el-date-editor){flex:1;min-width:190px}.donut-layout{justify-content:center}.status-donut{flex-basis:126px;width:126px;height:126px}.donut-hole{width:82px;height:82px}.status-legend{max-width:180px}.stage-row{grid-template-columns:75px minmax(50px,1fr) 22px;gap:7px}.stage-name{font-size:12px}.trend-legend{justify-content:flex-start;margin:8px 0}.trend-chart{gap:3px}.trend-group{min-width:30px}.trend-group>span{font-size:10px}.project-progress-grid{grid-template-columns:1fr}}
.delayed-list { display: grid; gap: 8px; }
.delayed-list .delayed-item { padding: 10px; }
.report-insights { grid-template-columns: minmax(250px, 1fr) minmax(300px, 1.2fr); }
.overview-row :deep(.el-col) { display: flex; }
.overview-row .visual-card { width: 100%; min-height: 326px; flex: 1; }
.delayed-card :deep(.el-card__body) { display: flex; flex: 1; flex-direction: column; }
.delayed-card .delayed-list { flex: 1; max-height: 222px; overflow-y: auto; padding-right: 3px; }
.delayed-card .delayed-list.expanded { scrollbar-color: #c8d2e3 transparent; }
.delayed-toggle { align-self: center; margin-top: 8px; color: var(--pm-primary); font-size: 12px; }
.delayed-toggle span { margin-left: 4px; font-size: 14px; }
@media (max-width: 900px) { .delayed-col { margin-top: 14px; } }
</style>
