#!/usr/bin/env bash
# 端到端冒烟测试：独立临时库 + 独立端口，不影响开发库 pm.db
set -euo pipefail

cd "$(dirname "$0")/.."
PORT=8123
DB=/tmp/pm_smoke.db
export PM_SECRET_KEY="smoke-test-secret-$(date +%s)"
export PM_DATABASE_URL="sqlite+aiosqlite:///${DB}"
BASE="http://127.0.0.1:${PORT}/api/v1"

rm -f "${DB}"
trap 'kill %1 2>/dev/null || true; rm -f "${DB}"' EXIT

echo "== 0. 迁移建表 + 建管理员（独立临时库）=="
.venv/bin/python -m alembic upgrade head >/dev/null
.venv/bin/python -m app.main create-admin smoke_admin 'smoke-pass-123' '冒烟管理员'

echo "== 启动服务（后台）=="
.venv/bin/python -m uvicorn app.main:app --port ${PORT} --workers 1 >/tmp/pm_smoke_server.log 2>&1 &
for i in $(seq 1 30); do
  curl -sf "${BASE}/health" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "== 1. 前端托管 =="
curl -sf "http://127.0.0.1:${PORT}/" | grep -q '<div id="app">' && echo "  / → index.html ✓"
curl -sf "http://127.0.0.1:${PORT}/requirements" | grep -q '<div id="app">' && echo "  /requirements SPA 回退 ✓"
ASSET=$(ls frontend/dist/assets/*.js | head -1 | xargs basename)
curl -sf "http://127.0.0.1:${PORT}/assets/${ASSET}" -o /dev/null && echo "  /assets/${ASSET} 静态资源 ✓"

echo "== 2. 健康检查 & 认证 =="
curl -sf "${BASE}/health" | grep -q '"ok"' && echo "  health ✓"
TOKEN=$(curl -sf -X POST "${BASE}/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"smoke_admin","password":"smoke-pass-123"}' | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "  login ✓"
curl -sf "${BASE}/auth/me" -H "Authorization: Bearer ${TOKEN}" | grep -q smoke_admin && echo "  me ✓"
# 错误密码必须 401
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "${BASE}/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"smoke_admin","password":"wrong"}')
[ "${code}" = "401" ] && echo "  错误密码 401 ✓"

echo "== 3. 需求闭环（创建 → 走完 7 环节 → done）=="
RID=$(curl -sf -X POST "${BASE}/requirements" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d '{"title":"冒烟需求","priority":"P1"}' | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "  创建需求 id=${RID} ✓"
# 无排期创建后首次排期（回归路径：old_value NULL 不得 500）
SID=$(curl -sf "${BASE}/requirements/${RID}" -H "Authorization: Bearer ${TOKEN}" \
  | .venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print(d['stages'][0]['id'])")
curl -sf -X PATCH "${BASE}/stages/${SID}/plan" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d '{"planned_start":"2030-01-01T09:00:00+08:00","planned_end":"2030-01-03T18:00:00+08:00","reason":"首次排期"}' >/dev/null
echo "  首次排期（old_value NULL 回归路径）✓"
# 依次走完 7 环节
for i in 0 1 2 3 4 5 6; do
  SID=$(curl -sf "${BASE}/requirements/${RID}" -H "Authorization: Bearer ${TOKEN}" \
    | .venv/bin/python -c "import sys,json;d=json.load(sys.stdin);print(d['stages'][${i}]['id'])")
  curl -sf -X POST "${BASE}/stages/${SID}/start" -H "Authorization: Bearer ${TOKEN}" >/dev/null
  curl -sf -X POST "${BASE}/stages/${SID}/complete" -H "Authorization: Bearer ${TOKEN}" >/dev/null
done
STATUS=$(curl -sf "${BASE}/requirements/${RID}" -H "Authorization: Bearer ${TOKEN}" \
  | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['status'])")
[ "${STATUS}" = "done" ] && echo "  7 环节走完，status=done ✓"

echo "== 4. 改期必填原因（缺原因必须 422）=="
code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH "${BASE}/stages/${SID}/plan" \
  -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d '{"planned_end":"2030-01-05T18:00:00+08:00"}')
[ "${code}" = "422" ] && echo "  缺 reason 422 ✓"

echo "== 5. 统计 & 通知 =="
curl -sf "${BASE}/stats/overview" -H "Authorization: Bearer ${TOKEN}" | grep -q status_distribution && echo "  stats/overview ✓"
curl -sf "${BASE}/stats/requirements/weekly" -H "Authorization: Bearer ${TOKEN}" | grep -q new_count && echo "  需求周报 ✓"
curl -sf "${BASE}/notifications/unread-count" -H "Authorization: Bearer ${TOKEN}" | grep -q unread && echo "  未读数 ✓"

echo "== 6. 项目模块 =="
PID=$(curl -sf -X POST "${BASE}/projects" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d '{"name":"冒烟项目","contacts":[{"name":"张三","phone":"138"}]}' | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -sf -X POST "${BASE}/projects/${PID}/requirements" -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' \
  -d "{\"requirement_id\":${RID}}" | grep -q '"total":1' && echo "  项目挂接需求 ✓"
curl -sf "${BASE}/stats/projects/weekly" -H "Authorization: Bearer ${TOKEN}" | grep -q projects && echo "  项目周报 ✓"

echo ""
echo "SMOKE TEST PASSED ✅"
