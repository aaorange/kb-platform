<template>
  <div class="login-page">
    <!-- 品牌区 -->
    <div class="brand-panel">
      <div class="brand-content">
        <div class="brand-logo">
          <el-icon :size="26"><Reading /></el-icon>
        </div>
        <h1 class="brand-title">企业知识库管理平台</h1>
        <p class="brand-sub">AI 鉴权检索 · 四维权限管控</p>
        <div class="brand-points">
          <div class="point" v-for="p in points" :key="p.t">
            <el-icon class="point-icon"><CircleCheckFilled /></el-icon>
            <div>
              <div class="point-title">{{ p.t }}</div>
              <div class="point-desc">{{ p.d }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 表单区 -->
    <div class="form-panel">
      <el-card class="login-card" shadow="never">
        <h2 class="login-title">欢迎回来</h2>
        <p class="login-desc">请使用企业账号登录</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-width="0" @submit.prevent="handleLogin">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" size="large" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" size="large" show-password @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="handleLogin">登 录</el-button>
          </el-form-item>
        </el-form>

        <el-collapse class="account-collapse">
          <el-collapse-item title="测试账号（点击直接填充）">
            <div v-for="a in accounts" :key="a.u" class="account-item" @click="fillAccount(a)">
              <span class="account-name">{{ a.name }}</span>
              <span class="account-info">{{ a.u }} / {{ a.p }} · {{ a.dept }}</span>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const formRef = ref()
const loading = ref(false)

const points = [
  { t: '权限受控的 AI 问答', d: '回答只基于您有权限的知识生成，引用可溯源' },
  { t: '四维细粒度权限', d: '全局 / 部门 / 角色 / 个人，敏感知识精准隔离' },
  { t: '知识自动沉淀', d: '高频问题转 FAQ，缺口自动识别，运营有数据' },
]

const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const accounts = [
  { u: 'admin', p: 'admin123', name: '管理员', dept: '总经理办公室' },
  { u: 'zhangwei', p: 'user123', name: '张伟', dept: '研发部' },
  { u: 'lina', p: 'user123', name: '李娜', dept: '人力资源部' },
  { u: 'wangqiang', p: 'user123', name: '王强', dept: '财务部' },
]

function fillAccount(a) {
  form.username = a.u
  form.password = a.p
}

async function handleLogin() {
  await formRef.value.validate()
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    router.push('/chat')
  } catch (e) {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  background: #fff;
}

.brand-panel {
  flex: 1;
  background: linear-gradient(160deg, #064e3b 0%, #059669 55%, #10b981 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
}
.brand-panel::before {
  content: '';
  position: absolute;
  width: 560px;
  height: 560px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 255, 255, 0.08) 0%, transparent 65%);
  top: -160px;
  right: -160px;
}
.brand-content {
  width: 400px;
  color: #fff;
  padding: 0 24px;
  position: relative;
}
.brand-logo {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.16);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 24px;
}
.brand-title {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: 1px;
}
.brand-sub {
  margin-top: 10px;
  font-size: 15px;
  opacity: 0.85;
  margin-bottom: 48px;
}
.brand-points {
  display: flex;
  flex-direction: column;
  gap: 26px;
}
.point {
  display: flex;
  gap: 14px;
}
.point-icon {
  color: #6ee7b7;
  font-size: 22px;
  margin-top: 2px;
  flex-shrink: 0;
}
.point-title {
  font-size: 15px;
  font-weight: 600;
}
.point-desc {
  font-size: 13px;
  opacity: 0.75;
  margin-top: 4px;
  line-height: 1.6;
}

.form-panel {
  width: 460px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fbfcfb;
  border-left: 1px solid #e5e9e6;
}
.login-card {
  width: 360px;
  border: 1px solid #e5e9e6;
  border-radius: 16px;
}
.login-title {
  font-size: 22px;
  color: var(--kb-text);
  margin-bottom: 6px;
}
.login-desc {
  font-size: 13px;
  color: var(--kb-text-secondary);
  margin-bottom: 28px;
}

.account-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
}
.account-item:hover {
  background: var(--el-color-primary-light-9);
}
.account-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text);
}
.account-info {
  font-size: 12px;
  color: var(--kb-text-secondary);
}

@media (max-width: 900px) {
  .brand-panel { display: none; }
  .form-panel { width: 100%; }
}
</style>
