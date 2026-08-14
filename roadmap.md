# 开发路线图（用户决策，按此执行，勿自行改动范围）

## M1：工程脚手架 + 走通最小闭环（约 1 周）

目录结构：

```
pm/
├── app/
│   ├── main.py            # FastAPI 入口
│   ├── models/            # SQLAlchemy 模型（design.md 7.2 的 6 张表）
│   ├── api/               # 路由（按 8.x 分文件）
│   ├── services/          # 状态机、逾期判定（核心逻辑放这里，不放路由）
│   ├── scheduler/         # APScheduler 扫描任务
│   └── core/              # 配置、认证依赖、权限校验
├── alembic/               # 迁移
├── tests/
└── pyproject.toml
```

任务：
- 建表 + Alembic 迁移、`/auth/login` + JWT、用户管理 CRUD
- 状态机服务 + 完整单元测试：13 条转换、人工/系统延期双源、暂停顺延、回退重置——**测试先行**，写透了后面全是调用它
- 验收（已确认调整，2026-08-14）：M1 以"状态机单测 + 用户/认证 API"为准，**完整 HTTP 走流验收（创建需求 → start → complete → 走完 7 环节 → 状态正确流转）挪到 M2 末尾执行**
- M1 已完成并通过检查：106 用例全过、覆盖率 100%；已修复回退"当前环节"校验缺口与 JWT 默认密钥启动校验

## M2：需求 + 环节全量 API（约 1 周）

- 需求 CRUD / 暂停 / 恢复 / mark-delayed，环节 start / complete / revert / plan / assignee
- 时间校验（design.md 3.2 顺序约束）、变更历史、回退留痕
- 验收：用 httpyac/postman 集合覆盖全部端点的正常 + 异常路径（403/409）

## M3：提醒 + 定时任务（约 3 天）

- APScheduler 扫描、去重键、改期重置 `reminder_sent`、通知中心 API
- 验收：改系统时间/注入时钟的集成测试，验证逾期判定与通知不重、不发漏

## M4：项目模块 + 统计 + 前端（1~1.5 周，可与 M3 并行）

- 项目 CRUD / 挂接、统计 5 个端点（口径按 design.md 6.3 实现）
- Vue 3 + Element Plus：按 9.1 页面清单，优先做需求列表 + 需求详情时间线（用户 80% 时间在这两页）
