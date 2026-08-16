<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, getToken, getStoredUser, clearToken } from './api'

const router = useRouter()
const user = ref(getStoredUser())
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
  router.push('/login')
}

onMounted(() => {
  if (getToken()) {
    if (!user.value) {
      api
        .get('/auth/me')
        .then((me) => {
          user.value = me
          localStorage.setItem('pm_user', JSON.stringify(me))
        })
        .catch(() => {})
    }
    refreshUnread()
    setInterval(refreshUnread, 60_000) // 前端轮询（design.md 4.2）
  }
})
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
          <el-badge v-if="unread" :value="unread" :max="99" class="nav-badge" />
        </router-link>
      </nav>

      <div class="user-area" v-if="user">
        <div class="user-card">
          <div class="avatar">{{ (user.display_name || '?').slice(0, 1) }}</div>
          <span class="user-info user-name">{{ user.display_name }}<span class="user-role">· {{ roleLabel }}</span></span>
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
  width: 176px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #141c33 0%, #1b2440 60%, #1f2a4a 100%);
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
  gap: 8px;
  padding: 18px 14px 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
}

.brand-logo {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4c6fff, #7c9aff);
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
  font-size: 15px;
  font-weight: 600;
  color: #fff;
}

/* ---------- 导航 ---------- */
.nav {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 40px;
  padding: 0 12px;
  border-radius: 10px;
  font-size: 13.5px;
  color: #a8b3cf;
  overflow: hidden;
  transition: background 0.2s ease, color 0.2s ease;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #e6ebf7;
}

.nav-item.router-link-active {
  background: linear-gradient(90deg, rgba(76, 111, 255, 0.95), rgba(76, 111, 255, 0.6));
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
  position: absolute;
  left: 50%;
  top: 4px;
  transform: translateX(6px) scale(0.85);
  margin-left: 0;
}

/* ---------- 用户区：与导航区左右边距一致（8px），保证收起态圆心同一竖线 ---------- */
.user-area {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin: 12px 8px;
}

.user-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.07);
  transition: padding 0.28s ease;
}

.sidebar.collapsed .user-card {
  padding: 4px;
  gap: 0; /* 名字已零宽，gap 会把头像顶偏 */
  border-radius: 50%;
  /* 收起态去掉外层椭圆圈，仅保留头像本身 */
  background: transparent;
  border-color: transparent;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #5b7bff, #9a6cff);
  color: #fff;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  /* 展开态：不显示姓氏圆标，仅显示用户名；收起态才显示 */
  opacity: 0;
  max-width: 0;
  transition: opacity 0.18s ease, max-width 0.28s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.sidebar.collapsed .avatar {
  opacity: 1;
  max-width: 32px;
}

.user-info {
  min-width: 0;
}

.user-name {
  font-size: 13px;
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
  font-size: 11px;
  color: #66739a;
}

/* 退出：胶囊按钮，文字居中，悬停显红 */
.logout-btn {
  position: relative;
  flex-shrink: 0;
  height: 34px;
  min-width: 34px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
  color: #a8b3cf;
  font-size: 13px;
  letter-spacing: 1px;
  text-align: center;
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
  width: 34px;
  border-radius: 50%;
}

.sidebar.collapsed .logout-char {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
}

/* ---------- 收起/展开按钮 ---------- */
.collapse-btn {
  margin: 0 8px 14px;
  padding: 7px 0;
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
  padding: 24px 28px 40px;
}
</style>
