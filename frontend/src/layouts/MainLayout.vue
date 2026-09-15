<template>
  <el-container style="height: 100vh">
    <el-aside :width="isCollapse ? '64px' : '220px'" class="kb-aside">
      <div class="kb-logo" @click="router.push('/chat')">
        <div class="kb-logo-icon"><el-icon :size="20"><Reading /></el-icon></div>
        <transition name="fade">
          <span v-if="!isCollapse" class="kb-logo-text">知识库平台</span>
        </transition>
      </div>
      <el-menu
        :default-active="$route.path" router
        :collapse="isCollapse" :collapse-transition="false"
        background-color="transparent" text-color="rgba(255,255,255,.62)" active-text-color="#6ee7b7"
      >
        <template v-for="item in menuItems" :key="item.path">
          <el-menu-item v-if="!item.admin || auth.isAdmin" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <template #title>{{ item.title }}</template>
          </el-menu-item>
        </template>
      </el-menu>
      <div v-if="!isCollapse" class="kb-aside-footer">AI 鉴权检索 v1.0</div>
    </el-aside>

    <el-container>
      <el-header class="kb-header">
        <div class="kb-header-left">
          <el-icon class="collapse-btn" :size="18" @click="isCollapse = !isCollapse">
            <Fold v-if="!isCollapse" />
            <Expand v-else />
          </el-icon>
          <span class="page-title">{{ $route.meta.title || '首页' }}</span>
        </div>
        <el-dropdown @command="handleCommand">
          <div class="user-chip">
            <el-avatar :size="30" style="background: var(--kb-primary)">{{ auth.user?.display_name?.charAt(0) }}</el-avatar>
            <div class="user-meta" v-if="auth.user">
              <span class="user-name">{{ auth.user.display_name }}</span>
              <span class="user-dept">{{ auth.user.dept_name || '无部门' }}<template v-if="auth.isAdmin"> · 管理员</template></span>
            </div>
            <el-icon style="color: #909399"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main style="padding: 20px; overflow-y: auto; background: var(--kb-bg)">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()
const isCollapse = ref(false)

const menuItems = [
  { path: '/chat', title: 'AI 智能问答', icon: 'ChatDotRound' },
  { path: '/knowledge', title: '知识维护', icon: 'Document', admin: true },
  { path: '/dashboard', title: '运营看板', icon: 'DataAnalysis' },
  { path: '/operations', title: '知识沉淀', icon: 'Setting', admin: true },
  { path: '/organization', title: '组织架构', icon: 'UserFilled', admin: true },
]

function handleCommand(cmd) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.kb-aside {
  background: linear-gradient(180deg, #0b3527 0%, #062a1e 100%);
  transition: width .2s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.kb-logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  flex-shrink: 0;
  border-bottom: 1px solid rgba(255, 255, 255, .07);
}
.kb-logo-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.kb-logo-text {
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
  white-space: nowrap;
}
.kb-aside :deep(.el-menu) {
  border-right: none;
  padding: 8px;
}
.kb-aside :deep(.el-menu-item) {
  border-radius: 8px;
  margin-bottom: 4px;
  height: 46px;
}
.kb-aside :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, .06);
}
.kb-aside :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(16, 185, 129, .28), rgba(16, 185, 129, .08));
  color: #6ee7b7;
}
.kb-aside-footer {
  margin-top: auto;
  padding: 14px;
  color: rgba(255, 255, 255, .28);
  font-size: 11px;
  text-align: center;
  white-space: nowrap;
}
.fade-enter-active, .fade-leave-active { transition: opacity .15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.kb-header {
  background: #fff;
  border-bottom: 1px solid var(--kb-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 60px;
}
.kb-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.collapse-btn {
  cursor: pointer;
  color: var(--kb-text-secondary);
}
.collapse-btn:hover {
  color: var(--kb-primary);
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--kb-text);
}
.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 5px 10px;
  border-radius: 10px;
}
.user-chip:hover {
  background: var(--el-color-primary-light-9);
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--kb-text);
}
.user-dept {
  font-size: 11px;
  color: var(--kb-text-secondary);
}
</style>
