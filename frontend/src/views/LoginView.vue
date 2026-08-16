<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api, setToken } from '../api'

const router = useRouter()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await api.post('/auth/login', form)
    setToken(data.access_token)
    const me = await api.get('/auth/me')
    localStorage.setItem('pm_user', JSON.stringify(me))
    ElMessage.success(`欢迎，${me.display_name}`)
    router.push('/requirements')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="blob blob-1" />
    <div class="blob blob-2" />
    <div class="login-card">
      <div class="logo">PM</div>
      <h2 class="title">需求管理与项目管理平台</h2>
      <p class="subtitle">需求全生命周期 · 项目维度复盘 · 到期自动提醒</p>
      <el-form @keyup.enter="submit">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            size="large"
            show-password
          />
        </el-form-item>
        <el-button type="primary" size="large" class="submit" :loading="loading" @click="submit">
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(135deg, #131b31 0%, #1d2a4d 55%, #2a3a6b 100%);
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.45;
}

.blob-1 {
  width: 420px;
  height: 420px;
  background: #4c6fff;
  top: -120px;
  right: -80px;
}

.blob-2 {
  width: 360px;
  height: 360px;
  background: #7a4cff;
  bottom: -140px;
  left: -100px;
}

.login-card {
  position: relative;
  z-index: 1;
  width: 400px;
  padding: 40px 36px 32px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 24px 64px rgba(8, 14, 34, 0.45);
  text-align: center;
}

.logo {
  width: 52px;
  height: 52px;
  margin: 0 auto 14px;
  border-radius: 13px;
  background: linear-gradient(135deg, #4c6fff, #7c9aff);
  color: #fff;
  font-weight: 700;
  font-size: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.title {
  margin: 0;
  font-size: 19px;
  color: #1f2733;
}

.subtitle {
  margin: 8px 0 26px;
  font-size: 13px;
  color: #7a8699;
}

.submit {
  width: 100%;
  margin-top: 4px;
  letter-spacing: 6px;
  background: linear-gradient(90deg, #4c6fff, #6a8bff);
  border: none;
}

.submit:hover {
  background: linear-gradient(90deg, #3b57d9, #5577f0);
}
</style>
