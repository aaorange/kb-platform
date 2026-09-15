import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/chat',
    children: [
      { path: 'chat', name: 'Chat', component: () => import('../views/Chat.vue'), meta: { title: 'AI 智能问答', icon: 'ChatDotRound' } },
      { path: 'knowledge', name: 'Knowledge', component: () => import('../views/Knowledge.vue'), meta: { title: '知识维护', icon: 'Document', admin: true } },
      { path: 'dashboard', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { title: '运营看板', icon: 'DataAnalysis' } },
      { path: 'operations', name: 'Operations', component: () => import('../views/Operations.vue'), meta: { title: '知识沉淀', icon: 'Setting', admin: true } },
      { path: 'organization', name: 'Organization', component: () => import('../views/Organization.vue'), meta: { title: '组织架构', icon: 'UserFilled', admin: true } },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    next()
  } else if (!auth.isLoggedIn) {
    next('/login')
  } else if (to.meta.admin && !auth.isAdmin) {
    next('/chat')
  } else {
    next()
  }
})

export default router
