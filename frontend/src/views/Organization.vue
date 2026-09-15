<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- 用户管理 -->
      <el-tab-pane label="用户管理" name="users">
        <div style="margin-bottom: 16px">
          <el-button type="primary" :icon="Plus" @click="openUserDialog">新增用户</el-button>
        </div>
        <el-table :data="users" v-loading="loading" border>
          <el-table-column prop="username" label="用户名" width="120" />
          <el-table-column prop="display_name" label="姓名" width="100" />
          <el-table-column prop="dept_name" label="部门" width="120" />
          <el-table-column label="角色" width="200">
            <template #default="{ row }">
              <el-tag v-for="r in row.roles" :key="r" size="small" style="margin: 2px">{{ r }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{ row.is_active ? '正常' : '禁用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="管理员" width="80" align="center">
            <template #default="{ row }">
              <el-icon v-if="row.is_admin" color="#409eff"><Check /></el-icon>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEditDialog(row)">编辑</el-button>
              <el-button size="small" type="warning" link @click="openResetPwd(row)">重置密码</el-button>
              <el-popconfirm :title="`确定${row.is_active ? '禁用' : '启用'} ${row.display_name}？`" @confirm="toggleActive(row)">
                <template #reference>
                  <el-button size="small" :type="row.is_active ? 'danger' : 'success'" link>
                    {{ row.is_active ? '禁用' : '启用' }}
                  </el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 部门管理 -->
      <el-tab-pane label="部门管理" name="depts">
        <el-table :data="departments" v-loading="loading" border>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="部门名称" />
          <el-table-column prop="parent_id" label="上级部门" width="120">
            <template #default="{ row }">{{ row.parent_id || '—' }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 角色管理 -->
      <el-tab-pane label="角色管理" name="roles">
        <div style="margin-bottom: 16px">
          <el-button type="primary" :icon="Plus" @click="openRoleDialog">新增角色</el-button>
        </div>
        <el-table :data="roles" v-loading="loading" border>
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="角色名称" width="150" />
          <el-table-column prop="description" label="描述" />
          <el-table-column prop="user_count" label="用户数" width="80" align="center" />
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEditRoleDialog(row)">编辑</el-button>
              <el-popconfirm
                :title="row.user_count > 0 ? `该角色下有 ${row.user_count} 个用户，无法删除` : `确定删除角色「${row.name}」？`"
                :disabled="row.user_count > 0"
                @confirm="deleteRole(row)"
              >
                <template #reference>
                  <el-button size="small" type="danger" link :disabled="row.user_count > 0">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 新增用户弹窗 -->
    <el-dialog v-model="userDialog" title="新增用户" width="500px">
      <el-form :model="newUser" label-width="80px">
        <el-form-item label="用户名"><el-input v-model="newUser.username" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="newUser.display_name" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="newUser.password" type="password" show-password /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="newUser.dept_id" placeholder="选择部门（可不选）" clearable no-data-text="暂无部门" style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="newUser.role_ids" multiple placeholder="选择角色（可不选）" no-data-text="暂无角色，可先到「角色管理」创建" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveUser">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑用户弹窗 -->
    <el-dialog v-model="editDialog" :title="`编辑用户 — ${editUser.display_name}`" width="500px">
      <el-form :model="editUser" label-width="90px">
        <el-form-item label="姓名"><el-input v-model="editUser.display_name" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="editUser.dept_id" placeholder="选择部门（可不选）" clearable no-data-text="暂无部门" style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editUser.role_ids" multiple placeholder="选择角色（可不选）" no-data-text="暂无角色，可先到「角色管理」创建" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用状态">
          <el-switch v-model="editUser.is_active" active-text="正常" inactive-text="禁用" />
        </el-form-item>
        <el-form-item label="管理员">
          <el-switch v-model="editUser.is_admin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEditUser">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码弹窗 -->
    <el-dialog v-model="resetPwdDialog" :title="`重置密码 — ${resetTarget?.display_name}`" width="420px">
      <el-input v-model="newPassword" type="password" show-password placeholder="新密码（至少 6 位）" />
      <template #footer>
        <el-button @click="resetPwdDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveResetPwd">确认重置</el-button>
      </template>
    </el-dialog>

    <!-- 新增/编辑角色弹窗 -->
    <el-dialog v-model="roleDialog" :title="editingRole.id ? '编辑角色' : '新增角色'" width="440px">
      <el-form :model="editingRole" label-width="70px">
        <el-form-item label="名称">
          <el-input v-model="editingRole.name" placeholder="角色名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editingRole.description" type="textarea" :rows="2" placeholder="角色描述（选填）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRole">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Plus, Check } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const activeTab = ref('users')
const users = ref([])
const departments = ref([])
const roles = ref([])
const loading = ref(false)
const userDialog = ref(false)
const saving = ref(false)
const newUser = reactive({ username: '', display_name: '', password: '', dept_id: null, role_ids: [] })

const editDialog = ref(false)
const editUser = reactive({ id: null, display_name: '', dept_id: null, role_ids: [], is_active: true, is_admin: false })

const resetPwdDialog = ref(false)
const resetTarget = ref(null)
const newPassword = ref('')

const roleDialog = ref(false)
const editingRole = reactive({ id: null, name: '', description: '' })

async function loadData() {
  loading.value = true
  const tasks = [
    api.getUsers().then(u => { users.value = u.data }).catch(() => {}),
    api.getDepartments().then(d => { departments.value = d.data }).catch(() => {}),
    api.getRoles().then(r => { roles.value = r.data }).catch(() => {}),
  ]
  try {
    await Promise.all(tasks)
  } finally {
    loading.value = false
  }
}

function openUserDialog() {
  Object.assign(newUser, { username: '', display_name: '', password: '', dept_id: null, role_ids: [] })
  userDialog.value = true
}

async function saveUser() {
  if (!newUser.username.trim() || !newUser.password.trim()) {
    ElMessage.warning('用户名和密码不能为空')
    return
  }
  saving.value = true
  try {
    await api.createUser({ ...newUser })
    ElMessage.success('用户创建成功')
    userDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

function openEditDialog(row) {
  const dept = departments.value.find(d => d.name === row.dept_name)
  Object.assign(editUser, {
    id: row.id,
    display_name: row.display_name,
    dept_id: dept?.id ?? null,
    role_ids: roles.value.filter(r => row.roles.includes(r.name)).map(r => r.id),
    is_active: row.is_active,
    is_admin: row.is_admin,
  })
  editDialog.value = true
}

async function saveEditUser() {
  saving.value = true
  try {
    await api.updateUser(editUser.id, {
      display_name: editUser.display_name,
      dept_id: editUser.dept_id,
      role_ids: editUser.role_ids,
      is_active: editUser.is_active,
      is_admin: editUser.is_admin,
    })
    ElMessage.success('用户信息已更新')
    editDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function toggleActive(row) {
  try {
    await api.updateUser(row.id, { is_active: !row.is_active })
    ElMessage.success(`已${row.is_active ? '禁用' : '启用'} ${row.display_name}`)
    await loadData()
  } catch (e) {
    // 错误提示由拦截器处理
  }
}

function openResetPwd(row) {
  resetTarget.value = row
  newPassword.value = ''
  resetPwdDialog.value = true
}

async function saveResetPwd() {
  if (newPassword.value.length < 6) {
    ElMessage.warning('密码长度至少 6 位')
    return
  }
  saving.value = true
  try {
    await api.resetPassword(resetTarget.value.id, { new_password: newPassword.value })
    ElMessage.success(`已重置 ${resetTarget.value.display_name} 的密码`)
    resetPwdDialog.value = false
  } finally {
    saving.value = false
  }
}

function openRoleDialog() {
  Object.assign(editingRole, { id: null, name: '', description: '' })
  roleDialog.value = true
}

function openEditRoleDialog(row) {
  Object.assign(editingRole, { id: row.id, name: row.name, description: row.description || '' })
  roleDialog.value = true
}

async function saveRole() {
  if (!editingRole.name.trim()) {
    ElMessage.warning('角色名称不能为空')
    return
  }
  saving.value = true
  try {
    if (editingRole.id) {
      await api.updateRole(editingRole.id, {
        name: editingRole.name.trim(),
        description: editingRole.description.trim() || null,
      })
      ElMessage.success('角色已更新')
    } else {
      await api.createRole({
        name: editingRole.name.trim(),
        description: editingRole.description.trim() || null,
      })
      ElMessage.success('角色创建成功')
    }
    roleDialog.value = false
    await loadData()
  } finally {
    saving.value = false
  }
}

async function deleteRole(row) {
  try {
    await api.deleteRole(row.id)
    ElMessage.success(`已删除角色「${row.name}」`)
    await loadData()
  } catch { /* handled by interceptor */ }
}

onMounted(loadData)
</script>
