<template>
  <div class="login-page">
    <button class="login-theme-toggle" type="button" @click="toggleTheme">
      <span>{{ isDark ? '☀' : '☾' }}</span>
      {{ isDark ? '切换浅色主题' : '切换深色主题' }}
    </button>

    <div class="login-orb orb-one"></div>
    <div class="login-orb orb-two"></div>
    <div class="login-grid"></div>

    <section class="login-hero">
      <div class="brand-line">
        <div class="brand-mark">S</div>
        <div><strong>SmartOffice</strong><small>企业智能办公协同平台</small></div>
      </div>

      <div class="hero-copy">
        <span class="eyebrow">ENTERPRISE AI WORKSPACE</span>
        <h1>让每一次协作<br><span>更智能、更高效</span></h1>
        <p>统一接入 OA 智能申请、消息协同、知识检索、会议纪要、员工考核与经营报表，让每个岗位拥有清晰高效的数字工作空间。</p>
        <div class="feature-row">
          <div><b>01</b><strong>统一工作入口</strong><span>待办、通知和业务工具分层汇合</span></div>
          <div><b>02</b><strong>AI 工作流中台</strong><span>Dify 多应用统一配置与权限隔离</span></div>
          <div><b>03</b><strong>安全业务协同</strong><span>部门审批、数据权限与操作留痕</span></div>
        </div>
      </div>

      <div class="hero-footer">
        <span>SmartOffice · AI 驱动的企业协同体验</span>
        <span>安全 · 高效 · 可扩展</span>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <div class="login-heading">
          <span class="status-dot"></span>
          <span>内部员工入口</span>
        </div>
        <h2>欢迎回来</h2>
        <p class="login-subtitle">登录后进入你的智能工作台</p>

        <el-form :model="form" @submit.prevent="handleLogin">
          <el-form-item>
            <el-input
              v-model="form.username"
              size="large"
              placeholder="账号，例如 e001"
              autocomplete="username"
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <div class="login-options">
            <el-checkbox v-model="remember">记住账号</el-checkbox>
            <span>首次登录后请修改初始密码</span>
          </div>
          <el-button class="login-button" type="primary" size="large" :loading="loading" @click="handleLogin">
            登录工作台
          </el-button>
        </el-form>

        <div class="login-demo">
          <div><span>员工账号规则</span><code>工号小写，例如 E001 → e001</code></div>
          <div><span>初始密码</span><code>由管理员统一下发，首次登录必须修改</code></div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { login } from '../auth.js'
import { useTheme } from '../theme.js'

const { isDark, initTheme, toggleTheme } = useTheme()
initTheme()

const emit = defineEmits(['success'])
const loading = ref(false)
const remember = ref(true)
const form = reactive({ username: '', password: '' })

onMounted(() => {
  form.username = localStorage.getItem('smart_office_remember_username') || ''
})

async function handleLogin() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const data = await login(form.username.trim(), form.password)
    if (remember.value) localStorage.setItem('smart_office_remember_username', form.username.trim())
    else localStorage.removeItem('smart_office_remember_username')
    ElMessage.success(`欢迎，${data.user.name}`)
    emit('success', data.user)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '登录失败，请检查账号和密码')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { min-height:100vh; display:grid; grid-template-columns:minmax(0,1.25fr) minmax(420px,.75fr); background:var(--app-bg); color:var(--text); overflow:hidden; position:relative; }
.login-grid { position:absolute; inset:0; opacity:.24; background-image:linear-gradient(var(--grid-line) 1px,transparent 1px),linear-gradient(90deg,var(--grid-line) 1px,transparent 1px); background-size:42px 42px; mask-image:linear-gradient(90deg,#000,transparent 80%); }
.login-orb { position:absolute; border-radius:999px; filter:blur(55px); opacity:.28; }
.orb-one { width:430px; height:430px; background:#315efb; left:16%; top:13%; }
.orb-two { width:320px; height:320px; background:#7548f8; left:45%; bottom:1%; }
.login-theme-toggle { position:fixed; right:26px; top:24px; z-index:8; height:38px; padding:0 13px; display:flex; align-items:center; gap:8px; border:1px solid var(--border); border-radius:11px; background:var(--surface-glass); color:var(--text-soft); backdrop-filter:blur(16px); cursor:pointer; }
.login-hero { min-height:100vh; padding:42px 7vw; display:flex; flex-direction:column; position:relative; z-index:1; }
.brand-line { display:flex; align-items:center; gap:12px; }
.brand-mark { width:42px; height:42px; display:grid; place-items:center; background:linear-gradient(135deg,#4f7cff,#7c4dff); border-radius:13px; color:white; font-weight:800; box-shadow:0 12px 36px rgba(67,97,238,.35); }
.brand-line strong,.brand-line small { display:block; }
.brand-line strong { color:var(--text); }
.brand-line small { margin-top:3px; color:var(--muted); font-size:11px; }
.hero-copy { margin:auto 0; max-width:760px; }
.eyebrow { display:inline-block; color:#7da0ff; font-size:12px; letter-spacing:2px; margin-bottom:22px; }
.hero-copy h1 { margin:0; color:var(--text); font-size:clamp(54px,6vw,88px); line-height:1.06; letter-spacing:-4px; }
.hero-copy h1 span { background:linear-gradient(90deg,#5f7cff,#9f6dff,#29b8ff); -webkit-background-clip:text; color:transparent; }
.hero-copy>p { max-width:680px; margin:26px 0 38px; color:var(--muted); line-height:1.9; font-size:16px; }
.feature-row { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; max-width:760px; }
.feature-row div { padding:18px; border:1px solid var(--border); border-radius:17px; background:var(--surface-glass); backdrop-filter:blur(16px); }
.feature-row b,.feature-row strong,.feature-row span { display:block; }
.feature-row b { color:var(--primary); font-size:11px; }
.feature-row strong { margin:10px 0 6px; color:var(--text); }
.feature-row span { color:var(--muted); font-size:12px; line-height:1.6; }
.hero-footer { display:flex; gap:30px; color:var(--muted-2); font-size:11px; }
.login-panel { display:grid; place-items:center; padding:46px; position:relative; z-index:2; background:var(--panel-glass); border-left:1px solid var(--border); backdrop-filter:blur(24px); }
.login-card { width:min(100%,430px); padding:38px; border:1px solid var(--border); border-radius:24px; background:var(--surface); box-shadow:var(--shadow-lg); }
.login-heading { color:var(--primary); font-size:12px; letter-spacing:1px; display:flex; align-items:center; gap:8px; }
.status-dot { width:7px; height:7px; border-radius:50%; background:#36d399; box-shadow:0 0 12px #36d399; }
.login-card h2 { margin:26px 0 8px; color:var(--text); font-size:34px; }
.login-subtitle { color:var(--muted); margin:0 0 30px; }
.login-card :deep(.el-input__wrapper) { background:var(--surface-2); border:1px solid var(--border); box-shadow:none; border-radius:12px; padding:4px 14px; }
.login-card :deep(.el-input__inner) { color:var(--text); }
.login-options { display:flex; justify-content:space-between; align-items:center; color:var(--muted); font-size:12px; margin:4px 0 22px; }
.login-button { width:100%; border:0; border-radius:12px; background:linear-gradient(90deg,#4c6fff,#7656ff); font-weight:700; }
.login-demo { margin-top:26px; padding:16px; display:grid; gap:11px; background:var(--surface-2); border:1px solid var(--border-soft); border-radius:14px; }
.login-demo span,.login-demo code { display:block; }
.login-demo span { color:var(--muted); font-size:11px; }
.login-demo code { margin-top:3px; color:var(--primary); font-size:12px; }
@media(max-width:980px){.login-page{grid-template-columns:1fr}.login-hero{min-height:45vh;padding-bottom:24px}.feature-row{display:none}.login-panel{border-left:0;padding-top:16px}.login-theme-toggle{right:14px;top:14px}.hero-copy h1{font-size:50px}.hero-footer{display:none}}
</style>
