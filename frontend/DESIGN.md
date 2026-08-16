# 前端设计规范（基线）

> **本文档为基线约定：后续所有前端设计与改动以此为基准，不另行开新风格。**
> 现状由 `src/theme.css`（设计令牌）+ `src/App.vue`（布局骨架）+ 各 View（页面模式）构成。

## 1. 技术栈与边界

- Vue 3（`<script setup>` 组合式 API）+ Element Plus（全量引入，中文 locale）+ vue-router（history 模式）
- **不引入** Pinia / unplugin 自动按需 / Tailwind——状态用模块级 ref（如 `api.js` 的 token），样式用令牌 + 少量 scoped CSS
- 数据层统一走 `src/api.js`；展示常量与格式化统一在 `src/format.js`，禁止在组件里散落映射表

## 2. 设计令牌（theme.css :root，唯一色值来源）

| 令牌 | 值 | 用途 |
|---|---|---|
| `--pm-primary` | `#4c6fff` | 品牌主色（覆盖 `--el-color-primary`） |
| `--pm-primary-deep` | `#3b57d9` | 主色 hover |
| `--pm-bg` | `#f2f4f9` | 页面底色 |
| `--pm-card-border` | `#e8ecf4` | 卡片/分割边框 |
| `--pm-text-main` / `--pm-text-sub` | `#1f2733` / `#7a8699` | 主/次文字 |
| `--pm-radius` | `10px` | 卡片圆角（EP 基础圆角 6px） |
| `--pm-shadow` | 双层柔和投影 | 卡片阴影 |

**规则：新颜色一律先进 `:root` 定义令牌再引用，组件内不许硬编码色值。**

## 3. 布局骨架（App.vue）

- **侧边栏**：216px 深色渐变（`#141c33→#1f2a4a`），可收起至 68px（宽度过渡 + 文字透明度渐隐，避免布局抖动）；品牌区（圆形渐变 logo）+ 导航（圆角 10px 导航项，激活态品牌色渐变高亮 + 投影）+ 底部用户区
- **主区**：`.page` 容器 `max-width: 1280px` 居中，进场 `pm-fade-in` 动画（0.25s 上浮淡入）
- 顶栏铃铛未读数 60 秒轮询（`refreshUnread`）

## 4. 页面结构模式（所有列表/详情页统一）

```
.page
├── .page-header        页头：左侧 .page-title(20px/700) + .page-sub(13px 灰)，
│                       右侧主操作按钮或 .controls（周期切换等）
├── .filter-card        筛选卡片（.toolbar 内排筛选控件 + 查询按钮）
├── .table-card / 内容卡片
└── 分页（右对齐）
```

- **详情页头部**：`head-card` 内 `← 返回` link + `title-text` + 状态 `el-tag round` + `head-meta` 次要信息行
- **卡片**：`el-card shadow="never"`（阴影交给全局样式），标题用 `.card-title`（自带品牌色竖条前缀）
- **统计卡**：`.stat-card`（`.stat-value` 大数字 + `.stat-label` 灰标签），可按状态加 `stat-{status}` 着色类
- **标签**：`el-tag round`；状态色映射统一 `format.js` 的 `statusMeta()`（延期 danger / 进行中 primary / 完成 success / 暂停 warning / 未开始 info）
- **进度**：`el-progress` `stroke-width: 10`

## 5. 交互模式

| 场景 | 约定 |
|---|---|
| 列表行跳详情 | 表格 `@row-click` + `cursor: pointer` |
| 创建 | 工具按钮开 `el-dialog` 表单，成功后跳详情或刷新列表 |
| 必填原因（改期/暂停/延期标记/回退） | `ElMessageBox.prompt` 校验非空；复杂表单（回退目标选择）用 dialog |
| 结果反馈 | 成功/失败一律 `ElMessage.success/error`，错误信息直接展示后端 `detail` |
| 会话过期 | 仅**非登录接口** 401 清 token 踢回 `/login`；登录接口 401 显示后端真实原因 |

## 6. 新增页面 Checklist

1. 色值/圆角/阴影只用令牌；页面结构复用第 4 节模式
2. 状态展示走 `statusMeta()` + `round` 标签；时间走 `fmtTime/fmtDate`
3. 数据请求全部经 `api.js`；筛选-查询-分页三件套命名与现有页一致（`filters` / `load` / `page`）
4. 权限相关按钮显隐参照现有 `canWrite / canWriteProject` 模式（Admin 或负责人）
5. 完成后 `npm run build` 必须通过
