<template>
  <div class="chat-page">
    <!-- 会话侧边栏 -->
    <div class="session-panel">
      <div style="padding: 12px 12px 8px">
        <el-button type="primary" :icon="Plus" style="width: 100%" round @click="newChat">新建对话</el-button>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions" :key="s.id" class="session-item"
          :class="{ active: currentSessionId === s.id }"
          @click="selectSession(s.id)"
        >
          <el-icon :size="14" style="flex-shrink: 0; opacity: .7"><ChatLineRound /></el-icon>
          <span class="session-title">{{ s.title }}</span>
          <el-icon class="session-del" @click.stop="confirmDeleteSession(s)" :size="14">
            <Delete />
          </el-icon>
        </div>
        <div v-if="sessions.length === 0" class="session-empty">暂无对话记录</div>
      </div>
    </div>

    <!-- 对话区域 -->
    <div class="chat-main">
      <div ref="msgArea" class="msg-area" @click="handleClickMessages">
        <!-- 空状态 + 推荐问题 -->
        <div v-if="messages.length === 0" class="chat-empty">
          <div class="empty-icon"><el-icon :size="30"><ChatDotRound /></el-icon></div>
          <h3>有什么可以帮您？</h3>
          <p class="empty-desc">基于您有权限的文档生成回答，引用可溯源</p>
          <div class="suggest-list">
            <button v-for="s in suggestions" :key="s" class="suggest-item" @click="sendSuggestion(s)">
              {{ s }}
            </button>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-for="(msg, i) in messages" :key="i" class="msg-enter" style="margin-bottom: 22px">
          <!-- 用户提问 -->
          <div v-if="msg.role === 'user'" style="display: flex; justify-content: flex-end">
            <div class="bubble-user">{{ msg.content }}</div>
          </div>
          <!-- AI 回答 -->
          <div v-else style="display: flex; gap: 10px">
            <div class="ai-avatar">AI</div>
            <div style="flex: 1; min-width: 0">
              <div v-if="msg.thinking" class="bubble-ai">
                <div class="typing-dots"><span></span><span></span><span></span></div>
              </div>
              <div v-else class="bubble-ai chat-stream" :class="{ streaming: msg.streaming }" v-html="msg.content"></div>
              <!-- 引用溯源 -->
              <div v-if="msg.cited && msg.cited.length && !msg.thinking" class="cite-list">
                <span v-for="(c, j) in msg.cited" :key="j" class="cite-tag">
                  [{{ j + 1 }}] {{ c.doc_id }}<template v-if="c.heading"> · {{ c.heading?.substring(0, 18) }}</template>
                </span>
              </div>
              <!-- 权限提示 -->
              <el-alert v-if="msg.blocked > 0 && !msg.thinking" type="warning" :closable="false" style="margin-top: 8px; border-radius: 8px">
                {{ msg.blocked }} 篇相关文档因权限受限无法展示
              </el-alert>
              <!-- 反馈 -->
              <div v-if="msg.logId && !msg.streaming" class="feedback-bar">
                <button class="fb-btn" :class="{ liked: msg.feedback === 1 }" @click="sendFeedback(msg, 1)">👍 有帮助</button>
                <button class="fb-btn" :class="{ disliked: msg.feedback === -1 }" @click="sendFeedback(msg, -1)">👎 没帮助</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入框 -->
      <div class="input-bar">
        <el-input
          v-model="question" placeholder="输入您的问题，Enter 发送..."
          size="large" @keyup.enter="handleSend" :disabled="loading"
        />
        <el-button type="primary" size="large" :loading="loading" round @click="handleSend" style="width: 96px">发送</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, onMounted } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import 'highlight.js/styles/github.css'
import api from '../api'

// Markdown 渲染器：代码块带语言标签 + 复制按钮
marked.use({
  renderer: {
    code(code, lang) {
      const language = lang && hljs.getLanguage(lang) ? lang : ''
      const html = language
        ? hljs.highlight(code, { language }).value
        : hljs.highlightAuto(code).value
      return `<div class="code-block"><div class="code-header"><span>${language || 'code'}</span><button class="code-copy" type="button">复制</button></div><pre><code class="hljs">${html}</code></pre></div>`
    },
  },
})

function renderMd(md) {
  return DOMPurify.sanitize(marked.parse(md || ''))
}

const question = ref('')
const loading = ref(false)
const messages = ref([])
const msgArea = ref()
const sessions = ref([])
const currentSessionId = ref(null)

const suggestions = [
  '差旅报销的具体标准是什么？',
  '上班迟到 15 分钟怎么处理？',
  '高管年薪由哪几部分构成？',
  '会议室爽约几次会被暂停预订？',
]

async function loadSessions() {
  try {
    const res = await api.getSessions()
    sessions.value = res.data
  } catch (e) {
    // 静默失败，不影响问答
  }
}

function newChat() {
  currentSessionId.value = null
  messages.value = []
  question.value = ''
}

async function confirmDeleteSession(s) {
  try {
    await ElMessageBox.confirm(`删除对话「${s.title}」？删除后不可恢复`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await api.deleteSession(s.id)
    if (currentSessionId.value === s.id) newChat()
    await loadSessions()
    ElMessage.success('会话已删除')
  } catch {
    ElMessage.error('删除失败')
  }
}

async function selectSession(sessionId) {
  currentSessionId.value = sessionId
  messages.value = []
  try {
    const res = await api.getSessionMessages(sessionId)
    const data = res.data
    for (const msg of data.messages) {
      messages.value.push({ role: 'user', content: msg.question })
      messages.value.push({
        role: 'assistant',
        content: renderMd(msg.answer),
        cited: (msg.cited_chunk_ids || []).map(id => ({ chunk_id: id, doc_id: id.split('-')[0], heading: '' })),
        blocked: (msg.blocked_doc_ids || []).length,
        logId: msg.id,
        feedback: msg.feedback || 0,
        thinking: false,
        streaming: false,
      })
    }
    await scrollToBottom()
  } catch (e) {
    ElMessage.error('加载会话历史失败')
  }
}

async function scrollToBottom() {
  await nextTick()
  if (msgArea.value) msgArea.value.scrollTop = msgArea.value.scrollHeight
}

async function sendSuggestion(s) {
  question.value = s
  await handleSend()
}

// 事件委托：代码块复制按钮（v-html 内容无法绑定 Vue 事件）
async function handleClickMessages(e) {
  const btn = e.target.closest('.code-copy')
  if (!btn) return
  const code = btn.closest('.code-block')?.querySelector('code')
  if (!code) return
  try {
    await navigator.clipboard.writeText(code.innerText)
    btn.textContent = '已复制'
    ElMessage.success('代码已复制')
    setTimeout(() => (btn.textContent = '复制'), 1500)
  } catch {
    ElMessage.error('复制失败')
  }
}

async function handleSend() {
  const q = question.value.trim()
  if (!q || loading.value) return
  loading.value = true
  question.value = ''

  messages.value.push({ role: 'user', content: q })
  const aiMsg = reactive({
    role: 'assistant', content: '', rawText: '', cited: [], blocked: 0,
    logId: null, feedback: 0, thinking: true, streaming: false,
  })
  messages.value.push(aiMsg)
  await scrollToBottom()

  try {
    await api.chatStream(q, currentSessionId.value, (event) => {
      if (event.type === 'session') {
        currentSessionId.value = event.session_id
        loadSessions()
      } else if (event.type === 'log') {
        aiMsg.logId = event.log_id
      } else if (event.type === 'faq_hit') {
        aiMsg.thinking = false
        aiMsg.content = renderMd(event.answer)
      } else if (event.type === 'chunk') {
        if (aiMsg.thinking) { aiMsg.thinking = false; aiMsg.streaming = true }
        aiMsg.rawText += event.content
        aiMsg.content = renderMd(aiMsg.rawText)
      } else if (event.type === 'meta') {
        aiMsg.cited = event.cited_chunks || []
        aiMsg.blocked = event.blocked_count || 0
      }
      scrollToBottom()
    })
    aiMsg.streaming = false
    loadSessions()
  } catch (e) {
    aiMsg.thinking = false
    aiMsg.streaming = false
    aiMsg.content = '⚠️ 请求失败，请检查网络或后端服务是否正常'
    if (e.response?.status === 401) ElMessage.error('登录已过期')
  } finally {
    loading.value = false
  }
}

async function sendFeedback(msg, value) {
  const newValue = msg.feedback === value ? 0 : value
  try {
    await api.sendFeedback(msg.logId, newValue)
    msg.feedback = newValue
    if (newValue !== 0) ElMessage.success(newValue === 1 ? '感谢您的反馈' : '已记录，我们会持续改进')
  } catch (e) {
    // 错误提示由拦截器处理
  }
}

onMounted(loadSessions)
</script>

<style scoped>
.chat-page {
  display: flex;
  height: calc(100vh - 100px);
  background: #fff;
  border-radius: 12px;
  border: 1px solid var(--kb-border);
  overflow: hidden;
}

/* 会话侧边栏 */
.session-panel {
  width: 240px;
  border-right: 1px solid var(--kb-border);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  background: #fbfcfb;
}
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px 10px;
}
.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  font-size: 13px;
  color: var(--kb-text);
}
.session-item:hover {
  background: #f0f4f2;
}
.session-item.active {
  background: var(--el-color-primary-light-9);
  color: var(--kb-primary-dark);
  font-weight: 600;
}
.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.session-del {
  flex-shrink: 0;
  opacity: 0;
  color: var(--kb-text-secondary);
  transition: opacity .15s;
}
.session-item:hover .session-del { opacity: .6; }
.session-del:hover { opacity: 1 !important; color: #f56c6c; }
.session-empty {
  text-align: center;
  color: #c0c4cc;
  padding: 30px 0;
  font-size: 13px;
}

/* 对话区 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.msg-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
}

/* 空状态 */
.chat-empty {
  text-align: center;
  padding: 70px 20px 30px;
}
.empty-icon {
  width: 60px;
  height: 60px;
  border-radius: 18px;
  margin: 0 auto 18px;
  background: var(--el-color-primary-light-9);
  color: var(--kb-primary);
  display: flex;
  align-items: center;
  justify-content: center;
}
.chat-empty h3 {
  font-size: 18px;
  color: var(--kb-text);
}
.empty-desc {
  color: var(--kb-text-secondary);
  font-size: 13px;
  margin-top: 8px;
}
.suggest-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 420px;
  margin: 28px auto 0;
}
.suggest-item {
  padding: 12px 18px;
  border: 1px solid var(--kb-border);
  border-radius: 10px;
  background: #fbfcfb;
  font-size: 13px;
  color: var(--kb-text);
  cursor: pointer;
  text-align: left;
  transition: all .15s;
}
.suggest-item:hover {
  border-color: var(--kb-primary);
  background: var(--el-color-primary-light-9);
}

/* 气泡 */
.bubble-user {
  background: var(--kb-primary);
  color: #fff;
  padding: 10px 16px;
  border-radius: 14px 14px 2px 14px;
  max-width: 70%;
  font-size: 14px;
  line-height: 1.7;
}
.ai-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.bubble-ai {
  background: #f6f8f7;
  padding: 12px 16px;
  border-radius: 2px 14px 14px 14px;
  min-height: 44px;
}

/* 引用标签 */
.cite-list {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.cite-tag {
  font-size: 11px;
  color: var(--kb-primary-dark);
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 6px;
  padding: 2px 8px;
}

/* 反馈 */
.feedback-bar {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}
.fb-btn {
  border: 1px solid var(--kb-border);
  background: #fff;
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--kb-text-secondary);
  cursor: pointer;
  transition: all .15s;
}
.fb-btn:hover {
  border-color: var(--kb-primary);
  color: var(--kb-primary);
}
.fb-btn.liked {
  border-color: var(--kb-primary);
  background: var(--el-color-primary-light-9);
  color: var(--kb-primary-dark);
}
.fb-btn.disliked {
  border-color: #f56c6c;
  background: #fef0f0;
  color: #f56c6c;
}

/* 输入区 */
.input-bar {
  border-top: 1px solid var(--kb-border);
  padding: 14px 20px;
  display: flex;
  gap: 10px;
  background: #fbfcfb;
}
</style>
