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
    <el-dialog v-model="uploadDialog" title="上传知识文档" width="640px" :close-on-click-modal="!uploading" :close-on-press-escape="!uploading">
      <el-form label-width="90px">
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
        <el-form-item label="分类">
          <el-select v-model="uploadForm.category" allow-create filterable style="width: 100%">
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
      <div v-if="uploading" style="margin: 0 16px 8px">
        <el-progress :percentage="taskProgress" :stroke-width="14" :text-inside="true" />
        <div style="font-size: 12px; color: #909399; margin-top: 6px">{{ taskStatusText }}</div>
      </div>
      <template #footer>
        <el-button @click="uploadDialog = false" :disabled="uploading">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="submitUpload">
          {{ uploading ? '处理中…' : '开始导入' }}
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
import { Delete, Plus, Upload, UploadFilled } from '@element-plus/icons-vue'
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
