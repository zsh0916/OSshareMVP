<template>
  <div class="workbench-page" v-loading="loading">
    <header class="welcome-row">
      <div>
        <span class="welcome-kicker">SMART OFFICE</span>
        <h1>{{ greetingText }}，{{ user?.name || '同事' }} <span>👋</span></h1>
        <p>开启高效的一天，让 AI 协助处理申请、知识检索、会议与数据汇总。</p>
      </div>
      <div class="welcome-meta">
        <strong>{{ todayText }}</strong>
        <span><i></i> 系统在线 · 数据实时更新</span>
      </div>
    </header>

    <section class="feature-grid">
      <article class="media-card">
        <video
          ref="heroVideoRef"
          :key="heroVideoSrc"
          class="theme-hero-video"
          autoplay
          muted
          loop
          playsinline
          preload="auto"
          disablepictureinpicture
          controlslist="nodownload noplaybackrate nofullscreen"
          tabindex="-1"
          aria-hidden="true"
          :poster="heroPosterSrc"
        >
          <source :src="heroVideoSrc" type="video/mp4" />
        </video>

        <div class="hero-video-shade" aria-hidden="true"></div>

        <div class="hero-video-content">
          <span>SMARTOFFICE · 企业智能办公平台</span>
          <h2>让 AI 为您的工作赋能</h2>
          <strong>AAA糖果批发组制作</strong>
          <p>统一连接协同、审批、知识、会议与人才管理</p>
        </div>
      </article>

      <article class="dashboard-card pending-card">
        <div class="card-head">
          <div>
            <span class="section-kicker">TODAY</span>
            <h3>待办事项</h3>
          </div>
          <button type="button" @click="$emit('navigate', 'tasks')">查看全部 {{ stats.total_tasks || 0 }} →</button>
        </div>

        <div v-if="!summary.task_preview?.length" class="compact-empty">
          <b>暂无待办</b>
          <span>新的审批、申请进度和部门消息会显示在这里。</span>
        </div>
        <div v-else class="pending-list">
          <button
            v-for="(item, index) in summary.task_preview.slice(0, 4)"
            :key="item.id"
            type="button"
            @click="openTask(item)"
          >
            <i :class="['pending-dot', `tone-${index % 4}`]"></i>
            <span>
              <strong>{{ item.title }}</strong>
              <small>{{ item.description || item.source }}</small>
            </span>
            <time>{{ formatShortTime(item.created_at) }}</time>
          </button>
        </div>
      </article>
    </section>

    <section class="metrics-grid">
      <button class="metric-card" type="button" @click="$emit('navigate', 'my_applications')">
        <span class="metric-icon purple">OA</span>
        <span><small>我的申请</small><strong>{{ myApplicationCount }}</strong><em>申请记录</em></span>
      </button>
      <button class="metric-card" type="button" @click="$emit('navigate', 'tasks')">
        <span class="metric-icon blue">✓</span>
        <span><small>待办任务</small><strong>{{ stats.total_tasks || 0 }}</strong><em>待处理</em></span>
      </button>
      <button class="metric-card" type="button" @click="$emit('navigate', 'notifications')">
        <span class="metric-icon red">◉</span>
        <span><small>通知消息</small><strong>{{ stats.unread_notifications || 0 }}</strong><em>未读</em></span>
      </button>
      <button class="metric-card" type="button" @click="$emit('navigate', 'my_applications')">
        <span class="metric-icon green">↗</span>
        <span><small>本周完成</small><strong>{{ weekCompleted }}</strong><em>已办结</em></span>
      </button>
      <button class="metric-card" type="button" @click="$emit('navigate', 'tasks')">
        <span class="metric-icon amber">%</span>
        <span><small>效率评分</small><strong>{{ efficiencyDisplay }}</strong><em>{{ completionRate > 0 ? '实时估算' : '暂无数据' }}</em></span>
      </button>
    </section>

    <section class="content-grid">
      <article class="dashboard-card quick-card">
        <div class="card-head">
          <div>
            <span class="section-kicker">QUICK ACCESS</span>
            <h3>快捷入口</h3>
          </div>
          <span class="card-caption">常用功能一键直达</span>
        </div>
        <div class="quick-grid">
          <button type="button" @click="$emit('navigate', 'oa_apply')"><i class="q-green">AI</i><span><strong>智能申请</strong><small>自然语言发起 OA</small></span></button>
          <button type="button" @click="$emit('navigate', 'doc_search')"><i class="q-blue">⌕</i><span><strong>内部文档</strong><small>查询制度与流程</small></span></button>
          <button type="button" @click="$emit('navigate', 'meeting_minutes')"><i class="q-amber">M</i><span><strong>会议纪要</strong><small>音视频转写整理</small></span></button>
          <button type="button" @click="$emit('navigate', 'training_analysis')"><i class="q-purple">Σ</i><span><strong>员工考核</strong><small>评估与培训建议</small></span></button>
          <button type="button" @click="$emit('navigate', 'report_generate')"><i class="q-red">R</i><span><strong>日报报表</strong><small>日报与阶段汇总</small></span></button>
          <button type="button" @click="$emit('navigate', 'notifications')"><i class="q-cyan">◉</i><span><strong>消息中心</strong><small>通知与业务消息</small></span></button>
        </div>
      </article>

      <article class="dashboard-card activity-card">
        <div class="card-head">
          <div>
            <span class="section-kicker">ACTIVITY</span>
            <h3>消息动态</h3>
          </div>
          <div class="activity-tabs">
            <button :class="{ active: activityTab === 'applications' }" type="button" @click="activityTab = 'applications'">申请</button>
            <button :class="{ active: activityTab === 'notifications' }" type="button" @click="activityTab = 'notifications'">通知</button>
          </div>
        </div>

        <div v-if="activityTab === 'applications'" class="activity-list">
          <div v-if="!summary.recent_applications?.length" class="compact-empty small"><span>暂无申请动态</span></div>
          <button
            v-for="item in summary.recent_applications?.slice(0, 4) || []"
            :key="item.id"
            type="button"
            @click="openApplication(item)"
          >
            <span class="activity-avatar">{{ (item.applicant_name || user?.name || '员').slice(-1) }}</span>
            <span><strong>{{ item.application_type_name }}</strong><small>{{ item.summary || `${item.applicant_name || '员工'}提交了申请` }}</small></span>
            <time>{{ formatTime(item.submitted_at || item.created_at) }}</time>
          </button>
        </div>

        <div v-else class="activity-list">
          <div v-if="!summary.recent_notifications?.length" class="compact-empty small"><span>暂无通知动态</span></div>
          <button
            v-for="item in summary.recent_notifications?.slice(0, 4) || []"
            :key="item.id"
            type="button"
            @click="openNotification(item)"
          >
            <span :class="['activity-avatar notice', noticeClass(item.notification_type)]">{{ noticeIcon(item.notification_type) }}</span>
            <span><strong>{{ item.title }}</strong><small>{{ item.content }}</small></span>
            <time>{{ formatTime(item.created_at) }}</time>
          </button>
        </div>
      </article>
    </section>

    <section class="dashboard-card cooperation-section">
      <div class="card-head">
        <div>
          <span class="section-kicker">PARTNERSHIP</span>
          <h3>交流合作动态</h3>
        </div>
        <button class="text-link" type="button" @click="$emit('open-collaboration')">查看全部 →</button>
      </div>

      <div class="cooperation-grid">
        <button
          v-for="item in cooperationUpdates"
          :key="item.id"
          class="cooperation-card"
          type="button"
          @click="$emit('open-collaboration')"
        >
          <span class="company-mark">{{ item.company.slice(0, 1) }}</span>
          <span class="company-copy">
            <span><strong>{{ item.company }}</strong><em>{{ item.tag }}</em></span>
            <b>{{ item.title }}</b>
            <small>{{ item.summary }}</small>
          </span>
          <span class="company-meta"><time>{{ item.date }}</time><i :class="item.tone">{{ item.status }}</i></span>
        </button>
      </div>
      <p class="cooperation-note">当前为界面演示数据，后续可接入真实合作动态接口。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getWorkbenchSummary, markNotificationRead } from '../api/index.js'
import { cooperationUpdates } from '../data/cooperations.js'
import { useTheme } from '../theme.js'

const { isDark } = useTheme()
const heroVideoRef = ref(null)
const heroVideoSrc = computed(() => isDark.value ? '/smartoffice-hero-dark.mp4' : '/smartoffice-hero-light.mp4')
const heroPosterSrc = computed(() => isDark.value ? '/smartoffice-hero-dark-poster.jpg' : '/smartoffice-hero-light-poster.jpg')

watch(heroVideoSrc, async () => {
  await nextTick()
  const video = heroVideoRef.value
  if (!video) return
  video.load()
  video.play().catch(() => {})
})

const props = defineProps({ user: { type: Object, default: null } })
const emit = defineEmits(['navigate', 'data-change', 'open-collaboration'])

const loading = ref(false)
const activityTab = ref('applications')
const summary = ref({
  stats: {},
  task_preview: [],
  notification_summary: {},
  recent_applications: [],
  recent_notifications: []
})
const stats = computed(() => summary.value.stats || {})
const myApplicationCount = computed(() => Number(
  stats.value.my_application_total ??
  stats.value.my_applications ??
  summary.value.recent_applications?.length ??
  0
))
const weekCompleted = computed(() => Number(
  stats.value.completed_this_week ??
  stats.value.week_completed ??
  (summary.value.recent_applications || []).filter(item => item.status === 'approved').length
))
const completionRate = computed(() => {
  const total = Number(stats.value.total_tasks || 0)
  const pending = Number(stats.value.my_pending || 0) + Number(stats.value.department_pending || 0)
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round(((total - Math.min(total, pending)) / total) * 100)))
})
const efficiencyDisplay = computed(() => completionRate.value > 0 ? `${completionRate.value}%` : '--')
const greetingText = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})
const todayText = computed(() => {
  const date = new Date()
  const week = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'][date.getDay()]
  return `${date.getFullYear()}年${String(date.getMonth() + 1).padStart(2, '0')}月${String(date.getDate()).padStart(2, '0')}日 · ${week}`
})

onMounted(loadData)

async function loadData() {
  loading.value = true
  try {
    const response = await getWorkbenchSummary()
    summary.value = response.data
    emit('data-change')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载工作台失败')
  } finally {
    loading.value = false
  }
}

async function openTask(item) {
  try {
    if (item.notification_id) await markNotificationRead(item.notification_id)
    if (item.business_id) sessionStorage.setItem('smart_office_target_business_id', String(item.business_id))
    emit('navigate', item.target_page || 'tasks')
    emit('data-change')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '打开待办失败')
  }
}

function openApplication(item) {
  sessionStorage.setItem('smart_office_target_business_id', String(item.id))
  emit('navigate', 'my_applications')
}

async function openNotification(item) {
  try {
    if (!item.is_read) await markNotificationRead(item.id)
    if (item.business_id) sessionStorage.setItem('smart_office_target_business_id', String(item.business_id))
    emit('navigate', item.target_page || 'notifications')
    emit('data-change')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '打开通知失败')
  }
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(5, 16) : '-'
}

function formatShortTime(value) {
  if (!value) return '--:--'
  const text = String(value).replace('T', ' ')
  return text.length >= 16 ? text.slice(11, 16) : text.slice(5, 10)
}

function noticeIcon(type) {
  if (type === 'oa_approved') return '✓'
  if (type === 'oa_rejected') return '×'
  if (type === 'oa_submitted') return 'OA'
  if (type === 'feishu_department_message') return '部'
  return '知'
}

function noticeClass(type) {
  if (type === 'oa_approved') return 'approved'
  if (type === 'oa_rejected') return 'rejected'
  if (type === 'oa_submitted') return 'submitted'
  if (type === 'feishu_department_message') return 'business'
  return 'system'
}
</script>

<style scoped>
.workbench-page { display:flex; flex-direction:column; gap:16px; max-width:1360px; margin:0 auto; }
.welcome-row { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; padding:4px 2px 2px; }
.welcome-kicker,.section-kicker { color:var(--primary); font-size:10px; font-weight:700; letter-spacing:1.8px; }
.welcome-row h1 { margin:7px 0 5px; color:var(--text); font-size:28px; letter-spacing:-.8px; }
.welcome-row h1 span { font-size:23px; }
.welcome-row p { margin:0; color:var(--muted); font-size:12px; }
.welcome-meta { display:flex; flex-direction:column; align-items:flex-end; gap:7px; color:var(--muted); font-size:11px; }
.welcome-meta strong { color:var(--text-soft); font-weight:600; }
.welcome-meta span { display:flex; align-items:center; gap:6px; }
.welcome-meta i { width:7px; height:7px; border-radius:50%; background:var(--success); box-shadow:0 0 12px color-mix(in srgb,var(--success) 75%,transparent); }
.feature-grid {
  display:grid;
  grid-template-columns:minmax(0,1.65fr) minmax(300px,.82fr);
  align-items:stretch;
  gap:14px;
}
.media-card,.dashboard-card,.metric-card {
  border:1px solid var(--border);
  background:var(--surface);
  box-shadow:var(--shadow-sm);
}
.media-card {
  width:100%;
  min-width:0;
  min-height:246px;
  aspect-ratio:32 / 15;
  position:relative;
  overflow:hidden;
  border-radius:18px;
  background:#071226;
  isolation:isolate;
}
.media-card video {
  position:absolute;
  inset:0;
  z-index:0;
  width:100%;
  height:100%;
  display:block;
  object-fit:cover;
  object-position:center;
  pointer-events:none;
  user-select:none;
  transform:none !important;
}
.hero-video-shade {
  position:absolute;
  inset:0;
  z-index:1;
  pointer-events:none;
  background:
    linear-gradient(90deg,rgba(3,9,25,.84) 0%,rgba(3,9,25,.58) 42%,rgba(3,9,25,.10) 76%),
    linear-gradient(0deg,rgba(3,9,25,.64) 0%,transparent 56%);
}
.hero-video-content {
  position:absolute;
  z-index:2;
  left:clamp(24px,3vw,44px);
  right:clamp(24px,3vw,44px);
  bottom:clamp(22px,2.8vw,36px);
  max-width:min(640px,76%);
  color:#fff;
  text-align:left;
  pointer-events:none;
}
.hero-video-content span {
  display:block;
  color:#c7d7ff;
  font-size:clamp(11px,.92vw,15px);
  font-weight:700;
  letter-spacing:.07em;
  line-height:1.5;
}
.hero-video-content h2 {
  margin:8px 0 3px;
  color:#fff;
  font-size:clamp(27px,2.25vw,43px);
  font-weight:800;
  line-height:1.18;
  letter-spacing:-.02em;
  text-shadow:0 2px 12px rgba(0,0,0,.36);
}
.hero-video-content strong {
  display:block;
  color:#f2f6ff;
  font-size:clamp(14px,1.13vw,20px);
  line-height:1.5;
}
.hero-video-content p {
  margin:5px 0 0;
  color:#cad6eb;
  font-size:clamp(11px,.9vw,15px);
  line-height:1.55;
}
:global(:root[data-theme='light']) .hero-video-shade {
  background:
    linear-gradient(90deg,rgba(7,24,51,.72) 0%,rgba(7,24,51,.44) 42%,rgba(7,24,51,.05) 76%),
    linear-gradient(0deg,rgba(7,24,51,.52) 0%,transparent 57%);
}
.dashboard-card { min-width:0; border-radius:18px; padding:18px; }
.card-head { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:13px; }
.card-head h3 { margin:5px 0 0; color:var(--text); font-size:16px; }
.card-head>button,.text-link { border:0; background:transparent; color:var(--primary); cursor:pointer; font-size:11px; }
.card-caption { color:var(--muted-2); font-size:10px; }
.pending-card { display:flex; flex-direction:column; }
.pending-list { display:flex; flex:1; flex-direction:column; }
.pending-list button { min-height:44px; width:100%; display:grid; grid-template-columns:8px 1fr auto; align-items:center; gap:11px; padding:10px 2px; border:0; border-bottom:1px solid var(--border-soft); background:transparent; color:var(--text); text-align:left; cursor:pointer; }
.pending-list button:hover { background:var(--surface-hover); }
.pending-list span { min-width:0; }
.pending-list strong,.pending-list small { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pending-list strong { color:var(--text-soft); font-size:12px; }
.pending-list small { margin-top:4px; color:var(--muted); font-size:10px; }
.pending-list time { color:var(--muted-2); font-size:10px; }
.pending-dot { width:7px; height:7px; border-radius:50%; background:var(--primary); }
.pending-dot.tone-1{background:#35b9e8}.pending-dot.tone-2{background:#f3a72f}.pending-dot.tone-3{background:#ef5e76}
.compact-empty { min-height:150px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:8px; color:var(--muted); text-align:center; }
.compact-empty b { color:var(--text-soft); }
.compact-empty span { font-size:11px; }
.compact-empty.small { min-height:120px; }
.metrics-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; }
.metric-card { min-height:94px; display:flex; align-items:center; gap:13px; border-radius:16px; padding:15px; text-align:left; color:var(--text); cursor:pointer; transition:.2s; }
.metric-card:hover { transform:translateY(-3px); border-color:color-mix(in srgb,var(--primary) 55%,var(--border)); box-shadow:var(--shadow-md); }
.metric-icon { flex:none; width:38px; height:38px; display:grid; place-items:center; border-radius:11px; font-size:11px; font-weight:800; }
.metric-icon.purple{background:rgba(129,89,255,.13);color:#8a66ff}.metric-icon.blue{background:rgba(73,116,255,.13);color:#5c7eff}.metric-icon.red{background:rgba(239,94,118,.13);color:#ef5e76}.metric-icon.green{background:rgba(28,189,141,.13);color:#1cbd8d}.metric-icon.amber{background:rgba(241,166,48,.13);color:#e9a12d}
.metric-card>span:last-child { min-width:0; }
.metric-card small,.metric-card strong,.metric-card em { display:block; font-style:normal; }
.metric-card small { color:var(--muted); font-size:10px; }
.metric-card strong { margin:3px 0 1px; color:var(--text); font-size:24px; }
.metric-card em { color:var(--muted-2); font-size:9px; }
.content-grid { display:grid; grid-template-columns:minmax(0,1.18fr) minmax(340px,.82fr); gap:14px; }
.quick-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
.quick-grid button { min-height:74px; display:flex; align-items:center; gap:10px; padding:12px; border:1px solid var(--border-soft); border-radius:13px; background:var(--surface-2); color:var(--text); text-align:left; cursor:pointer; transition:.2s; }
.quick-grid button:hover { transform:translateY(-2px); border-color:var(--primary); background:var(--surface-hover); }
.quick-grid i { flex:none; width:34px; height:34px; display:grid; place-items:center; border-radius:10px; font-style:normal; font-size:10px; font-weight:800; }
.q-green{background:rgba(28,189,141,.13);color:#1cbd8d}.q-blue{background:rgba(73,116,255,.13);color:#5c7eff}.q-amber{background:rgba(241,166,48,.13);color:#e9a12d}.q-purple{background:rgba(129,89,255,.13);color:#8a66ff}.q-red{background:rgba(239,94,118,.13);color:#ef5e76}.q-cyan{background:rgba(42,183,221,.13);color:#2ab7dd}
.quick-grid strong,.quick-grid small { display:block; }
.quick-grid strong { color:var(--text); font-size:12px; }
.quick-grid small { margin-top:4px; color:var(--muted); font-size:9px; }
.activity-tabs { display:flex; gap:4px; padding:3px; border:1px solid var(--border-soft); border-radius:9px; background:var(--surface-2); }
.activity-tabs button { height:25px; padding:0 9px; border:0; border-radius:7px; background:transparent; color:var(--muted); cursor:pointer; font-size:9px; }
.activity-tabs button.active { background:var(--surface); color:var(--primary); box-shadow:var(--shadow-sm); }
.activity-list { display:flex; flex-direction:column; }
.activity-list>button { width:100%; display:grid; grid-template-columns:34px 1fr auto; align-items:center; gap:10px; padding:10px 0; border:0; border-bottom:1px solid var(--border-soft); background:transparent; color:var(--text); text-align:left; cursor:pointer; }
.activity-list>button:hover { background:var(--surface-hover); }
.activity-avatar { width:31px; height:31px; display:grid; place-items:center; border-radius:50%; background:linear-gradient(135deg,var(--primary),#835dff); color:white; font-size:10px; font-weight:800; }
.activity-avatar.notice { border-radius:10px; background:var(--primary-soft); color:var(--primary); }
.activity-avatar.approved{background:rgba(28,189,141,.13);color:#1cbd8d}.activity-avatar.rejected{background:rgba(239,94,118,.13);color:#ef5e76}.activity-avatar.business{background:rgba(42,183,221,.13);color:#2ab7dd}
.activity-list strong,.activity-list small { display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.activity-list strong { color:var(--text); font-size:11px; }
.activity-list small { margin-top:4px; max-width:330px; color:var(--muted); font-size:9px; }
.activity-list time { color:var(--muted-2); font-size:9px; }
.cooperation-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.cooperation-card { min-width:0; display:grid; grid-template-columns:40px 1fr auto; align-items:start; gap:11px; padding:14px; border:1px solid var(--border-soft); border-radius:14px; background:var(--surface-2); color:var(--text); text-align:left; cursor:pointer; transition:.2s; }
.cooperation-card:hover { transform:translateY(-2px); border-color:var(--primary); background:var(--surface-hover); }
.company-mark { width:38px; height:38px; display:grid; place-items:center; border-radius:11px; background:linear-gradient(135deg,var(--primary),#8a62ff); color:white; font-weight:800; }
.company-copy { min-width:0; }
.company-copy>span { display:flex; align-items:center; gap:7px; min-width:0; }
.company-copy strong { min-width:0; color:var(--text); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.company-copy em { flex:none; padding:2px 6px; border-radius:999px; background:var(--primary-soft); color:var(--primary); font-style:normal; font-size:8px; }
.company-copy b { display:block; margin:6px 0 4px; color:var(--text-soft); font-size:11px; }
.company-copy small { display:-webkit-box; overflow:hidden; color:var(--muted); font-size:9px; line-height:1.45; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.company-meta { display:flex; flex-direction:column; align-items:flex-end; gap:8px; color:var(--muted-2); font-size:8px; }
.company-meta i { padding:3px 6px; border-radius:999px; background:var(--primary-soft); color:var(--primary); font-style:normal; white-space:nowrap; }
.company-meta i.success{background:rgba(28,189,141,.13);color:#1cbd8d}.company-meta i.warning{background:rgba(241,166,48,.13);color:#e9a12d}
.cooperation-note { margin:10px 0 0; color:var(--muted-2); font-size:9px; }
@media(max-width:1180px){.feature-grid,.content-grid{grid-template-columns:1fr}.metrics-grid{grid-template-columns:repeat(3,1fr)}.cooperation-grid{grid-template-columns:1fr}.quick-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.welcome-row{align-items:flex-start;flex-direction:column}.welcome-meta{align-items:flex-start}.media-card{min-height:0;aspect-ratio:32 / 15}.metrics-grid{grid-template-columns:1fr 1fr}.quick-grid{grid-template-columns:1fr 1fr}.cooperation-card{grid-template-columns:38px 1fr}.company-meta{grid-column:2;flex-direction:row;align-items:center}.welcome-row h1{font-size:24px}}

@media(max-width:560px){
  .media-card{min-height:220px;aspect-ratio:16 / 9}
  .hero-video-content{left:20px;right:20px;bottom:18px;max-width:90%}
  .hero-video-content p{display:none}
}

/* 欢迎视频文字最终隔离：避免全局 main-content 标题/段落主题规则覆盖 */
.hero-video-content,
.hero-video-content * {
  opacity: 1 !important;
  filter: none !important;
  mix-blend-mode: normal !important;
}
.hero-video-content span {
  color: #dbe7ff !important;
  -webkit-text-fill-color: #dbe7ff !important;
  text-shadow: 0 2px 10px rgba(0, 0, 0, .58) !important;
}
.hero-video-content h2 {
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
  text-shadow: 0 3px 16px rgba(0, 0, 0, .68) !important;
}
.hero-video-content strong {
  color: #f5f7ff !important;
  -webkit-text-fill-color: #f5f7ff !important;
  text-shadow: 0 2px 12px rgba(0, 0, 0, .62) !important;
}
.hero-video-content p {
  color: #d5dfef !important;
  -webkit-text-fill-color: #d5dfef !important;
  text-shadow: 0 2px 10px rgba(0, 0, 0, .62) !important;
}

</style>
