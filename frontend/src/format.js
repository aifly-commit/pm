// 展示常量与格式化工具
export const STAGE_TYPES = [
  { value: 'research', label: '需求调研' },
  { value: 'review', label: '需求审评' },
  { value: 'backend_dev', label: '平台开发' },
  { value: 'frontend_dev', label: '前端开发' },
  { value: 'api_dev', label: 'API 开发' },
  { value: 'testing', label: '测试' },
  { value: 'release', label: '上线' },
]

export const REQ_STATUSES = [
  { value: 'not_started', label: '未开始', type: 'info' },
  { value: 'in_progress', label: '进行中', type: 'primary' },
  { value: 'delayed', label: '延期', type: 'danger' },
  { value: 'paused', label: '暂停', type: 'warning' },
  { value: 'done', label: '已完成', type: 'success' },
]

export const STAGE_STATUSES = [
  { value: 'not_started', label: '未开始', type: 'info' },
  { value: 'in_progress', label: '进行中', type: 'primary' },
  { value: 'done', label: '已完成', type: 'success' },
]

export const PROJECT_STATUSES = [
  { value: 'not_started', label: '未启动', type: 'info' },
  { value: 'in_progress', label: '进行中', type: 'primary' },
  { value: 'done', label: '已完成', type: 'success' },
  { value: 'paused', label: '暂停', type: 'warning' },
  { value: 'terminated', label: '终止', type: 'danger' },
]

// 与后端 app/enums.py PRODUCT_LINES 保持一致
export const PRODUCT_LINES = [
  'MySQL', 'PostgreSQL', 'SQLServer', 'TiDB', '分布式数据库',
  'Redis', 'MongoDB', 'Memcached', 'Milvus', '记忆服务',
  '图服务', 'ClickHouse', 'RabbitMQ', 'DMP', 'DTS', 'DataAgent',
]

export function statusMeta(list, value) {
  return list.find((s) => s.value === value) || { label: value, type: 'info' }
}

export function stageLabel(type) {
  const s = STAGE_TYPES.find((x) => x.value === type)
  return s ? s.label : type
}

export function fmtTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

export function fmtDate(value) {
  if (!value) return '—'
  return String(value).slice(0, 10)
}
