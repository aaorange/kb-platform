<template>
  <div>
    <div style="margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center">
      <span style="color: #909399; font-size: 13px">共 {{ units.length }} 份知识文档</span>
      <el-button type="primary" :icon="Upload" @click="openUploadDialog">上传文档</el-button>
    </div>

    <el-table :data="units" v-loading="loading" border style="width: 100%">
      <el-table-column prop="doc_id" label="文档编号" width="160" />
      <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="category" label="分类" width="100" />
      <el-table-column prop="char_count" label="字符数" width="90" />
      <el-table-column label="权限" width="280">
        <template #default="{ row }">
          <el-tag v-for="(p, i) in row.permissions" :key="i" :type="permTagType(p.scope_type)" size="small" style="margin: 2px">
            {{ permLabel(p) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_enabled ? 'success' : 'danger'" size="small">{{ row.is_enabled ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240">
        <template #default="{ row }">
          <el-button size="small" link @click="openPreview(row)">预览</el-button>
          <el-button size="small" type="primary" link @click="openPermDialog(row)">权限</el-button>
          <el-button size="small" :type="row.is_enabled ? 'warning' : 'success'" link @click="toggleUnit(row)">
            {{ row.is_enabled ? '禁用' : '启用' }}
          </el-button>
          <el-popconfirm title="确定删除此文档？向量数据将同步清除" @confirm="deleteUnit(row)" confirm-button-text="删除" cancel-button-text="取消">
            <template #reference>
              <el-button size="small" type="danger" link>删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <!-- 文档预览弹窗 -->
    <el-dialog v-model="previewDialog" :title="previewData?.title || '文档预览'" width="760px" top="5vh">
      <div v-if="previewData">
        <div style="margin-bottom: 12px; display: flex; gap: 12px; flex-wrap: wrap">
          <el-tag size="small" type="info">{{ previewData.doc_id }}</el-tag>
          <el-tag size="small">{{ previewData.category }}</el-tag>
          <el-tag size="small" type="warning">{{ previewData.char_count }} 字</el-tag>
          <el-tag size="small" type="success">{{ previewData.chunk_count }} 切片</el-tag>
          <el-tag size="small" :type="previewData.is_enabled ? 'success' : 'danger'">{{ previewData.is_enabled ? '启用' : '已禁用' }}</el-tag>
        </div>
        <div style="max-height: 60vh; overflow-y: auto; border: 1px solid #ebeef5; border-radius: 8px; padding: 20px; background: #fafafa">
          <div v-for="(c, i) in previewData.chunks" :key="i" style="margin-bottom: 24px">
            <div style="font-size: 13px; color: #909399; margin-bottom: 6px; border-left: 3px solid #409eff; padding-left: 8px">
              #{{ c.chunk_index + 1 }} {{ c.heading }}
            </div>
            <div style="white-space: pre-wrap; line-height: 1.8; font-size: 14px">{{ c.content }}</div>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 上传弹窗 -->
    <el-dialog v-model="uploadDialog" title="上传知识文档" width="720px" :close-on-click-modal="!uploading" :close-on-press-escape="!uploading">
      <el-form label-width="90px">
        <!-- 模式切换：单文件 / 文件夹 -->
        <el-form-item label="上传模式">
          <el-radio-group v-model="uploadMode" :disabled="uploading">
            <el-radio-button label="single">单文件</el-radio-button>
            <el-radio-button label="folder">文件夹</el-radio-button>
          </el-radio-group>
          <span style="margin-left: 12px; font-size: 12px; color: #909399">文件夹模式：递归选中目录下所有合规文件，串行导入</span>
        </el-form-item>

        <!-- 单文件模式：保留原 el-upload（拖拽 + 单选 + 体积拦截） -->
        <template v-if="uploadMode === 'single'">
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              drag
              :auto-upload="false"
              :limit="1"
              :on-change="onFileChange"
              :on-remove="() => (uploadFile = null)"
              :on-exceed="onExceed"
              accept=".md,.txt,.docx,.pdf"
              style="width: 100%"
            >
              <el-icon style="font-size: 40px; color: #c0c4cc"><UploadFilled /></el-icon>
              <div style="margin-top: 8px">拖拽文件到此处，或点击选择</div>
              <template #tip>
                <div style="font-size: 12px; color: #909399">支持 .md / .txt / .docx / .pdf，单文件不超过 40MB</div>
              </template>
            </el-upload>
          </el-form-item>
          <el-form-item label="知识标题">
            <el-input v-model="uploadForm.title" placeholder="默认使用文件名" />
          </el-form-item>
        </template>

        <!-- 文件夹模式：原生 input[webkitdirectory] 选目录 + 文件列表 -->
        <template v-else>
          <el-form-item label="选择文件夹">
            <div style="width: 100%">
              <!-- 隐藏的原生 input：webkitdirectory 递归选目录；el-upload 不支持目录，只能用原生 -->
              <input ref="folderInputRef" type="file" webkitdirectory directory multiple style="display: none" @change="onFolderChange" />
              <el-button :icon="FolderOpened" :disabled="uploading" @click="folderInputRef?.click()">选择文件夹</el-button>
              <span v-if="folderFiles.length || folderSkipped" style="margin-left: 12px; font-size: 12px; color: #909399">
                合规 {{ folderFiles.length }} 个，跳过 {{ folderSkipped }} 个（格式/体积不符）
              </span>
            </div>
          </el-form-item>
          <el-form-item v-if="folderFiles.length" label="文件列表">
            <div style="width: 100%; max-height: 240px; overflow-y: auto; border: 1px solid #ebeef5; border-radius: 6px">
              <div v-for="(f, i) in folderFiles" :key="i" style="display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid #f5f5f5; font-size: 13px">
                <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap" :title="f.webkitRelativePath || f.name">{{ f.webkitRelativePath || f.name }}</span>
                <span style="color: #909399; width: 72px; text-align: right">{{ (f.size / 1024 / 1024).toFixed(2) }}MB</span>
                <el-tag :type="folderStatusType(i)" size="small" style="width: 64px; text-align: center">{{ folderStatusText(i) }}</el-tag>
                <el-button v-if="!uploading" :icon="Delete" circle size="small" @click="folderFiles.splice(i, 1)" />
              </div>
            </div>
          </el-form-item>
        </template>

        <!-- 公共配置：分类 + 权限（两种模式共用；文件夹模式分类应用到全部文件） -->
        <el-form-item label="分类">
          <el-select v-model="uploadForm.category" allow-create filterable style="width: 100%" :disabled="uploading">
            <el-option v-for="c in ['未分类', '财务', 'HR', '客服', '产品', '技术', '通用制度']" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="访问权限">
          <div style="width: 100%">
            <div v-for="(perm, i) in uploadPerms" :key="i" style="display: flex; gap: 10px; margin-bottom: 10px; align-items: center">
              <el-select v-model="perm.scope_type" placeholder="权限维度" style="width: 140px" @change="perm.scope_value = ''">
                <el-option label="全局公开" value="global" />
                <el-option label="部门可见" value="department" />
                <el-option label="角色可见" value="role" />
                <el-option label="指定用户" value="user" />
              </el-select>
              <el-input v-if="perm.scope_type !== 'global'" v-model="perm.scope_value" placeholder="输入部门名/角色名/用户名" style="flex: 1" />
              <el-button type="danger" :icon="Delete" circle size="small" @click="uploadPerms.splice(i, 1)" />
            </div>
            <el-button type="primary" plain :icon="Plus" @click="uploadPerms.push({ scope_type: 'global', scope_value: '' })">添加权限规则</el-button>
            <div style="font-size: 12px; color: #909399; margin-top: 6px">不添加任何规则 = 仅管理员可见（无权限配置默认不可见）</div>
          </div>
        </el-form-item>
      </el-form>

      <!-- 进度区：单文件走原单进度条；文件夹模式额外显示批量汇总 -->
      <div v-if="uploading" style="margin: 0 16px 8px">
        <template v-if="uploadMode === 'single'">
          <el-progress :percentage="taskProgress" :stroke-width="14" :text-inside="true" />
          <div style="font-size: 12px; color: #909399; margin-top: 6px">{{ taskStatusText }}</div>
        </template>
        <template v-else>
          <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 13px">
            <span>第 {{ batchCurrent }}/{{ folderFiles.length }} 个：{{ batchCurrentFile }}</span>
            <span style="color: #909399">成功 {{ batchSuccess }} · 重复 {{ batchDup }} · 失败 {{ batchFail }}</span>
          </div>
          <el-progress :percentage="taskProgress" :stroke-width="14" :text-inside="true" />
          <div style="font-size: 12px; color: #909399; margin-top: 6px">{{ taskStatusText }}</div>
        </template>
      </div>
      <template #footer>
        <el-button @click="uploadDialog = false" :disabled="uploading">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          {{ uploading ? '处理中…' : (uploadMode === 'folder' ? `开始导入（${folderFiles.length} 个）` : '开始导入') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 权限配置弹窗 -->
    <el-dialog v-model="permDialog" title="配置知识权限" width="600px">
      <el-form label-width="80px">
        <div v-for="(perm, i) in editPerms" :key="i" style="display: flex; gap: 10px; margin-bottom: 12px; align-items: center">
          <el-select v-model="perm.scope_type" placeholder="权限维度" style="width: 140px" @change="perm.scope_value = ''">
            <el-option label="全局公开" value="global" />
            <el-option label="部门可见" value="department" />
            <el-option label="角色可见" value="role" />
            <el-option label="指定用户" value="user" />
          </el-select>
          <el-input v-if="perm.scope_type !== 'global'" v-model="perm.scope_value" placeholder="输入部门名/角色名/用户名" style="flex: 1" />
          <el-button type="danger" :icon="Delete" circle size="small" @click="editPerms.splice(i, 1)" />
        </div>
        <el-button type="primary" plain :icon="Plus" @click="editPerms.push({ scope_type: 'global', scope_value: '' })">添加权限规则</el-button>
      </el-form>
      <template #footer>
        <el-button @click="permDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="savePermissions">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Delete, FolderOpened, Plus, Upload, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const units = ref([])
const loading = ref(false)
const permDialog = ref(false)
const saving = ref(false)
const editPerms = ref([])
const currentUnit = ref(null)

const uploadDialog = ref(false)
const uploading = ref(false)
const uploadFile = ref(null)
const uploadRef = ref(null)
const MAX_UPLOAD_MB = 40  // 与后端 MAX_UPLOAD_SIZE_MB / nginx client_max_body_size 对齐
const uploadForm = ref({ title: '', category: '未分类' })
const uploadPerms = ref([{ scope_type: 'global', scope_value: '' }])
const taskProgress = ref(0)
const taskStatusText = ref('')

// ===== 文件夹批量上传相关状态 =====
const uploadMode = ref('single')         // single | folder：弹窗内模式切换
const folderInputRef = ref(null)         // 原生 input[webkitdirectory] 引用（el-upload 不支持目录）
const folderFiles = ref([])              // 客户端过滤后的合规文件 File[]
const folderSkipped = ref(0)             // 格式/体积不符被跳过的数量
const folderStatuses = ref([])           // 每个文件状态：pending|processing|success|duplicate|failed
const batchCurrent = ref(0)              // 当前处理到第几个（1-based）
const batchCurrentFile = ref('')         // 当前处理的文件名（UI 显示）
const batchSuccess = ref(0)
const batchDup = ref(0)
const batchFail = ref(0)

const previewDialog = ref(false)
const previewData = ref(null)

async function openPreview(row) {
  try {
    const res = await api.previewUnit(row.id)
    previewData.value = res.data
    previewDialog.value = true
  } catch (e) {
    // 403 无权限时由拦截器提示
  }
}

function openUploadDialog() {
  uploadFile.value = null
  uploadForm.value = { title: '', category: '未分类' }
  uploadPerms.value = [{ scope_type: 'global', scope_value: '' }]
  // 重置文件夹批量状态（上次批量上传的残留清掉）
  uploadMode.value = 'single'
  folderFiles.value = []
  folderSkipped.value = 0
  folderStatuses.value = []
  batchCurrent.value = 0
  batchCurrentFile.value = ''
  batchSuccess.value = 0
  batchDup.value = 0
  batchFail.value = 0
  taskProgress.value = 0
  taskStatusText.value = ''
  if (folderInputRef.value) folderInputRef.value.value = ''  // 清空原生 input，允许重选同一目录
  uploadDialog.value = true
}

function onFileChange(file) {
  // 上传体积前置拦截：超过上限直接拒绝（不发请求），后端/nginx 仍兜底校验
  if (file.raw && file.raw.size > MAX_UPLOAD_MB * 1024 * 1024) {
    uploadFile.value = null
    uploadRef.value?.clearFiles()
    ElMessage.error(`文件超过 ${MAX_UPLOAD_MB}MB 上限（当前 ${(file.raw.size / 1024 / 1024).toFixed(1)}MB），请拆分或压缩后再上传`)
    return
  }
  uploadFile.value = file.raw
  if (!uploadForm.value.title) uploadForm.value.title = file.name.replace(/\.[^.]+$/, '')
}

// limit=1 时再次选择/拖入文件：el-upload 默认静默忽略（既无提示也绕过体积校验），
// 改为"替换当前文件"，让新文件重新走 onFileChange 的体积拦截
function onExceed(files) {
  const file = files && files[0]
  if (!file) return
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    ElMessage.error(`文件超过 ${MAX_UPLOAD_MB}MB 上限（当前 ${(file.size / 1024 / 1024).toFixed(1)}MB），请拆分或压缩后再上传`)
    return
  }
  uploadRef.value?.clearFiles()
  uploadRef.value?.handleStart(file)
}

// ===== 文件夹选择回调：读取 webkitdirectory 选中的所有文件，按格式 + 体积过滤 =====
const SUPPORTED_FOLDER_EXTS = ['.md', '.txt', '.docx', '.pdf']  // 与单文件 accept 一致
function onFolderChange(e) {
  const all = Array.from(e.target.files || [])  // FileList 每项含 webkitRelativePath 相对路径
  const ok = []
  let skipped = 0
  for (const f of all) {
    const name = f.name.toLowerCase()
    const ext = name.slice(name.lastIndexOf('.'))  // 含点，如 .md
    if (!SUPPORTED_FOLDER_EXTS.includes(ext)) { skipped++; continue }
    if (f.size > MAX_UPLOAD_MB * 1024 * 1024) { skipped++; continue }
    ok.push(f)
  }
  folderFiles.value = ok
  folderSkipped.value = skipped
  folderStatuses.value = ok.map(() => 'pending')
  batchCurrent.value = 0
  batchCurrentFile.value = ''
  batchSuccess.value = 0
  batchDup.value = 0
  batchFail.value = 0
  if (ok.length === 0) {
    ElMessage.warning(skipped ? `所选目录没有合规文件（跳过 ${skipped} 个）` : '所选目录为空')
  }
}

// 文件夹模式下文件列表每行的状态标签
function folderStatusText(i) {
  return { pending: '待处理', processing: '处理中', success: '成功', duplicate: '已重复', failed: '失败' }[folderStatuses.value[i]] || ''
}
function folderStatusType(i) {
  return { pending: 'info', processing: 'warning', success: 'success', duplicate: 'info', failed: 'danger' }[folderStatuses.value[i]] || ''
}

// 轮询后台导入任务进度，直至 completed / duplicate / failed
async function pollTask(taskId) {
  while (true) {
    await new Promise((r) => setTimeout(r, 2000))
    const r = await api.getTaskStatus(taskId)
    taskProgress.value = r.data.progress
    taskStatusText.value = r.data.message
    const s = r.data.status
    if (s === 'completed' || s === 'duplicate') return r.data
    if (s === 'failed') throw new Error(r.data.message)
  }
}

async function submitUpload() {
  // 文件夹模式走批量串行提交，单文件走原逻辑
  if (uploadMode.value === 'folder') return submitFolderUpload()

  if (!uploadFile.value) return ElMessage.warning('请先选择文件')
  uploading.value = true
  taskProgress.value = 0
  taskStatusText.value = '上传文件中…'
  try {
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    fd.append('title', uploadForm.value.title)
    fd.append('category', uploadForm.value.category)
    fd.append('permissions', JSON.stringify(uploadPerms.value))
    const res = await api.uploadDocument(fd)
    if (res.data.duplicated) {
      ElMessage.warning(res.data.message)
      uploadDialog.value = false
      return
    }
    taskStatusText.value = '已提交后台处理…'
    const task = await pollTask(res.data.task_id)
    if (task.status === 'completed') ElMessage.success(task.message)
    else ElMessage.warning(task.message)
    uploadDialog.value = false
    await loadData()
  } catch (e) {
    ElMessage.error(e.message || e.response?.data?.detail || '导入失败')
  } finally {
    uploading.value = false
  }
}

// ===== 文件夹批量上传：串行循环调现有 /upload，复用 pollTask 轮询，聚合进度 =====
// 后端零改动：每文件一个 task_id，后端 Semaphore(1) 自动串行处理 + SHA256 去重
async function submitFolderUpload() {
  if (!folderFiles.value.length) return ElMessage.warning('请先选择文件夹且至少有一个合规文件')
  uploading.value = true
  batchCurrent.value = 0
  batchCurrentFile.value = ''
  batchSuccess.value = 0
  batchDup.value = 0
  batchFail.value = 0
  taskProgress.value = 0
  taskStatusText.value = ''
  try {
    for (let i = 0; i < folderFiles.value.length; i++) {
      const f = folderFiles.value[i]
      batchCurrent.value = i + 1
      batchCurrentFile.value = f.webkitRelativePath || f.name
      folderStatuses.value[i] = 'processing'
      taskProgress.value = 0
      taskStatusText.value = `上传中：${batchCurrentFile.value}`
      try {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('title', f.name.replace(/\.[^.]+$/, ''))  // 文件夹模式标题用各自文件名（去扩展名）
        fd.append('category', uploadForm.value.category)      // 公共分类应用到全部
        fd.append('permissions', JSON.stringify(uploadPerms.value))  // 公共权限应用到全部
        const res = await api.uploadDocument(fd)
        // SHA256 命中重复：后端秒回 duplicated，不算失败，继续下一个
        if (res.data.duplicated) {
          folderStatuses.value[i] = 'duplicate'
          batchDup.value++
          taskStatusText.value = `「${batchCurrentFile.value}」已存在，跳过`
          continue
        }
        taskStatusText.value = `后台处理中：${batchCurrentFile.value}`
        const task = await pollTask(res.data.task_id)
        if (task.status === 'completed') {
          folderStatuses.value[i] = 'success'
          batchSuccess.value++
        } else {
          folderStatuses.value[i] = 'failed'
          batchFail.value++
        }
      } catch (e) {
        // 单文件失败隔离：记失败，继续下一个，不中断整批
        folderStatuses.value[i] = 'failed'
        batchFail.value++
        console.error('导入失败', batchCurrentFile.value, e)
      }
    }
    // 批量汇总
    const total = folderFiles.value.length
    ElMessage.success(`批量导入完成：成功 ${batchSuccess.value} · 重复 ${batchDup.value} · 失败 ${batchFail.value}（共 ${total}）`)
    uploadDialog.value = false
    await loadData()
  } finally {
    uploading.value = false
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.getUnits()
    units.value = res.data
  } finally {
    loading.value = false
  }
}

function permLabel(p) {
  if (p.scope_type === 'global') return '全局公开'
  return `${p.scope_type}:${p.scope_value || ''}`
}

function permTagType(scope) {
  return { global: 'success', department: 'warning', role: 'primary', user: 'info' }[scope] || ''
}

function openPermDialog(row) {
  currentUnit.value = row
  editPerms.value = row.permissions.map(p => ({ ...p }))
  if (editPerms.value.length === 0) editPerms.value.push({ scope_type: 'global', scope_value: '' })
  permDialog.value = true
}

async function savePermissions() {
  saving.value = true
  try {
    await api.updatePermissions(currentUnit.value.id, { permissions: editPerms.value })
    ElMessage.success('权限更新成功')
    permDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function toggleUnit(row) {
  try {
    await api.toggleUnit(row.id)
    ElMessage.success(`已${row.is_enabled ? '禁用' : '启用'}「${row.title}」`)
    await loadData()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function deleteUnit(row) {
  try {
    await api.deleteUnit(row.id)
    ElMessage.success(`已删除「${row.title}」`)
    await loadData()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

onMounted(loadData)
</script>
