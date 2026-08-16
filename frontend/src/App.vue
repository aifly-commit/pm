<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, getToken, getStoredUser, clearToken } from './api'

const router = useRouter()
const user = ref(getStoredUser())
const unread = ref(0)

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
  <el-container v-if="$route.path !== '/login'" class="layout">
    <el-header class="header">
      <div class="brand">需求管理平台</div>
      <nav class="nav">
        <router-link to="/requirements">需求</router-link>
        <router-link to="/projects">项目</router-link>
        <router-link to="/stats">统计</router-link>
        <router-link to="/notifications" class="bell">
          通知
          <el-badge v-if="unread" :value="unread" :max="99" class="badge" />
        </router-link>
      </nav>
      <div class="user" v-if="user">
        <span>{{ user.display_name }}（{{ roleLabel }}）</span>
        <el-button link type="danger" @click="logout">退出</el-button>
      </div>
    </el-header>
    <el-main class="main">
      <router-view @notification-may-change="refreshUnread" />
    </el-main>
  </el-container>
  <router-view v-else />
</template>

<style>
body {
  margin: 0;
  background: #f5f7fa;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}
.layout {
  min-height: 100vh;
}
.header {
  display: flex;
  align-items: center;
  gap: 32px;
  background: #1f2d3d;
  color: #fff;
}
.brand {
  font-weight: 600;
  font-size: 17px;
}
.nav {
  display: flex;
  gap: 24px;
  flex: 1;
}
.nav a {
  color: #c0c4cc;
  text-decoration: none;
  padding: 4px 2px;
}
.nav a.router-link-active {
  color: #fff;
  border-bottom: 2px solid #409eff;
}
.bell {
  position: relative;
}
.badge {
  margin-left: 4px;
  transform: translateY(-6px);
}
.user {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 14px;
}
.main {
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
}
</style>
