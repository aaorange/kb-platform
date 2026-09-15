<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- FAQ 管理 -->
      <el-tab-pane label="FAQ 管理" name="faq">
        <div style="margin-bottom: 16px; display: flex; gap: 10px">
          <el-button type="primary" :icon="Plus" @click="openFaqDialog">新增 FAQ</el-button>
          <el-button type="success" :loading="generating" @click="autoGenerate">自动生成 FAQ 草稿</el-button>
          <span style="font-size: 12px; color: #909399; align-self: center">从高频问题中检索生成答案，草稿审核后写入缓存</span>
        </div>
        <el-table :data="faqs" v-loading="loading" border>
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="question" label="问题" min-width="250" show-overflow-tooltip />
          <el-table-column prop="answer" label="回答" min-width="300" show-overflow-tooltip />
          <el-table-column prop="hit_count" label="命中次数" width="100" align="center" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_published ? 'success' : 'info'" size="small">{{ row.is_published ? '已发布' : '草稿' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="publishCache(row)">写入缓存</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 知识缺口 -->
      <el-tab-pane label="知识缺口池" name="gaps">
        <el-table :data="gaps" v-loading="loading" border>
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="question" label="未命中问题" min-width="300" show-overflow-tooltip />
          <el-table-column prop="frequency" label="出现次数" width="100" align="center">
            <template #default="{ row }">
              <el-tag type="danger" size="small">{{ row.frequency }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'open' ? 'warning' : 'success'" size="small">{{ row.status === 'open' ? '待处理' : '已解决' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="首次出现" width="180">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增 FAQ 弹窗 -->
    <el-dialog v-model="faqDialog" title="新增 FAQ" width="720px">
      <!-- 候选问题点选 -->
      <div style="margin-bottom: 16px">
        <div style="font-size: 13px; color: #606266; margin-bottom: 8px; display: flex; align-items: center; gap: 8px">
          候选问题（点击选用，来自问答记录与知识缺口）
          <el-button size="small" link type="primary" @click="loadCandidates" :loading="loadingCandidates">刷新</el-button>
        </div>
        <div v-if="candidates.length" style="display: flex; flex-wrap: wrap; gap: 8px; max-height: 180px; overflow-y: auto; padding: 4px">
          <el-button
            v-for="(c, i) in candidates"
            :key="i"
            size="small"
            :type="newFAQ.question === c.question ? 'primary' : (c.source === 'gap' ? 'danger' : 'default')"
            :plain="newFAQ.question !== c.question"
            @click="selectCandidate(c)"
          >
            {{ c.question }}<el-tag size="small" style="margin-left: 6px" :type="c.source === 'gap' ? 'danger' : 'info'">×{{ c.count }}</el-tag>
          </el-button>
        </div>
        <div v-else style="color: #c0c4cc; font-size: 13px; padding: 12px 0">暂无候选问题（可手动输入，或先让用户多提问）</div>
      </div>

      <el-form label-width="60px">
        <el-form-item label="问题">
          <el-input v-model="newFAQ.question" type="textarea" :rows="2" placeholder="点选上方候选问题，或手动输入" />
        </el-form-item>
        <el-form-item label="回答">
          <div style="width: 100%">
            <el-input v-model="newFAQ.answer" type="textarea" :rows="6" placeholder="点「AI 生成」自动生成，或手动输入" />
            <el-button
              type="primary" plain size="small" style="margin-top: 8px"
              :loading="generatingAnswer" :disabled="!newFAQ.question.trim()"
              @click="generateAnswer"
            >AI 生成回答</el-button>
            <span v-if="newFAQ.docIds.length" style="font-size: 12px; color: #909399; margin-left: 10px">
              依据 {{ newFAQ.docIds.length }} 篇文档生成
            </span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="faqDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveFAQ">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const activeTab = ref('faq')
const faqs = ref([])
const gaps = ref([])
const loading = ref(false)
const faqDialog = ref(false)
const saving = ref(false)
const generating = ref(false)
const newFAQ = reactive({ question: '', answer: '', docIds: [] })
const candidates = ref([])
const loadingCandidates = ref(false)
const generatingAnswer = ref(false)

async function loadData() {
  loading.value = true
  try {
    const [faqRes, gapRes] = await Promise.all([api.getFAQs(), api.getGaps()])
    faqs.value = faqRes.data
    gaps.value = gapRes.data
  } finally {
    loading.value = false
  }
}

async function loadCandidates() {
  loadingCandidates.value = true
  try {
    const res = await api.getFaqCandidates()
    candidates.value = res.data
  } finally {
    loadingCandidates.value = false
  }
}

function openFaqDialog() {
  Object.assign(newFAQ, { question: '', answer: '', docIds: [] })
  faqDialog.value = true
  loadCandidates()
}

function selectCandidate(c) {
  if (newFAQ.question === c.question) {
    newFAQ.question = ''
    return
  }
  newFAQ.question = c.question
  newFAQ.answer = ''
  newFAQ.docIds = []
}

async function generateAnswer() {
  if (!newFAQ.question.trim()) return
  generatingAnswer.value = true
  try {
    const res = await api.generateFaqAnswer(newFAQ.question.trim())
    newFAQ.answer = res.data.answer
    newFAQ.docIds = res.data.doc_ids || []
    ElMessage.success('已生成，可在此基础上修改')
  } catch (e) {
    // 拦截器已提示
  } finally {
    generatingAnswer.value = false
  }
}

async function saveFAQ() {
  if (!newFAQ.question.trim() || !newFAQ.answer.trim()) {
    ElMessage.warning('问题和回答不能为空')
    return
  }
  saving.value = true
  try {
    await api.createFAQ({
      question: newFAQ.question.trim(),
      answer: newFAQ.answer.trim(),
      doc_ids: newFAQ.docIds,
    })
    ElMessage.success('FAQ 创建成功')
    faqDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function publishCache(row) {
  try {
    await api.publishFAQCache(row.id)
    ElMessage.success('FAQ 已写入 Redis 缓存')
  } catch (e) {
    ElMessage.warning('写入失败，Redis 可能未启动')
  }
}

async function autoGenerate() {
  generating.value = true
  try {
    const res = await api.autoGenFaqs(3)
    const { generated, skipped, message } = res.data
    let tip = message
    if (generated?.length) tip += `（${generated.map(g => `「${g.question}」×${g.ask_count}`).join('、')}）`
    if (skipped?.length) tip += `；跳过 ${skipped.length} 条`
    ElMessage({ type: generated?.length ? 'success' : 'warning', message: tip, duration: 6000 })
    await loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '自动生成失败')
  } finally {
    generating.value = false
  }
}

function formatTime(t) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

onMounted(loadData)
</script>
