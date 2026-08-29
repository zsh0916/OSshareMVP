<template>
  <div class="task-page">
    <section class="task-hero">
      <div>
        <span class="page-kicker">UNIFIED TASK CENTER</span>
        <h2>待办中心</h2>
        <p>审批任务、申请进度、部门业务消息和未读提醒统一显示在这里。</p>
      </div>
      <button class="refresh-button" :disabled="loading" @click="loadData">刷新待办</button>
    </section>

    <section class="task-stats">
      <button
        v-for="item in categoryOptions"
        :key="item.key"
        :class="['stat-card', { active: category === item.key }]"
        @click="selectCategory(item.key)"
      >
        <span>{{ item.label }}</span>
        <strong>{{ counts[item.key] || 0 }}</strong>
        <small>{{ item.description }}</small>
      </button>
    </section>

    <section class="task-panel">
      <div class="task-toolbar">
        <div>
          <h3>{{ currentCategory.label }}</h3>
          <span>共 {{ total }} 项</span>
        </div>
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索申请人、事项或消息内容"
          class="task-search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
      </div>

      <div v-loading="loading" class="task-list">
        <div v-if="!items.length && !loading" class="empty-state">
          <strong>当前没有待办事项</strong>
          <span>新的审批、业务消息或结果通知会自动出现在这里。</span>
        </div>

        <article
          v-for="item in items"
          :key="item.id"
          :class="['task-item', item.priority, item.category]"
          @click="openTask(item)"
        >
          <div class="task-icon">{{ taskIcon(item) }}</div>
          <div class="task-main">
            <div class="task-title-row">
              <strong>{{ item.title }}</strong>
              <span :class="['priority-tag', item.priority]">{{ priorityName(item.priority) }}</span>
            </div>
            <p>{{ item.description }}</p>
            <div class="task-meta">
              <span>{{ item.source }}</span>
              <span>{{ formatTime(item.created_at) }}</span>
              <span>{{ statusName(item.status) }}</span>
            </div>
          </div>
          <button class="task-action" @click.stop="openTask(item)">{{ item.action_label || '查看' }} →</button>
        </article>
      </div>

      <div v-if="total > pageSize" class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadData"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getTasks, markNotificationRead } from '../api/index.js'

const emit = defineEmits(['navigate', 'counts-change', 'data-change'])

const loading = ref(false)
const items = ref([])
const total = ref(0)
const counts = ref({
  all: 0,
  approval: 0,
  application: 0,
  department_message: 0,
  notification: 0,
  high_priority: 0
})
const category = ref('all')
const keyword = ref('')
const page = ref(1)
const pageSize = 20
let refreshTimer = null

const categoryOptions = [
  { key: 'all', label: '全部待办', description: '所有需要关注的事项' },
  { key: 'approval', label: '待我审批', description: '本部门待审批 OA' },
  { key: 'application', label: '申请进度', description: '本人正在审批中的申请' },
  { key: 'department_message', label: '部门消息', description: '按部门分发的业务消息' },
  { key: 'notification', label: '结果与提醒', description: '审批结果和系统通知' }
]

const currentCategory = computed(
  () => categoryOptions.find(item => item.key === category.value) || categoryOptions[0]
)

onMounted(async () => {
  await loadData()
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') loadData(false)
  }, 30000)
  window.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  window.removeEventListener('visibilitychange', handleVisibilityChange)
})

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') loadData(false)
}

function selectCategory(value) {
  category.value = value
  page.value = 1
  loadData()
}

function handleSearch() {
  page.value = 1
  loadData()
}

async function loadData(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const response = await getTasks({
      page: page.value,
      page_size: pageSize,
      category: category.value,
      keyword: keyword.value.trim()
    })
    items.value = response.data.items || []
    total.value = response.data.total || 0
    counts.value = { ...counts.value, ...(response.data.counts || {}) }
    emit('counts-change', counts.value.all || 0)
  } catch (error) {
    if (showLoading) {
      ElMessage.error(error.response?.data?.detail || '加载待办失败')
    }
  } finally {
    if (showLoading) loading.value = false
  }
}

async function openTask(item) {
  try {
    if (item.notification_id) {
      await markNotificationRead(item.notification_id)
    }
    if (item.business_id) {
      sessionStorage.setItem('smart_office_target_business_id', String(item.business_id))
    }
    emit('navigate', item.target_page || 'tasks', item.business_id || null)
    emit('data-change')
    if (item.notification_id) await loadData(false)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '打开待办失败')
  }
}

function taskIcon(item) {
  if (item.category === 'approval') return '审'
  if (item.category === 'application') return '申'
  if (item.category === 'department_message') return '部'
  if (item.title?.includes('通过')) return '✓'
  if (item.title?.includes('驳回')) return '×'
  return '知'
}

function priorityName(value) {
  return { high: '优先处理', normal: '普通', low: '低' }[value] || '普通'
}

function statusName(value) {
  return { pending: '待处理', waiting: '审批中', unread: '未读' }[value] || value
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}
</script>

<style scoped>
.task-page { display:flex; flex-direction:column; gap:18px; }
.task-hero { display:flex; justify-content:space-between; align-items:flex-end; padding:26px 30px; border:1px solid #202638; border-radius:22px; background:radial-gradient(circle at 80% 20%,rgba(76,106,255,.16),transparent 30%),#10131d; }
.page-kicker { color:#7390ff; font-size:11px; letter-spacing:2px; }
.task-hero h2 { margin:8px 0 6px; color:#f8fafc; font-size:30px; }
.task-hero p { margin:0; color:#768196; }
.refresh-button { border:1px solid #32416f; background:#17203a; color:#9db2ff; border-radius:11px; padding:10px 17px; cursor:pointer; }
.task-stats { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; }
.stat-card { text-align:left; border:1px solid #202638; background:#10131d; border-radius:17px; padding:18px; cursor:pointer; transition:.2s; color:inherit; }
.stat-card:hover,.stat-card.active { border-color:#536eff; transform:translateY(-2px); background:#13192a; }
.stat-card span,.stat-card small { display:block; color:#758095; }
.stat-card strong { display:block; margin:10px 0 7px; font-size:28px; color:#f7f9fc; }
.stat-card small { font-size:11px; }
.task-panel { border:1px solid #202638; background:#10131d; border-radius:20px; padding:20px 24px; min-height:480px; }
.task-toolbar { display:flex; justify-content:space-between; align-items:center; padding-bottom:18px; border-bottom:1px solid #202638; }
.task-toolbar h3 { color:#f2f5fa; margin:0 0 5px; }
.task-toolbar span { color:#697488; font-size:12px; }
.task-search { width:320px; }
.task-list { min-height:360px; }
.task-item { display:grid; grid-template-columns:48px 1fr auto; align-items:center; gap:15px; padding:18px 6px; border-bottom:1px solid #1e2432; cursor:pointer; transition:.2s; }
.task-item:hover { transform:translateX(4px); background:linear-gradient(90deg,rgba(73,103,255,.06),transparent); }
.task-item.high { border-left:2px solid #ef6074; padding-left:12px; }
.task-icon { width:42px; height:42px; display:grid; place-items:center; border-radius:13px; background:#1f2947; color:#8aa5ff; font-weight:800; }
.task-item.approval .task-icon { background:rgba(240,161,28,.13); color:#f1b14a; }
.task-item.department_message .task-icon { background:rgba(45,180,224,.13); color:#62c9ec; }
.task-item.application .task-icon { background:rgba(140,92,255,.13); color:#aa8cff; }
.task-title-row { display:flex; align-items:center; gap:10px; }
.task-main strong { color:#e5eaf2; }
.task-main p { margin:6px 0 9px; color:#788397; font-size:13px; }
.task-meta { display:flex; flex-wrap:wrap; gap:12px; color:#576174; font-size:11px; }
.priority-tag { border-radius:999px; padding:3px 8px; font-size:10px; background:#262c3b; color:#aab4c5; }
.priority-tag.high { background:rgba(239,90,111,.13); color:#ff8192; }
.task-action { border:0; background:none; color:#7d98ff; cursor:pointer; white-space:nowrap; }
.empty-state { min-height:330px; display:flex; flex-direction:column; justify-content:center; align-items:center; color:#667186; }
.empty-state strong { color:#9ba6b8; margin-bottom:8px; }
.pagination-row { display:flex; justify-content:center; padding-top:20px; }
@media(max-width:1100px) {
  .task-stats { grid-template-columns:repeat(2,1fr); }
}
@media(max-width:760px) {
  .task-hero,.task-toolbar { align-items:flex-start; flex-direction:column; gap:14px; }
  .task-stats { grid-template-columns:1fr; }
  .task-search { width:100%; }
  .task-item { grid-template-columns:44px 1fr; }
  .task-action { grid-column:2; text-align:left; padding:0; }
}
</style>
