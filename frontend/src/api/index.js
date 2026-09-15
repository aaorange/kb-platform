import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    } else if (err.response?.data?.detail) {
      ElMessage.error(err.response.data.detail)
    }
    return Promise.reject(err)
  }
)

export default {
  // Auth
  login: (data) => api.post('/auth/login', data),
  getMe: () => api.get('/auth/me'),

  // Org
  getDepartments: () => api.get('/org/departments'),
  createDepartment: (data) => api.post('/org/departments', data),
  getRoles: () => api.get('/org/roles'),
  createRole: (data) => api.post('/org/roles', data),
  updateRole: (roleId, data) => api.patch(`/org/roles/${roleId}`, data),
  deleteRole: (roleId) => api.delete(`/org/roles/${roleId}`),
  getUsers: () => api.get('/org/users'),
  createUser: (data) => api.post('/org/users', data),
  updateUser: (userId, data) => api.patch(`/org/users/${userId}`, data),
  resetPassword: (userId, data) => api.post(`/org/users/${userId}/reset-password`, data),

  // Knowledge
  getUnits: () => api.get('/knowledge/units'),
  uploadDocument: (formData) =>
    api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000, // 仅等待文件传输（解析/向量化已转后台任务）
    }),
  getTaskStatus: (taskId) => api.get(`/knowledge/tasks/${taskId}`),
  toggleUnit: (unitId) => api.patch(`/knowledge/units/${unitId}/toggle`),
  deleteUnit: (unitId) => api.delete(`/knowledge/units/${unitId}`),
  updatePermissions: (unitId, data) => api.put(`/knowledge/units/${unitId}/permissions`, data),
  previewUnit: (unitId) => api.get(`/knowledge/units/${unitId}/preview`),

  // Chat sessions
  getSessions: () => api.get('/chat/sessions'),
  getSessionMessages: (sessionId) => api.get(`/chat/sessions/${sessionId}/messages`),
  deleteSession: (sessionId) => api.delete(`/chat/sessions/${sessionId}`),
  sendFeedback: (logId, value) => api.post(`/chat/logs/${logId}/feedback`, { value }),

  // Ops
  getDashboard: () => api.get('/ops/dashboard'),
  getDashboardFull: () => api.get('/ops/dashboard/full'),
  getFAQs: () => api.get('/ops/faqs'),
  createFAQ: (data) => api.post('/ops/faqs', data),
  publishFAQCache: (faqId) => api.post(`/ops/faqs/${faqId}/cache`),
  autoGenFaqs: (count) => api.post('/ops/faqs/auto-generate', { count }, { timeout: 300000 }),
  getFaqCandidates: () => api.get('/ops/faq-candidates'),
  generateFaqAnswer: (question) => api.post('/ops/faqs/generate-answer', { question }, { timeout: 300000 }),
  getGaps: () => api.get('/ops/gaps'),

  // Chat (SSE — 不走 axios)
  chatStream: (question, sessionId, onEvent) => {
    const token = localStorage.getItem('token')
    return fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ question, session_id: sessionId }),
    }).then(async (res) => {
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              onEvent(JSON.parse(line.slice(6)))
            } catch { /* skip */ }
          }
        }
      }
    })
  },
}
