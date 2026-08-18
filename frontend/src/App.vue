<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, getToken, getStoredUser, clearToken } from './api'

const router = useRouter()
const route = useRoute()
const user = ref(getStoredUser())
const authenticated = ref(Boolean(getToken()))
const profileLoading = ref(false)
const unread = ref(0)
const collapsed = ref(localStorage.getItem('pm_sidebar_collapsed') === '1')

function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem('pm_sidebar_collapsed', collapsed.value ? '1' : '0')
}

const roleLabel = computed(() => {
  const map = { pm: '产品经理', developer: '研发', tester: '测试', admin: '管理员' }
  return map[user.value?.role] || user.value?.role || ''
})

const todayLabel = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short',
}).format(new Date())

async function refreshUnread() {
  if (!getToken()) return
  try {
    const data = await api.get('/notifications/unread-count')
    unread.value = data.unread
  } catch {
    /* 静默：顶栏未读数失败不打扰 */
  }
}

function logout() {
  clearToken()
  user.value = null
  authenticated.value = false
  router.push('/login')
}

async function ensureSession() {
  if (route.path === '/login' || !getToken()) {
    authenticated.value = false
    return
  }
  authenticated.value = true
  if (!user.value) {
    profileLoading.value = true
    try {
      const me = await api.get('/auth/me')
      user.value = me
      localStorage.setItem('pm_user', JSON.stringify(me))
    } catch {
      // api 客户端会在 401 时清理会话并跳转；这里保留占位避免侧栏闪烁。
    } finally {
      profileLoading.value = false
    }
  }
  refreshUnread()
}

// App 在登录页和业务页之间不会重新挂载；监听路由确保刚登录后立即同步资料。
watch(() => route.path, ensureSession, { immediate: true })
setInterval(refreshUnread, 60_000) // 前端轮询（design.md 4.2）
</script>

<template>
  <div v-if="$route.path !== '/login'" class="layout">
    <aside class="sidebar" :class="{ collapsed }">
      <div class="brand">
        <div class="brand-logo">PM</div>
        <div class="brand-text">
          <div class="brand-name">产品平台</div>
        </div>
      </div>

      <nav class="nav">
        <div class="nav-section">工作导航</div>
        <router-link to="/requirements" class="nav-item" title="需求管理">
          <span class="nav-char">需</span>
          <span class="nav-dot" /><span class="nav-text">需求管理</span>
        </router-link>
        <router-link to="/projects" class="nav-item" title="项目管理">
          <span class="nav-char">项</span>
          <span class="nav-dot" /><span class="nav-text">项目管理</span>
        </router-link>
        <router-link to="/stats" class="nav-item" title="统计分析">
          <span class="nav-char">统</span>
          <span class="nav-dot" /><span class="nav-text">统计分析</span>
        </router-link>
        <router-link to="/notifications" class="nav-item" title="通知中心">
          <span class="nav-char">通</span>
          <span class="nav-dot" /><span class="nav-text">通知中心</span>
          <el-badge v-if="unread && !collapsed" :value="unread" :max="99" class="nav-badge" />
        </router-link>
      </nav>

      <div class="user-area" v-if="authenticated">
        <div class="user-card" :class="{ 'is-loading': profileLoading }">
          <div class="avatar">{{ (user?.display_name || '…').slice(0, 1) }}</div>
          <span class="user-info user-name">
            {{ user?.display_name || '正在加载账户信息' }}
            <span v-if="roleLabel" class="user-role">· {{ roleLabel }}</span>
          </span>
        </div>
        <button class="logout-btn" title="退出登录" @click="logout">
          <span class="logout-text">退出登录</span>
          <span class="logout-char">退</span>
        </button>
      </div>

      <button class="collapse-btn" @click="toggleSidebar" :title="collapsed ? '展开侧边栏' : '收起侧边栏'">
        {{ collapsed ? '»' : '«' }}
      </button>
    </aside>

    <main class="main">
      <div class="workspace-date"><span class="live-dot" />{{ todayLabel }}</div>
      <router-view @notification-may-change="refreshUnread" />
    </main>
  </div>
  <router-view v-else />
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}

/* ---------- 侧边栏骨架：宽度过渡 + 内部元素只做透明度/位移，避免 layout 抖动 ---------- */
.sidebar {
  width: 192px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: radial-gradient(circle at 18% 0%, rgba(93, 122, 255, 0.27), transparent 31%),
    linear-gradient(180deg, #111a31 0%, #182542 58%, #1a2643 100%);
  color: #cdd5e6;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow: hidden;
  transition: width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar.collapsed {
  width: 68px;
}

/* 文字类元素：不换行 + 透明度与最大宽度联动收起，避免占位移位 */
.brand-text,
.nav-text,
.user-info,
.logout-text {
  white-space: nowrap;
  overflow: hidden;
  transition: opacity 0.18s ease, max-width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}

.brand-text {
  max-width: 120px;
}

.nav-text {
  max-width: 120px;
}

.user-info {
  max-width: 110px;
}

.logout-text {
  max-width: 80px;
  display: inline-block;
  vertical-align: middle;
}

.sidebar.collapsed .brand-text,
.sidebar.collapsed .nav-text,
.sidebar.collapsed .user-info,
.sidebar.collapsed .logout-text {
  opacity: 0;
  max-width: 0;
}

/* ---------- 品牌区 ---------- */
.brand {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 19px 14px 15px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

.brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6a83ff, #8f6cff);
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.5px;
  flex-shrink: 0;
  margin: 0 2px;
}

.brand-name {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.2px;
  color: #fff;
}

/* ---------- 导航 ---------- */
.nav {
  flex: 0 0 auto;
  padding: 15px 10px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-section {
  padding: 0 12px 7px;
  color: #7180a6;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  white-space: nowrap;
  transition: opacity 0.18s ease;
}

.sidebar.collapsed .nav-section { opacity: 0; }

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 42px;
  padding: 0 13px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  color: #a8b3cf;
  overflow: hidden;
  transition: background 0.2s ease, color 0.2s ease;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #e6ebf7;
}

.nav-item.router-link-active {
  background: linear-gradient(100deg, rgba(90, 117, 255, 0.98), rgba(90, 117, 255, 0.58));
  color: #fff;
  box-shadow: 0 4px 12px rgba(76, 111, 255, 0.35);
}

.nav-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.55;
  flex-shrink: 0;
  transition: opacity 0.18s ease;
}

.sidebar.collapsed .nav-dot {
  opacity: 0;
}

/* 收起态：单字圆形（绝对定位居中，不参与展开态布局，动画无抖动） */
.nav-char {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%) scale(0.6);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  color: #cdd5e6;
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.22s ease 0.06s, transform 0.22s ease 0.06s,
    background 0.2s ease, color 0.2s ease;
}

.sidebar.collapsed .nav-char {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
  pointer-events: auto;
}

.nav-item:hover .nav-char {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
}

.nav-item.router-link-active .nav-char {
  background: rgba(255, 255, 255, 0.22);
  color: #fff;
}

.nav-badge {
  margin-left: auto;
  transition: transform 0.22s ease, opacity 0.2s ease;
}

.sidebar.collapsed .nav-badge {
  display: none;
}

/* ---------- 用户区：与导航区左右边距一致（8px），保证收起态圆心同一竖线 ---------- */
.user-area {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 7px;
  margin: auto 10px 12px;
}

.user-card {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0;
  height: 36px;
  box-sizing: border-box;
  padding: 0 12px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.055);
  border: 1px solid rgba(255, 255, 255, 0.07);
  transition: padding 0.28s ease;
}

.user-card.is-loading { opacity: 0.76; }

.sidebar.collapsed .user-card {
  width: 36px;
  height: 36px;
  padding: 0;
  justify-content: center;
  gap: 0; /* 名字已零宽，gap 会把头像顶偏 */
  border-radius: 50%;
  /* 与退出按钮使用同一套外框；头像仅作为内部识别内容。 */
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.1);
}

.sidebar.collapsed .user-card,
.sidebar.collapsed .logout-btn {
  box-sizing: border-box;
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.1);
  color: #a8b3cf;
}

.sidebar.collapsed .avatar {
  background: transparent;
  color: inherit;
  font-size: 14px;
  font-weight: 600;
}

.avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  /* 收起/展开均不切换底色，避免透明度动画期间闪现旧的蓝色头像。 */
  background: transparent;
  color: #a8b3cf;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  /* 展开态使用完整姓名，不再重复显示姓名首字；收起态才展示头像。 */
  opacity: 0;
  max-width: 0;
  transition: opacity 0.18s ease, max-width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.sidebar.collapsed .avatar {
  opacity: 1;
  max-width: 28px;
}

.user-info {
  min-width: 0;
}

.user-name {
  font-size: 12px;
  font-weight: 600;
  color: #eef1fa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
}

.user-role {
  font-size: 10px;
  color: #7f8daf;
}

/* 退出：胶囊按钮，文字居中，悬停显红 */
.logout-btn {
  position: relative;
  flex-shrink: 0;
  height: 36px;
  min-width: 34px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.04);
  color: #a8b3cf;
  font-size: 12px;
  letter-spacing: 0;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease,
    padding 0.28s ease;
}

.logout-btn:hover {
  background: rgba(245, 108, 108, 0.14);
  border-color: rgba(245, 108, 108, 0.4);
  color: #ffb3b5;
}

.logout-char {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%) scale(0.6);
  font-size: 14px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.22s ease 0.06s, transform 0.22s ease 0.06s;
}

.sidebar.collapsed .user-area {
  align-items: center;
}

.sidebar.collapsed .logout-btn {
  padding: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
}

.sidebar.collapsed .logout-char {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
}

/* ---------- 收起/展开按钮 ---------- */
.collapse-btn {
  margin: 0 10px 14px;
  padding: 6px 0;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  color: #a8b3cf;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease;
}

.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.main {
  flex: 1;
  min-width: 0;
  padding: 22px 32px 44px;
  background: radial-gradient(circle at 90% 0%, rgba(111, 135, 255, 0.11), transparent 25%), var(--pm-bg);
}

.workspace-date {
  position: fixed;
  right: 24px;
  bottom: 18px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 7px 10px;
  border: 1px solid rgba(91, 112, 177, 0.15);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 5px 18px rgba(52, 67, 116, 0.08);
  color: #64718f;
  font-size: 12px;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #48c78e;
  box-shadow: 0 0 0 3px rgba(72, 199, 142, 0.14);
}

@media (max-width: 760px) {
  .sidebar { width: 68px; }
  .sidebar .brand-text, .sidebar .nav-text, .sidebar .user-info, .sidebar .logout-text {
    opacity: 0;
    max-width: 0;
  }
  .sidebar .nav-dot { opacity: 0; }
  .sidebar .nav-char { opacity: 1; transform: translate(-50%, -50%) scale(1); pointer-events: auto; }
  .sidebar .avatar { opacity: 1; max-width: 32px; }
  .sidebar .user-card { padding: 4px; gap: 0; border-radius: 50%; background: transparent; border-color: transparent; }
  .sidebar .logout-btn { padding: 0; width: 34px; border-radius: 50%; }
  .sidebar .logout-char { opacity: 1; transform: translate(-50%, -50%) scale(1); }
  .main { padding: 16px 16px 32px; }
  .workspace-date { right: 14px; bottom: 14px; }
}
</style>
