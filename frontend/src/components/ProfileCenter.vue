<template>
  <div class="profile-page">
    <section class="profile-card">
      <div class="profile-avatar">{{ user?.name?.slice(-1) || '员' }}</div>
      <div class="profile-heading">
        <span class="page-kicker">PERSONAL PROFILE</span>
        <h2>{{ user?.name }}</h2>
        <p>{{ user?.department_name || '平台管理' }} · {{ user?.position || user?.role_name }}</p>
      </div>
      <span class="role-pill">{{ user?.role_name }}</span>
    </section>

    <section class="profile-grid">
      <article class="info-card">
        <h3>员工信息</h3>
        <div class="info-list">
          <div><span>工号</span><strong>{{ user?.employee_id || '-' }}</strong></div>
          <div><span>登录账号</span><strong>{{ user?.username }}</strong></div>
          <div><span>所属部门</span><strong>{{ user?.department_name || '-' }}</strong></div>
          <div><span>岗位</span><strong>{{ user?.position || '-' }}</strong></div>
          <div><span>入职日期</span><strong>{{ user?.hire_date || '-' }}</strong></div>
          <div><span>邮箱</span><strong>{{ user?.email || '-' }}</strong></div>
        </div>
      </article>

      <article class="info-card">
        <h3>修改密码</h3>
        <p class="card-tip">密码至少 8 位，建议同时包含大小写字母、数字和符号。</p>
        <el-form label-position="top">
          <el-form-item label="原密码"><el-input v-model="form.old_password" type="password" show-password /></el-form-item>
          <el-form-item label="新密码"><el-input v-model="form.new_password" type="password" show-password /></el-form-item>
          <el-form-item label="确认新密码"><el-input v-model="confirmPassword" type="password" show-password /></el-form-item>
          <el-button type="primary" :loading="saving" @click="submitPassword">更新密码</el-button>
        </el-form>
      </article>

      <article class="info-card permissions-card">
        <h3>当前权限</h3>
        <div class="permission-list">
          <span v-for="permission in user?.permissions || []" :key="permission">{{ permission }}</span>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { changePassword } from '../api/index.js'
import { authState, persistAuth, refreshCurrentUser } from '../auth.js'

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['password-changed'])
const saving = ref(false)
const confirmPassword = ref('')
const form = reactive({ old_password: '', new_password: '' })

async function submitPassword() {
  if (!form.old_password || !form.new_password) return ElMessage.warning('请完整填写密码')
  if (form.new_password.length < 8) return ElMessage.warning('新密码至少 8 位')
  if (form.new_password !== confirmPassword.value) return ElMessage.warning('两次输入的新密码不一致')
  saving.value = true
  try {
    await changePassword(form)
    let nextUser
    try {
      nextUser = await refreshCurrentUser()
    } catch (refreshError) {
      nextUser = { ...props.user, must_change_password: 0 }
      persistAuth(authState.token, nextUser)
    }
    ElMessage.success('密码已修改，已解除首次登录限制')
    form.old_password = ''
    form.new_password = ''
    confirmPassword.value = ''
    emit('password-changed', nextUser)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '密码修改失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.profile-page{display:flex;flex-direction:column;gap:18px}.profile-card{display:grid;grid-template-columns:78px 1fr auto;gap:20px;align-items:center;padding:30px;border:1px solid #202638;border-radius:22px;background:radial-gradient(circle at 80% 20%,rgba(76,111,255,.18),transparent 30%),#10131d}.profile-avatar{width:72px;height:72px;display:grid;place-items:center;border-radius:22px;background:linear-gradient(135deg,#4b6fff,#8458ff);font-size:28px;font-weight:800;color:#fff}.page-kicker{color:#6f8dff;font-size:11px;letter-spacing:2px}.profile-heading h2{margin:7px 0 5px;color:#f8fafc;font-size:28px}.profile-heading p{margin:0;color:#778195}.role-pill{padding:7px 12px;border-radius:999px;background:rgba(75,111,255,.14);color:#8ea6ff;font-size:12px}.profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.info-card{padding:24px;border:1px solid #202638;border-radius:20px;background:#10131d}.info-card h3{color:#e4e9f1;margin:0 0 18px}.info-list{display:grid;grid-template-columns:1fr 1fr;gap:12px}.info-list>div{padding:14px;border:1px solid #242b3d;border-radius:13px;background:#131722}.info-list span,.info-list strong{display:block}.info-list span{color:#707b8e;font-size:11px;margin-bottom:5px}.info-list strong{color:#dce2eb}.card-tip{color:#6e788b;font-size:12px;line-height:1.7}.permissions-card{grid-column:1/-1}.permission-list{display:flex;flex-wrap:wrap;gap:8px}.permission-list span{padding:6px 10px;border-radius:9px;background:#151b2c;color:#819cff;border:1px solid #26345c;font-size:11px}@media(max-width:900px){.profile-grid{grid-template-columns:1fr}.permissions-card{grid-column:auto}.profile-card{grid-template-columns:64px 1fr}.role-pill{display:none}.info-list{grid-template-columns:1fr}}
</style>
