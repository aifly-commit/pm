# 需求管理与项目管理平台 — 设计文档

- 版本：v1.1（含评审补充规则：状态机修复、回退规则、权限与 API 补全、统计口径澄清）
- 技术栈：Python 3.11+ / FastAPI / SQLite（SQLAlchemy + Alembic）/ APScheduler
- 提醒渠道：系统内通知（站内通知中心）

---

## 1. 概述

### 1.1 背景与目标

为产品团队提供一个统一的内部平台，解决两个核心问题：

1. **需求全生命周期管理**：一个需求从调研到上线要经历多个环节，每个环节有预估时间安排，到期自动提醒负责人，延期必须留痕（记录原因）。
2. **项目维度管理**：以项目为单位聚合对接的需求，跟踪接口人、项目进展与状态，支持按周/月复盘延期与完成情况。

### 1.2 两大模块的关系

- **需求管理模块**：管理"需求"从创建到上线的流程，是最小管理单元。
- **项目管理模块**：管理"项目"，一个项目通过"对接需求清单"聚合多个需求，项目进展由人工维护 + 需求完成情况自动汇总。

```
项目 (Project)  1 ──── n  需求 (Requirement)  1 ──── 7  环节 (Stage)
```

### 1.3 名词定义

| 名词 | 定义 |
|---|---|
| 需求 (Requirement) | 一条产品需求，平台管理的最小单元 |
| 环节 (Stage) | 需求经历的阶段，固定为 7 个：需求调研、需求审评、平台开发、前端开发、API 开发、测试、上线 |
| 预计开始/结束时间 | 产品经理对每个环节排期的预估值，可修改（需填原因） |
| 实际开始/结束时间 | 环节真实开始/完成的时间，由系统或人工记录 |
| 项目 (Project) | 一次对外/对内的合作或专项，对接一组需求 |
| 接口人 | 项目侧（外部合作方或内部协作方）的联系人 |
| 对接需求清单 | 项目下挂接的需求列表 |

---

## 2. 角色与权限

### 2.1 角色

| 角色 | 说明 |
|---|---|
| 产品经理 (PM) | 需求的负责人，创建需求、排期、推进环节、接收提醒 |
| 执行人 (Developer/Tester) | 环节的具体执行者（研发、测试），更新环节进度 |
| 管理员 (Admin) | 用户管理、环节模板配置、全量数据查看 |

### 2.2 权限矩阵

| 操作 | 产品经理 | 执行人 | 管理员 |
|---|---|---|---|
| 创建/编辑自己负责的需求 | ✅ | ❌ | ✅ |
| 查看所有需求 | ✅ | ✅ | ✅ |
| 设置/修改环节预估时间（须填原因） | ✅（仅自己负责的需求） | ❌ | ✅ |
| 更新环节实际进度（开始/完成） | ✅ | ✅（仅自己负责的环节） | ✅ |
| 暂停/恢复需求 | ✅（仅自己负责的需求） | ❌ | ✅ |
| 项目 CRUD、维护接口人 | ✅（仅自己负责的项目） | ❌ | ✅ |
| 指派/变更环节负责人 | ✅（仅自己负责的需求） | ❌ | ✅ |
| 查看统计报表 | ✅ | ✅ | ✅ |
| 用户管理 | ❌ | ❌ | ✅ |

> 说明：第一版权限从简，登录采用账号密码 + JWT，不接入企业 SSO。

补充约定：

- **人工标记延期**：PM 预知风险时可手动将需求标记为延期（须填写原因），该标记**不改变**系统派生的逾期判定；人工延期由 PM 手动解除（解除同样须填原因）。`requirements.status = delayed` 时，通过 `manual_delayed` 标记区分"系统逾期"与"人工标记"，二者任一存在即为延期态，二者均解除才回到进行中。
- **项目权限**：项目的 CRUD 与接口人维护限"项目负责人或 Admin"，任何 PM 不能修改他人负责的项目。
- **用户停用**：`is_active = FALSE` 的用户禁止登录；其名下仍挂有的需求 PM / 环节负责人角色，由 Admin 在用户管理中转交后再停用（第一版转交 = 批量改 `responsible_pm_id` / `assignee_id`）。停用用户不再接收任何通知（通知生成时过滤）。

---

## 3. 需求管理模块

### 3.1 环节流程

需求创建后，系统自动生成 7 个环节实例，按固定顺序流转：

```
需求调研 → 需求审评 → 平台开发 → 前端开发 → API 开发 → 测试 → 上线
```

流转规则：

- **串行推进**：当前环节完成后，下一环节才可标记开始（记录实际开始时间）。前端开发与 API 开发允许并行——平台开发完成后，两者可同时开始。
- **完成的前置校验**：`complete` 操作要求该环节当前状态为"进行中"（即已 start 且未完成）；否则返回 409。不允许跳过 start 直接 complete，也不允许完成前置环节未完成的环节（并行环节例外：前端/API 任一完成不受另一个是否完成的影响，但两者都完成后测试才可 start）。
- **回退**（详见下方回退规则）。
- 每个环节有唯一**环节状态**：未开始 / 进行中 / 已完成 / 已逾期（派生状态，见 3.3）。

**回退规则**：

- 允许的回退路径固定为：
  - `需求审评 → 需求调研`
  - `测试 → 平台开发 / 前端开发 / API 开发`（回退时由操作人指定目标环节，body 增加 `target_stage_id`，校验 target ∈ 允许集合）
- 回退操作必须填写原因（写入 `stage_revert_logs`，见 7.2）。
- 被回退的目标环节：状态置为"进行中"，`actual_end` 清空，`actual_start` 保留（重新计时只重算结束）。
- 目标环节**之后**的所有环节（不含并行兄弟环节）：状态重置为"未开始"，`actual_start` / `actual_end` 清空。例：从测试回退到平台开发时，前端开发、API 开发（若已完成）也一并重置——因为它们依赖平台开发的产出；从测试回退到前端开发时，平台开发保持已完成，API 开发按上述规则判断（API 开发在目标之后且非并行兄弟，重置）。
- 回退后需求级状态重算：按 3.3 口径即时重算（通常回到"进行中"）。
- "上线"环节不可被回退（上线完成 = 需求已完成，终态）；已完成的需求不可回退。

### 3.2 环节字段

每个环节实例包含：

| 字段 | 说明 |
|---|---|
| 环节类型 | 7 种之一，创建需求时自动生成 |
| 负责人 | 该环节的执行人（可空，由 PM 指派） |
| 预计开始时间 | PM 排期填写，可修改（须填原因） |
| 预计结束时间 | PM 排期填写，可修改（须填原因） |
| 实际开始时间 | 环节标记"开始"时由系统记录 |
| 实际结束时间 | 环节标记"完成"时由系统记录 |
| 延期原因 | 最近一次修改预估时间时填写的原因 |

**预估时间校验规则**（创建与修改时均强制）：

- `planned_end ≥ planned_start`（同一环节内）。
- 后一环节的 `planned_start` ≥ 前一环节的 `planned_end`（并行环节取共同前置，即平台开发）：前端开发、API 开发的 `planned_start` ≥ 平台开发的 `planned_end`；测试的 `planned_start` ≥ max(平台开发, 前端开发, API 开发) 的 `planned_end`。修改某环节时间导致下游约束破坏时，要么整体报错，要么提示一并调整（第一版：整体报错，返回具体冲突字段）。
- 创建需求时预估时间可整体留空（NULL），NULL 的环节不参与逾期判定与临期提醒；一旦填写则按上述规则校验。
- 环节负责人指派/变更通过 `PATCH /requirements/{id}`（body 中 stages 数组）或 `PATCH /stages/{id}/assignee` 完成，仅 PM（自己负责的需求）与 Admin 可操作。

### 3.3 需求状态机

需求整体状态（`requirement.status`）：

| 状态 | 含义 | 进入方式 |
|---|---|---|
| 未开始 | 需求已创建，第一个环节未开始 | 创建后默认 |
| 进行中 | 任一环节进行中 | 首个环节开始 |
| 已完成 | "上线"环节完成 | 上线环节完成 |
| 延期 | 存在环节当前时间 > 预计结束时间且环节未完成（系统逾期），或被 PM 人工标记 | 系统自动判定 + 人工标记，二者独立（见下） |
| 暂停 | 需求被人工挂起 | PM 手动操作，可随时恢复 |

状态转换表：

| 当前状态 | 允许操作 | 目标状态 |
|---|---|---|
| 未开始 | 开始首个环节 | 进行中 |
| 未开始 | 环节逾期（系统检测） | 延期 |
| 未开始 | 暂停 | 暂停 |
| 进行中 | 暂停 | 暂停 |
| 进行中 | 上线环节完成 | 已完成 |
| 进行中 | 环节逾期（系统检测） | 延期 |
| 进行中 | PM 人工标记延期（须填原因） | 延期 |
| 延期 | 逾期环节完成且无其他逾期、且无人工标记 | 进行中 |
| 延期 | PM 解除人工延期（须填原因） | 进行中（若同时无系统逾期） |
| 延期 | 上线环节完成 | 已完成 |
| 延期 | 暂停 | 暂停 |
| 暂停 | 恢复 | 按当前时间重新判定（进行中/延期） |
| 已完成 | （终态，不可回退） | — |

**状态判定与刷新机制**：

- "延期"的判定口径：**当前时间 > 任一未完成环节的预计结束时间**（planned_end 为 NULL 的环节不参与）。系统逾期与人工标记两个来源独立记录（`requirements.manual_delayed` 布尔字段），`status = delayed` 当且仅当二者任一成立；全部解除后回到"进行中"。
- **状态重算在写操作中同步执行**：start / complete / revert / 改期 / 暂停 / 恢复 / 人工标记(解除)延期等操作落库时立即重算需求状态并刷新，**不依赖定时任务**；30 分钟定时任务仅作为兜底（覆盖时间自然流逝导致的逾期）。
- **暂停的时钟处理**：暂停时记录 `paused_at`，该需求所有未完成环节**冻结逾期判定**（暂停期间不判定逾期、不产生临期/逾期通知）；恢复时对暂停期间的未完成环节的 `planned_start` / `planned_end` **统一顺延** `暂停时长`（自然日口径，写入变更历史，原因自动记录为"需求暂停顺延"，不计入人工"延期调整次数"统计），然后按新时间重新判定状态。
- **逾期扫描的范围**：需求状态为 done（终态）或 paused（冻结判定）的不参与；**未开始的需求参与**——首个环节即使还没 start，其 planned_end 超期同样判定逾期（排了期不启动也算延期）。

### 3.4 修改预估时间规则（核心约束）

1. 修改任一环节的预计开始/结束时间时，**必须填写延期原因**（非空，接口层强制校验）。
2. 每次修改写入 `stage_time_change_logs` 变更历史：操作人、操作时间、修改字段、原值、新值、原因。
3. 变更历史在需求详情页可见，且纳入周/月统计的"延期调整次数"。
4. 已完成的环节不允许再修改预估时间。

### 3.5 需求基础字段

| 字段 | 说明 |
|---|---|
| 标题 | 必填 |
| 描述 | 富文本/Markdown，需求背景与内容 |
| 优先级 | P0 / P1 / P2 / P3 |
| 负责产品经理 | 必填，关联用户 |
| 关联项目 | 可空，关联项目（一个需求最多属于一个项目） |
| 当前环节 | 派生字段：当前进行中或下一个待开始的环节。**并行窗口期**（前端开发与 API 开发同时在途）取 seq 较小者展示为"前端开发(并行)"，筛选按"命中任一在途环节"匹配 |
| 状态 | 见 3.3 |
| 创建时间 / 更新时间 | 系统维护 |

---

## 4. 提醒机制（系统内通知）

### 4.1 触发规则

| 通知类型 | 触发条件 | 接收人 |
|---|---|---|
| 环节临期提醒 | 距环节预计结束时间 ≤ N 天（默认 1 天，可配置）且环节未完成 | 该需求的负责产品经理 + 该环节负责人（若有） |
| 环节到期/逾期提醒 | 当前时间 > 环节预计结束时间且环节未完成 | 该需求的负责产品经理 + 该环节负责人（若有） |
| 环节临开始提醒 | 距环节预计开始时间 ≤ N 天（默认 1 天）且环节未开始 | 该需求的负责产品经理 + 该环节负责人（若有）（可选，默认关闭） |
| 需求状态变更 | 需求被暂停/恢复/完成/回退/人工标记(解除)延期 | 该需求的负责产品经理及相关环节负责人 |

补充规则：

- **暂停中的需求不产生任何时间触发型通知**（临期/逾期），状态变更通知正常产生。
- **改期后重置提醒标记**：`PATCH /stages/{id}/plan` 修改 `planned_end` 成功后，将该环节 `reminder_sent` 重置为 FALSE，使新的截止时间临近时能再次触发临期提醒；同时该环节当日已发的逾期通知不撤销，新 `planned_end` 再次超期后按新自然日继续去重发送。
- **通知去重只适用于时间触发型**（`stage_due_soon` / `stage_overdue` / `stage_start_soon`），使用 `dedupe_key = {stage_id}:{type}:{yyyy-mm-dd}:{user_id}`（按接收人区分，保证每人每天每环节每类型最多一条）；`status_changed` 类型**不参与去重**（`dedupe_key` 置 NULL），同一状态变更同日多次发生均生成通知。
- **接收人过滤**：`is_active = FALSE` 的用户与环节负责人为空的环节跳过对应接收人，只发给剩余有效接收人；PM 为必发接收人（若 PM 被停用则该通知不生成，由 Admin 转交流程处理）。

### 4.2 实现方案

- 使用 **APScheduler**（AsyncIOScheduler）随 FastAPI 进程启动，每 **30 分钟**扫描一次：
  1. 查询所有"未完成环节"中预计结束时间已过或临近的记录（**排除**：所属需求状态为 paused / done 的环节，planned_end 为 NULL 的环节）；
  2. 比对去重条件，生成 `notifications` 记录；
  3. 兜底刷新受影响需求的 `status`（进行中 ↔ 延期）。用户写操作（start/complete/改期等）已在请求内同步刷新状态，本扫描仅覆盖时间自然流逝导致的逾期。
- **防重复策略**：以 `(stage_id, notification_type, 自然日)` 为去重键——同一环节同一类型的逾期通知每天最多一条；临期通知同一环节只发一次（记录已发标记，改期后重置，见 4.1）。
- **多 worker 约束**：定时任务随后端进程运行，生产部署**必须 `uvicorn --workers 1`**（或使用 gunicorn 单 worker + uvicorn worker）；若未来需要多 worker，须将调度迁移到独立进程或数据库抢占锁，避免重复扫描与重复通知。
- **时区约定**：全平台统一使用 **Asia/Shanghai** 时区（服务器时间、数据库 DATETIME、通知去重的"自然日"、统计的自然周/月均按此时区计算）；API 传输时间带时区偏移的 ISO 8601（如 `2026-08-14T10:00:00+08:00`），入库前统一转换为本地-naive 的该时区时间存储。
- 用户在前端通过轮询（如每 60 秒）或进入页面时拉取未读通知数，第一版不做 WebSocket 推送。

### 4.3 通知中心

- 通知字段：类型、标题、内容、关联需求 ID、关联环节 ID、接收人、是否已读、创建时间。
- 支持：按未读/全部筛选、单条已读、全部已读、点击跳转需求详情页对应环节。

---

## 5. 项目管理模块

### 5.1 项目字段

| 字段 | 说明 |
|---|---|
| 项目名称 | 必填 |
| 项目描述 | 项目背景、目标 |
| 接口人 | 可多个，存姓名 + 联系方式（电话/邮箱/IM），独立于平台用户 |
| 对接需求清单 | 关联的需求列表（需求侧反向关联） |
| 项目进展 | 人工维护的进展摘要（Markdown）+ 进度百分比；同时展示由需求完成情况自动计算的完成率 |
| 项目状态 | 未启动 / 进行中 / 已完成 / 暂停 / 终止 |
| 计划开始/结束时间 | 项目级排期 |
| 实际开始/结束时间 | 系统或人工记录 |
| 负责人 | 平台内的产品经理 |

### 5.2 项目与需求的关联

- 一个项目对接 **多个**需求；一个需求最多属于 **一个**项目（`requirements.project_id` 外键，第一版不做多对多，降低复杂度）。
- 项目详情页展示"对接需求清单"：每条需求的标题、当前环节、状态、是否延期。
- 项目自动完成率 = 项目下已完成需求数 / 需求总数。

---

## 6. 统计分析模块

### 6.1 需求维度

- **当前进展总览**：
  - 按状态分布：未开始 / 进行中 / 延期 / 暂停 / 已完成 各多少条；
  - 按环节在途分布：7 个环节各有多少条需求正处于该环节；
  - 当前延期需求清单（含逾期环节、逾期天数、负责人）。
- **周报表**（自然周，周一 00:00 ~ 周日 24:00）：
  - 本周新增需求数、本周完成需求数（上线环节实际结束时间在本周）；
  - 本周新产生的延期需求数（**按需求去重**：同一需求本周内多次进入延期态只计 1 次）、**当前处于延期态的需求数**（"累计延期"口径 = 报表截止时刻 status = delayed 的需求数）、延期率 = 当前延期数 / 未完成总数（未完成 = status ∈ 未开始/进行中/延期）；
  - 本周预估时间调整次数（按变更历史统计，**仅统计 new_value > old_value 的顺延调整**；提前调整单独计数展示）及 Top 延期原因（仅基于顺延调整的原因）。
- **月报表**：口径同周报，按自然月聚合；另给出每周趋势（新增/完成/延期三条曲线）。

### 6.2 项目维度

- **周/月查看**：选择周/月后，展示每个进行中项目：
  - 项目下需求完成情况（本期完成数 / 总数、自动完成率）；
  - 项目下延期需求数、延期明细（需求、逾期环节、逾期天数、最近延期原因）；
  - 项目进展摘要与状态。
- 支持按项目状态、负责人筛选。

### 6.3 统计口径定义

- **延期判定**：存在任一环节满足 `当前时间 > 预计结束时间 且 环节未完成`（planned_end 为 NULL 的环节不参与；暂停中的需求不参与；与 3.3 状态判定同一口径）。
- **逾期天数**：`当前日期 - 预计结束日期`（自然日）。
- **本周/本月完成**：上线环节的实际结束时间落在统计周期内。
- **"曾延期"口径**（用于复盘）：需求在周期内**曾经**进入过 delayed 状态即计入（去重），与"当前延期"区分展示，不参与延期率计算。
- **暂停顺延不统计**：需求暂停恢复触发的自动时间顺延（原因 = "需求暂停顺延"）不计入"预估时间调整次数"与"Top 延期原因"。
- 报表均为**查询时实时计算**（数据量小，无需预聚合表），保证口径一致。

---

## 7. 数据模型设计

### 7.1 ER 关系

```
users 1 ──── n requirements (responsible_pm_id)
users 1 ──── n projects (owner_id)
projects 1 ──── n requirements (project_id)
requirements 1 ──── 7 requirement_stages
requirement_stages 1 ──── n stage_time_change_logs
requirements 1 ──── n stage_revert_logs
users 1 ──── n notifications
```

### 7.2 表结构

**users**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| username | VARCHAR(64) UNIQUE NOT NULL | 登录名 |
| password_hash | VARCHAR(255) NOT NULL | bcrypt |
| display_name | VARCHAR(64) NOT NULL | 显示名 |
| role | VARCHAR(16) NOT NULL | `pm` / `developer` / `tester` / `admin` |
| is_active | BOOLEAN DEFAULT TRUE | |
| created_at | DATETIME | |

**projects**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| name | VARCHAR(128) NOT NULL | |
| description | TEXT | |
| contacts | TEXT | 接口人列表，JSON：`[{"name":"张三","phone":"...","email":"..."}]` |
| progress_note | TEXT | 人工维护的进展摘要 |
| progress_percent | INTEGER DEFAULT 0 | 人工维护的进度百分比 0–100 |
| status | VARCHAR(16) NOT NULL DEFAULT 'not_started' | `not_started`/`in_progress`/`done`/`paused`/`terminated` |
| planned_start / planned_end | DATE | |
| actual_start / actual_end | DATE NULL | |
| owner_id | INTEGER FK → users.id | 负责人 |
| created_at / updated_at | DATETIME | |

**requirements**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| title | VARCHAR(200) NOT NULL | |
| description | TEXT | |
| priority | VARCHAR(4) NOT NULL DEFAULT 'P2' | P0–P3 |
| status | VARCHAR(16) NOT NULL DEFAULT 'not_started' | `not_started`/`in_progress`/`delayed`/`paused`/`done` |
| manual_delayed | BOOLEAN DEFAULT FALSE | PM 人工标记的延期（与系统逾期独立，见 3.3） |
| manual_delay_reason | TEXT NULL | 最近一次人工标记/解除延期的原因 |
| responsible_pm_id | INTEGER FK → users.id NOT NULL | |
| project_id | INTEGER FK → projects.id NULL | |
| paused_from | VARCHAR(16) NULL | 暂停前的状态，用于恢复 |
| paused_at | DATETIME NULL | 最近一次暂停时间，恢复时计算顺延时长 |
| created_at / updated_at | DATETIME | |

索引：`(status)`、`(responsible_pm_id)`、`(project_id)`。

**requirement_stages**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| requirement_id | INTEGER FK → requirements.id NOT NULL | |
| stage_type | VARCHAR(32) NOT NULL | `research`/`review`/`backend_dev`/`frontend_dev`/`api_dev`/`testing`/`release` |
| seq | INTEGER NOT NULL | 顺序 1–7 |
| status | VARCHAR(16) NOT NULL DEFAULT 'not_started' | `not_started`/`in_progress`/`done` |
| assignee_id | INTEGER FK → users.id NULL | 环节负责人 |
| planned_start / planned_end | DATETIME NULL | 预估时间 |
| actual_start / actual_end | DATETIME NULL | 实际时间 |
| last_delay_reason | TEXT | 最近一次延期原因 |
| reminder_sent | BOOLEAN DEFAULT FALSE | 临期提醒是否已发（防重复） |

索引：`(requirement_id, seq)` 唯一；`(planned_end, status)` 用于定时扫描。

**stage_time_change_logs**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| stage_id | INTEGER FK → requirement_stages.id NOT NULL | |
| changed_by | INTEGER FK → users.id NOT NULL | 操作人 |
| field | VARCHAR(16) NOT NULL | `planned_start` / `planned_end` |
| old_value / new_value | DATETIME NULL | 原值/新值；首次排期时原值为 NULL |
| reason | TEXT NOT NULL | 延期原因（强制非空） |
| auto_generated | BOOLEAN DEFAULT FALSE | TRUE = 系统自动产生（如暂停顺延），统计时排除 |
| created_at | DATETIME | |

索引：`(stage_id)`、`(created_at)`（统计用）。

**stage_revert_logs**（回退留痕）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| requirement_id | INTEGER FK → requirements.id NOT NULL | |
| from_stage_id | INTEGER FK → requirement_stages.id NOT NULL | 回退发起环节 |
| to_stage_id | INTEGER FK → requirement_stages.id NOT NULL | 回退目标环节 |
| reverted_by | INTEGER FK → users.id NOT NULL | 操作人 |
| reason | TEXT NOT NULL | 回退原因（强制非空） |
| created_at | DATETIME | |

索引：`(requirement_id)`。

**notifications**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK → users.id NOT NULL | 接收人 |
| type | VARCHAR(32) NOT NULL | `stage_due_soon`/`stage_overdue`/`stage_start_soon`/`status_changed` |
| title | VARCHAR(200) NOT NULL | |
| content | TEXT | |
| requirement_id | INTEGER FK → requirements.id NULL | |
| stage_id | INTEGER FK → requirement_stages.id NULL | |
| dedupe_key | VARCHAR(128) UNIQUE NULL | 防重复：`{stage_id}:{type}:{yyyy-mm-dd}:{user_id}`（含接收人——同一提醒发给多人时各自成行，键须按人区分才能保持唯一）；仅时间触发型使用，`status_changed` 置 NULL 不去重 |
| is_read | BOOLEAN DEFAULT FALSE | |
| created_at | DATETIME | |

索引：`(user_id, is_read)`。

---

## 8. API 设计（FastAPI / REST）

统一约定：前缀 `/api/v1`；认证用 JWT Bearer（`POST /auth/login` 获取）；错误返回 `{"detail": "..."}` + 标准 HTTP 状态码；时间统一 ISO 8601。

### 8.1 认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 登录，返回 access_token |
| GET | `/auth/me` | 当前用户信息 |

### 8.2 需求

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/requirements` | 列表，支持 `status`/`stage_type`/`pm_id`/`project_id`/`keyword` 筛选与分页 |
| POST | `/requirements` | 创建需求（自动生成 7 个环节），body 含各环节预估时间与负责人（可空） |
| GET | `/requirements/{id}` | 详情：基础信息 + 环节列表 + 变更历史 + 回退历史 |
| PATCH | `/requirements/{id}` | 编辑基础字段（标题/描述/优先级/关联项目/负责 PM/各环节负责人），负责人变更走此端点 |
| POST | `/requirements/{id}/pause` | 暂停需求（记录 paused_at，见 3.3 暂停时钟规则） |
| POST | `/requirements/{id}/resume` | 恢复需求（自动顺延未完成环节时间并重算状态） |
| POST | `/requirements/{id}/mark-delayed` | PM 人工标记延期，body：`{"reason": "..."}`（reason 必填） |
| POST | `/requirements/{id}/unmark-delayed` | PM 解除人工延期，body：`{"reason": "..."}`（reason 必填；若仍有系统逾期则状态保持 delayed） |

> 删除需求：第一版**不提供**删除端点（需求一旦创建全程留痕）；确需清理由 Admin 直接操作数据库。

### 8.3 环节

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/stages/{id}/start` | 环节开始（记录 actual_start；校验前置环节已完成，前端/API 开发除外可并行；测试 start 需平台/前端/API 三者均完成） |
| POST | `/stages/{id}/complete` | 环节完成（记录 actual_end；**校验环节处于进行中**，未 start 直接 complete 返回 409；上线完成则需求置为已完成——无论当前是进行中还是延期态） |
| POST | `/stages/{id}/revert` | 环节回退，body：`{"reason": "...", "target_stage_id": N}`（target ∈ 允许回退路径，见 3.1 回退规则；操作后同步重置下游环节并重算需求状态） |
| PATCH | `/stages/{id}/plan` | 修改预估时间，body：`{"planned_start": "...", "planned_end": "...", "reason": "..."}`，**reason 必填**，写变更历史；校验 3.2 时间约束（planned_end ≥ planned_start、下游顺序约束），成功后重置 `reminder_sent` 并同步重算需求状态 |
| PATCH | `/stages/{id}/assignee` | 指派/变更环节负责人，body：`{"assignee_id": N}`，仅负责 PM 与 Admin 可操作 |
| GET | `/stages/{id}/change-logs` | 该环节的预估时间变更历史 |

### 8.4 项目

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/projects` | 列表，支持 `status`/`owner_id` 筛选 |
| POST | `/projects` | 创建项目（含接口人列表），创建者默认为 owner |
| GET | `/projects/{id}` | 详情：项目信息 + 对接需求清单（含每条需求状态/当前环节/是否延期） + 自动完成率 |
| PATCH | `/projects/{id}` | 编辑项目（含进展、状态、接口人），仅 owner 或 Admin |
| DELETE | `/projects/{id}` | 删除项目（仅 owner 或 Admin；**不级联删除需求**——解除全部需求的 project_id 后删除项目本体，历史需求保留） |
| POST | `/projects/{id}/requirements` | 挂接需求，body：`{"requirement_id": N}`；**若需求已属于其他项目返回 409**；可挂接他人负责的需求（挂接不影响需求本身的编辑权限） |
| DELETE | `/projects/{id}/requirements/{rid}` | 解除挂接（置空 requirements.project_id） |

### 8.5 用户管理（仅 Admin）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/users` | 用户列表，支持 `role`/`is_active`/`keyword` 筛选 |
| POST | `/users` | 创建用户（用户名/初始密码/角色/显示名） |
| PATCH | `/users/{id}` | 编辑用户（显示名/角色/启用停用） |
| POST | `/users/{id}/reset-password` | 重置密码 |
| POST | `/users/{id}/transfer` | 转交该用户名下需求 PM 与环节负责人，body：`{"to_user_id": N}`，转交后方可停用 |

### 8.6 统计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/stats/overview` | 当前总览：按状态分布、按环节在途分布、当前延期清单 |
| GET | `/stats/requirements/weekly?date=YYYY-MM-DD` | 需求周报（date 所在自然周） |
| GET | `/stats/requirements/monthly?month=YYYY-MM` | 需求月报 |
| GET | `/stats/projects/weekly?date=YYYY-MM-DD` | 项目维度周报 |
| GET | `/stats/projects/monthly?month=YYYY-MM` | 项目维度月报 |

### 8.7 通知

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/notifications?unread_only=true` | 我的通知列表（分页） |
| GET | `/notifications/unread-count` | 未读数（前端轮询） |
| POST | `/notifications/{id}/read` | 单条已读（仅接收人本人可操作） |
| POST | `/notifications/read-all` | 全部已读 |

### 8.8 认证与通用约定补充

- **JWT 策略**：access_token 有效期 **12 小时**；第一版**不做 refresh token**，过期后重新登录。token 中含 `user_id` 与 `role`，权限校验在依赖项中统一完成。
- **时间格式**：ISO 8601 带时区偏移（如 `2026-08-14T10:00:00+08:00`），服务端统一转换 Asia/Shanghai 后存储（见 4.2）。
- **权限校验失败**统一返回 403；资源不存在返回 404；状态/流程校验失败（如未 start 就 complete、回退目标非法）返回 **409**，`detail` 中给出具体冲突原因。

---

## 9. 页面设计

### 9.1 页面清单

| 页面 | 路由 | 说明 |
|---|---|---|
| 登录 | `/login` | |
| 需求列表 | `/requirements` | 筛选：状态/当前环节/负责人/所属项目/关键词；表格列：标题、优先级、当前环节、状态（延期红标）、负责人、更新时间 |
| 新建/编辑需求 | `/requirements/new`、`/requirements/{id}/edit` | 表单含 7 个环节的预估时间与负责人 |
| 需求详情 | `/requirements/{id}` | 上半：基础信息；中部：环节时间线；下半：预估时间变更历史 |
| 项目列表 | `/projects` | 卡片或表格，显示状态、负责人、进度 |
| 项目详情 | `/projects/{id}` | 项目信息、接口人、进展编辑、对接需求清单 |
| 统计看板 | `/stats` | Tab 切换：需求（周/月）/ 项目（周/月） |
| 通知中心 | `/notifications` | 顶部铃铛显示未读数 |

### 9.2 需求详情页（关键环节时间线）

```
┌────────────────────────────────────────────────────────────┐
│ 需求：XXX系统改造          P1   状态：延期(红)   PM：李四      │
├────────────────────────────────────────────────────────────┤
│ 环节时间线                                                  │
│ ① 需求调研   ✔ 已完成   3/01→3/05 (实际 3/01→3/04)          │
│ ② 需求审评   ✔ 已完成   3/06→3/08 (实际 3/05→3/08)          │
│ ③ 平台开发   ● 进行中   3/09→3/20 ⚠已逾期3天 [改期][回退]     │
│ ④ 前端开发   ○ 未开始   3/21→3/28                            │
│ ⑤ API开发    ○ 未开始   3/21→3/28                            │
│ ⑥ 测试       ○ 未开始   3/29→4/03                            │
│ ⑦ 上线       ○ 未开始   4/04→4/04                            │
├────────────────────────────────────────────────────────────┤
│ 预估时间变更历史                                             │
│ 3/21 李四 平台开发预计结束 3/18→3/20 原因：依赖接口方联调延迟   │
└────────────────────────────────────────────────────────────┘
```

交互说明：

- 点击"改期"弹出表单：新预计开始/结束时间 + **延期原因（必填）**。
- 环节行内操作（开始/完成/回退）按当前用户权限与环节状态显示。
- 统计看板用图表库（如 ECharts）渲染柱状图（状态分布）、漏斗/条形（环节在途）、折线（周趋势）。

---

## 10. 非功能设计

### 10.1 技术栈与依赖

- 后端：Python 3.11+、FastAPI、SQLAlchemy 2.x + Alembic（迁移）、Pydantic v2、APScheduler 3.x、python-jose（JWT）、passlib[bcrypt]
- 数据库：SQLite（单文件，WAL 模式；小团队内部使用足够，后续可平滑迁 PostgreSQL）
- 前端：Vue 3 + Vite + Element Plus + ECharts（或 React + Ant Design，团队熟悉哪个用哪个）
- 部署：单机部署，`uvicorn` 运行后端，前端构建产物由 FastAPI StaticFiles 或 Nginx 托管；定时任务随后端进程运行，无需独立 worker。**必须单 worker 运行**（`--workers 1`），原因与多 worker 的替代方案见 4.2。

### 10.2 其他约定

- 数据量预估：千级需求、万级环节，实时计算统计无性能问题。
- 备份：每日定时复制 SQLite 文件即可。
- 审计：预估时间变更、状态变更均有日志，可追溯。

### 10.3 后续可扩展点（第一版不做，预留设计）

- **提醒渠道扩展**：通知生成抽象为 `NotificationSender` 接口，第一版仅 `InAppSender`，后续可加邮件、企业微信/钉钉机器人。
- **环节模板可配置**：7 个环节目前硬编码，后续可抽 `stage_templates` 表支持自定义流程。
- **需求多项目关联**：如出现一个需求属于多个项目的诉求，再加关联表改多对多。
- **WebSocket 实时推送**通知。
