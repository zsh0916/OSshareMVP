<template>
  <div class="notification-page">
    <section class="notification-hero">
      <div>
        <span class="page-kicker">NOTIFICATION CENTER</span>
        <h2>通知中心</h2>
        <p>OA、部门业务消息和系统提醒按类别集中展示。</p>
      </div>
      <div class="hero-actions">
        <el-switch v-model="unreadOnly" active-text="仅看未读" @change="handleFilterChange" />
        <el-button :disabled="!unreadCount" @click="readAll">全部已读</el-button>
        <el-button type="primary" :loading="loading" @click="loadData">刷新</el-button>
      </div>
    </section>

    <section class="category-grid">
      <button
        v-for="item in categories"
        :key="item.key"
        :class="['category-card', { active: category === item.key }]"
        @click="selectCategory(item.key)"
      >
        <span>{{ item.label }}</span>
        <strong>{{ categoryCounts[item.key] || 0 }}</strong>
        <small>{{ item.description }}</small>
      </button>
    </section>

    <section class="notification-panel">
      <div class="notification-toolbar">
        <div>
          <h3>{{ currentCategory.label }}</h3>
          <span>共 {{ total }} 条，未读 {{ unreadCount }} 条</span>
        </div>
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索通知标题或内容"
          class="notification-search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
      </div>

      <div v-loading="loading" class="notification-list">
        <div v-if="!items.length && !loading" class="empty-state">
          <strong>当前没有通知</strong>
          <span>新的审批结果、部门消息或系统提醒会显示在这里。</span>
        </div>

        <article
          v-for="item in items"
          :key="item.id"
          :class="['notification-item', noticeClass(item.notification_type), { unread: !item.is_read }]"
          @click="openItem(item)"
        >
          <div class="notice-symbol">{{ icon(item.notification_type) }}</div>
          <div class="notice-main">
            <div class="notice-title">
              <strong>{{ item.title }}</strong>
              <span class="type-tag">{{ typeName(item.notification_type) }}</span>
              <span v-if="!item.is_read" class="unread-tag">未读</span>
            </div>
            <p>{{ item.content }}</p>
            <small>{{ formatTime(item.created_at) }}</small>
          </div>
          <button @click.stop="openItem(item)">查看 →</button>
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
import { getNotifications, markAllNotificationsRead, markNotificationRead } from '../api/index.js'

const emit = defineEmits(['navigate', 'unread-change', 'data-change'])

const loading = ref(false)
const items = ref([])
const total = ref(0)
const unreadCount = ref(0)
const categoryCounts = ref({ all: 0, oa: 0, business: 0, system: 0, unread: 0 })
const category = ref('all')
const keyword = ref('')
const page = ref(1)
const pageSize = 20
const unreadOnly = ref(false)
let refreshTimer = null

const categories = [
  { key: 'all', label: '全部通知', description: '所有通知记录' },
  { key: 'oa', label: 'OA 通知', description: '提交、通过和驳回结果' },
  { key: 'business', label: '部门消息', description: '按部门定向推送的业务内容' },
  { key: 'system', label: '系统通知', description: '账号和平台运行提醒' }
]

const currentCategory = computed(
  () => categories.find(item => item.key === category.value) || categories[0]
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

function handleFilterChange() {
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
    const response = await getNotifications({
      page: page.value,
      page_size: pageSize,
      unread_only: unreadOnly.value ? 1 : 0,
      category: category.value,
      keyword: keyword.value.trim()
    })
    items.value = response.data.items || []
    total.value = response.data.total || 0
    unreadCount.value = response.data.unread_count || 0
    categoryCounts.value = { ...categoryCounts.value, ...(response.data.category_counts || {}) }
    emit('unread-change', unreadCount.value)
  } catch (error) {
    if (showLoading) ElMessage.error(error.response?.data?.detail || '加载通知失败')
  } finally {
    if (showLoading) loading.value = false
  }
}

async function readAll() {
  try {
    await markAllNotificationsRead()
    ElMessage.success('全部通知已标记为已读')
    await loadData()
    emit('data-change')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '操作失败')
  }
}

async function openItem(item) {
  try {
    if (!item.is_read) {
      await markNotificationRead(item.id)
      item.is_read = 1
      unreadCount.value = Math.max(0, unreadCount.value - 1)
      categoryCounts.value.unread = unreadCount.value
      emit('unread-change', unreadCount.value)
      emit('data-change')
    }
    if (item.business_id) {
      sessionStorage.setItem('smart_office_target_business_id', String(item.business_id))
    }
    const targetPage =
      item.notification_type === 'feishu_department_message' ||
      item.target_page === 'message_center'
        ? 'messages'
        : (item.target_page || 'notifications')

    emit('navigate', targetPage, item.business_id || null)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '打开通知失败')
  }
}

function icon(type) {
  if (type === 'oa_approved') return '✓'
  if (type === 'oa_rejected') return '×'
  if (type === 'oa_submitted') return 'OA'
  if (type === 'feishu_department_message') return '部'
  return '知'
}

function typeName(type) {
  if (type === 'oa_approved') return '审批通过'
  if (type === 'oa_rejected') return '审批驳回'
  if (type === 'oa_submitted') return '待审批'
  if (type === 'feishu_department_message') return '部门消息'
  return '系统通知'
}

function noticeClass(type) {
  if (type === 'oa_approved') return 'approved'
  if (type === 'oa_rejected') return 'rejected'
  if (type === 'oa_submitted') return 'submitted'
  if (type === 'feishu_department_message') return 'business'
  return 'system'
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}
</script>

<style scoped>
.notification-page { display:flex; flex-direction:column; gap:18px; }
.notification-hero { display:flex; justify-content:space-between; align-items:flex-end; padding:26px 30px; border:1px solid #202638; border-radius:22px; background:radial-gradient(circle at 82% 15%,rgba(74,105,255,.15),transparent 30%),#10131d; }
.page-kicker { color:#6f8dff; font-size:11px; letter-spacing:2px; }
.notification-hero h2 { margin:8px 0 6px; color:#f8fafc; font-size:30px; }
.notification-hero p { margin:0; color:#758095; }
.hero-actions { display:flex; gap:10px; align-items:center; }
.category-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.category-card { text-align:left; border:1px solid #202638; background:#10131d; border-radius:17px; padding:18px; cursor:pointer; color:inherit; transition:.2s; }
.category-card:hover,.category-card.active { transform:translateY(-2px); border-color:#536eff; background:#13192a; }
.category-card span,.category-card small { display:block; color:#768196; }
.category-card strong { display:block; color:#f8fafc; font-size:28px; margin:10px 0 7px; }
.category-card small { font-size:11px; }
.notification-panel { border:1px solid #202638; background:#10131d; border-radius:20px; padding:20px 24px; min-height:480px; }
.notification-toolbar { display:flex; justify-content:space-between; align-items:center; padding-bottom:18px; border-bottom:1px solid #202638; }
.notification-toolbar h3 { color:#f2f5fa; margin:0 0 5px; }
.notification-toolbar span { color:#697488; font-size:12px; }
.notification-search { width:320px; }
.notification-list { min-height:360px; }
.notification-item { display:grid; grid-template-columns:48px 1fr auto; gap:14px; align-items:center; padding:19px 6px; border-bottom:1px solid #1d2230; cursor:pointer; transition:.2s; }
.notification-item:hover { transform:translateX(4px); background:linear-gradient(90deg,rgba(76,111,255,.06),transparent); }
.notification-item.unread { border-left:2px solid #5f7cff; padding-left:12px; }
.notice-symbol { width:42px; height:42px; display:grid; place-items:center; border-radius:13px; background:#1d2747; color:#7fa0ff; font-weight:800; }
.notification-item.approved .notice-symbol { background:rgba(29,190,138,.13); color:#4bd8aa; }
.notification-item.rejected .notice-symbol { background:rgba(239,90,111,.13); color:#ff8293; }
.notification-item.submitted .notice-symbol { background:rgba(240,161,28,.13); color:#f3b64c; }
.notification-item.business .notice-symbol { background:rgba(43,180,223,.13); color:#63caeb; }
.notice-title { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.notice-title strong { color:#e2e7ef; }
.type-tag,.unread-tag { border-radius:999px; padding:3px 8px; font-size:10px; }
.type-tag { background:#242a38; color:#9ca7b9; }
.unread-tag { background:rgba(79,111,255,.14); color:#85a0ff; }
.notice-main p { margin:6px 0 8px; color:#788397; font-size:13px; }
.notice-main small { color:#535d70; }
.notification-item>button { border:0; background:none; color:#7d98ff; cursor:pointer; white-space:nowrap; }
.empty-state { min-height:330px; display:flex; flex-direction:column; justify-content:center; align-items:center; color:#667186; }
.empty-state strong { color:#9ba6b8; margin-bottom:8px; }
.pagination-row { display:flex; justify-content:center; padding-top:20px; }
@media(max-width:1000px) {
  .category-grid { grid-template-columns:repeat(2,1fr); }
}
@media(max-width:760px) {
  .notification-hero,.notification-toolbar { flex-direction:column; align-items:flex-start; gap:14px; }
  .hero-actions { flex-wrap:wrap; }
  .category-grid { grid-template-columns:1fr; }
  .notification-search { width:100%; }
  .notification-item { grid-template-columns:44px 1fr; }
  .notification-item>button { grid-column:2; text-align:left; padding:0; }
}
</style>
