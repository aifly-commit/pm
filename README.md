# pm — 需求管理与项目管理平台

内部平台：需求全生命周期管理（7 环节流转、到期提醒、延期留痕）+ 项目维度管理（接口人、对接需求清单、周/月复盘）。

- 设计文档：[design.md](./design.md)（v1.1，实现的唯一依据）
- 技术栈：Python 3.11+ / FastAPI / SQLAlchemy 2.x (async) + aiosqlite / SQLite / APScheduler / Alembic
- 前端：Vue 3 + Element Plus（M4 阶段）

## 开发

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple

# 数据库迁移
alembic upgrade head

# 启动（必须单 worker，见 design.md 4.2）
uvicorn app.main:app --reload --workers 1

# 测试（覆盖率硬性要求 ≥95%，见 pyproject.toml）
pytest
```

## 开发纪律

- 每次迭代测试闭环：写码 → `pytest` 全绿 → 提交
- 覆盖率 <95% 视为失败（`--cov-fail-under=95`）
- 测试不通过的项必须修复，不允许跳过
- 状态机等核心逻辑在 `app/services/`，API 路由只做参数校验与调用

## 目录结构

```
app/
├── core/          # 配置、安全（JWT/bcrypt）
├── services/      # 状态机、时间校验（核心业务规则）
├── models.py      # ORM 模型（design.md 7.2）
├── enums.py       # 枚举与环节流程定义
└── db.py          # 异步引擎与会话
alembic/           # 数据库迁移
tests/             # pytest（内存 SQLite，每用例独立建库）
```
