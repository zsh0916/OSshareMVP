<template>
  <div v-if="!authState.ready" class="app-loading">
    <div class="loading-logo">S</div>
    <span>SmartOffice 正在加载...</span>
  </div>

  <LoginPage v-else-if="!currentUser" @success="handleLoginSuccess" />

  <div v-else :class="['enterprise-app', { 'sidebar-collapsed': sidebarCollapsed }]">
    <header class="topbar">
      <div class="topbar-brand-block">
        <button class="brand" type="button" @click="navigate('workbench')">
          <span class="brand-icon">S</span>
          <span class="brand-copy">
            <strong>SmartOffice</strong>
            <small>企业智能办公协同平台</small>
          </span>
        </button>
        <button
          v-if="!currentUser.must_change_password"
          class="sidebar-toggle"
          type="button"
          :title="sidebarCollapsed ? '展开菜单' : '收起菜单'"
          @click="toggleSidebar"
        >
          {{ sidebarCollapsed ? '»' : '«' }}
        </button>
      </div>

      <div v-if="!currentUser.must_change_password" class="header-center">
        <div class="theme-segment" aria-label="主题切换">
          <button :class="{ active: isDark }" type="button" @click="setTheme('dark')">
            <span class="theme-dot dark"></span>暗色主题
          </button>
          <button :class="{ active: !isDark }" type="button" @click="setTheme('light')">
            <span class="theme-dot light"></span>白色主题
          </button>
        </div>

        <nav class="capability-nav" aria-label="平台能力">
          <button :class="{ active: hubOpen && hubActive === 'tasks' }" @click="openHub('tasks')">
            <span>⌘</span>智能协同
          </button>
          <button :class="{ active: hubOpen && hubActive === 'notifications' }" @click="openHub('notifications')">
            <span>▣</span>消息聚合
          </button>
          <button :class="{ active: activeSection === 'ai' }" @click="navigate('doc_search')">
            <span>✦</span>AI 助手
          </button>
          <button v-if="hasPermission('message.view')" :class="{ active: activeMenu === 'message_dashboard' }" @click="navigate('message_dashboard')">
            <span>↗</span>数据可视化
          </button>
          <button :class="{ active: activeSection === 'oa' }" @click="navigate('oa_apply')">
            <span>◈</span>流程自动化
          </button>
          <button :class="{ active: activeMenu === 'profile' || activeMenu === 'users' }" @click="navigate(hasPermission('user.manage') ? 'users' : 'profile')">
            <span>♢</span>安全权限
          </button>
        </nav>
      </div>
      <div v-else class="security-only-nav">首次登录安全设置</div>

      <div class="top-actions">
        <div v-if="!currentUser.must_change_password" class="global-search">
          <span>⌕</span>
          <input v-model="searchText" placeholder="搜索功能、申请或智能工具" @keyup.enter="handleSearch" />
          <kbd>Enter</kbd>
        </div>

        <button v-if="!currentUser.must_change_password" class="icon-action" type="button" title="协同中心" @click="openHub('tasks')">
          <span>✦</span>
          <i v-if="taskCount + unreadCount">{{ Math.min(99, taskCount + unreadCount) }}</i>
        </button>
        <button v-if="!currentUser.must_change_password" class="icon-action" type="button" title="通知中心" @click="openHub('notifications')">
          <span>◉</span>
          <i v-if="unreadCount">{{ unreadCount > 99 ? '99+' : unreadCount }}</i>
        </button>
        <button class="icon-action fullscreen-action" type="button" title="全屏显示" @click="toggleFullscreen">⛶</button>

        <el-dropdown trigger="click" @command="handleUserCommand">
          <button class="user-chip">
            <span class="user-avatar">{{ currentUser.name?.slice(-1) }}</span>
            <span class="user-text">
              <strong>{{ currentUser.name }}</strong>
              <small>{{ currentUser.position || currentUser.department_name || currentUser.role_name }}</small>
            </span>
            <span class="chevron">⌄</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人中心</el-dropdown-item>
              <el-dropdown-item command="tasks">待办中心</el-dropdown-item>
              <el-dropdown-item command="notifications">通知中心</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="app-body">
      <aside class="sidebar">
        <div class="sidebar-overview">
          <span class="sidebar-overview-icon">S</span>
          <div>
            <strong>SmartOffice</strong>
            <small>智能工作空间</small>
          </div>
        </div>

        <div v-for="group in visibleMenuGroups" :key="group.key" class="menu-group">
          <div class="menu-label">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.key"
            :class="['menu-item', { active: activeMenu === item.key }]"
            :title="sidebarCollapsed ? item.label : ''"
            @click="navigate(item.key)"
          >
            <span class="menu-icon">{{ item.icon }}</span>
            <span class="menu-text">{{ item.label }}</span>
            <i v-if="item.key === 'tasks' && taskCount">{{ taskCount }}</i>
            <i v-else-if="item.key === 'notifications' && unreadCount">{{ unreadCount }}</i>
          </button>
        </div>

        <div class="sidebar-footer">
          <span>当前身份</span>
          <strong>{{ currentUser.role_name }}</strong>
          <small>{{ currentUser.employee_id || currentUser.username }}</small>
        </div>
      </aside>

      <main class="main-content">
        <Transition name="page-fade" mode="out-in">
          <div :key="activeMenu" class="page-frame">
            <WorkbenchHome
              v-if="activeMenu === 'workbench'"
              :key="pageRefreshKey"
              :user="currentUser"
              @navigate="navigate"
              @data-change="refreshUnread"
              @open-collaboration="openHub('cooperation')"
            />
            <TaskCenter
              v-else-if="activeMenu === 'tasks'"
              @navigate="handleNotificationNavigate"
              @counts-change="taskCount = $event"
              @data-change="refreshUnread"
            />
            <OaApplyCenter v-else-if="activeMenu === 'oa_apply'" :current-user="currentUser" />
            <MyApplications v-else-if="activeMenu === 'my_applications'" @navigate="navigate" />
            <ApprovalCenter v-else-if="activeMenu === 'approval_center'" :user="currentUser" />
            <NotificationCenter
              v-else-if="activeMenu === 'notifications'"
              @navigate="handleNotificationNavigate"
              @unread-change="unreadCount = $event"
              @data-change="refreshUnread"
            />
            <ProfileCenter
              v-else-if="activeMenu === 'profile'"
              :user="currentUser"
              @password-changed="handlePasswordChanged"
            />
            <UserManagement v-else-if="activeMenu === 'users'" />
            <MessageCenter
              v-else-if="activeMenu === 'messages'"
              :messages="messages"
              :can-manage="hasPermission('message.view')"
              @refresh="loadAdminData"
            />
            <Dashboard v-else-if="activeMenu === 'message_dashboard'" :summary="legacySummary" />
            <WorkflowManage v-else-if="activeMenu === 'workflows'" />
            <RuleConfig v-else-if="activeMenu === 'rules'" />
            <DocumentSearch v-else-if="activeMenu === 'doc_search'" />
            <MeetingMinutes v-else-if="activeMenu === 'meeting_minutes'" />
            <EmployeeAssessment v-else-if="activeMenu === 'quiz_generate'" :current-user="currentUser" />
            <AssessmentAnalysis v-else-if="activeMenu === 'training_analysis'" :current-user="currentUser" />
            <ReportAssistant v-else-if="activeMenu === 'report_generate'" :current-user="currentUser" />
            <Placeholder v-else :title="currentPage.title" :description="currentPage.description" />
          </div>
        </Transition>
      </main>
    </div>

    <el-drawer
      v-model="hubOpen"
      class="smart-hub-drawer"
      direction="rtl"
      size="430px"
      :with-header="false"
      append-to-body
    >
      <div class="hub-shell" v-loading="hubLoading">
        <header class="hub-header">
          <div>
            <span>SMART COLLABORATION</span>
            <h2>协同中心</h2>
            <p>待办、通知与对外合作动态统一汇合。</p>
          </div>
          <button type="button" @click="hubOpen = false">×</button>
        </header>

        <div class="hub-tabs">
          <button :class="{ active: hubActive === 'tasks' }" @click="hubActive = 'tasks'">
            待办 <i>{{ taskCount }}</i>
          </button>
          <button :class="{ active: hubActive === 'notifications' }" @click="hubActive = 'notifications'">
            通知 <i>{{ unreadCount }}</i>
          </button>
          <button :class="{ active: hubActive === 'cooperation' }" @click="hubActive = 'cooperation'">合作动态</button>
        </div>

        <section v-if="hubActive === 'tasks'" class="hub-list">
          <button v-for="item in hubTasks" :key="item.id" class="hub-item" @click="openHubItem(item.target_page || 'tasks', item.business_id)">
            <span class="hub-symbol">{{ hubTaskIcon(item) }}</span>
            <span><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
            <time>{{ formatHubTime(item.created_at) }}</time>
          </button>
          <div v-if="!hubTasks.length" class="hub-empty">当前没有待处理事项</div>
          <button class="hub-more" @click="openHubItem('tasks')">进入待办中心 →</button>
        </section>

        <section v-else-if="hubActive === 'notifications'" class="hub-list">
          <button v-for="item in hubNotifications" :key="item.id" class="hub-item" @click="openHubItem(item.target_page || 'notifications', item.business_id)">
            <span class="hub-symbol notice">{{ hubNoticeIcon(item.notification_type) }}</span>
            <span><strong>{{ item.title }}</strong><small>{{ item.content }}</small></span>
            <time>{{ formatHubTime(item.created_at) }}</time>
          </button>
          <div v-if="!hubNotifications.length" class="hub-empty">当前没有新通知</div>
          <button class="hub-more" @click="openHubItem('notifications')">进入通知中心 →</button>
        </section>

        <section v-else class="hub-cooperations">
          <article v-for="item in cooperationUpdates" :key="item.id" class="hub-cooperation-card">
            <div class="cooperation-card-head">
              <span>{{ item.tag }}</span>
              <time>{{ item.date }}</time>
            </div>
            <h3>{{ item.company }}</h3>
            <strong>{{ item.title }}</strong>
            <p>{{ item.summary }}</p>
            <footer><i :class="item.tone"></i>{{ item.status }}<small v-if="item.demo">演示数据</small></footer>
          </article>
        </section>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import LoginPage from './components/LoginPage.vue'
// Feature pages are loaded on demand. Adding a future module only requires a
// component registration and menu descriptor, without increasing the login bundle.
const WorkbenchHome = defineAsyncComponent(() => import('./components/WorkbenchHome.vue'))
const TaskCenter = defineAsyncComponent(() => import('./components/TaskCenter.vue'))
const NotificationCenter = defineAsyncComponent(() => import('./components/NotificationCenter.vue'))
const MyApplications = defineAsyncComponent(() => import('./components/MyApplications.vue'))
const ApprovalCenter = defineAsyncComponent(() => import('./components/ApprovalCenter.vue'))
const UserManagement = defineAsyncComponent(() => import('./components/UserManagement.vue'))
const ProfileCenter = defineAsyncComponent(() => import('./components/ProfileCenter.vue'))
const OaApplyCenter = defineAsyncComponent(() => import('./components/OaApplyCenter.vue'))
const DocumentSearch = defineAsyncComponent(() => import('./components/DocumentSearch.vue'))
const MeetingMinutes = defineAsyncComponent(() => import('./components/MeetingMinutes.vue'))
const EmployeeAssessment = defineAsyncComponent(() => import('./components/EmployeeAssessment.vue'))
const AssessmentAnalysis = defineAsyncComponent(() => import('./components/AssessmentAnalysis.vue'))
const ReportAssistant = defineAsyncComponent(() => import('./components/ReportAssistant.vue'))
const Dashboard = defineAsyncComponent(() => import('./components/Dashboard.vue'))
const MessageCenter = defineAsyncComponent(() => import('./components/MessageCenter.vue'))
const WorkflowManage = defineAsyncComponent(() => import('./components/WorkflowManage.vue'))
const RuleConfig = defineAsyncComponent(() => import('./components/RuleConfig.vue'))
const Placeholder = defineAsyncComponent(() => import('./components/Placeholder.vue'))
import { authState, hasPermission, logout, restoreSession } from './auth.js'
import { getDashboardSummary, getMessages, getNotifications, getTasks, getTaskSummary } from './api/index.js'
import { cooperationUpdates } from './data/cooperations.js'
import { useTheme } from './theme.js'

const { isDark, initTheme, setTheme } = useTheme()
initTheme()

const activeMenu = ref(authState.user?.must_change_password ? 'profile' : 'workbench')
const searchText = ref('')
const unreadCount = ref(0)
const taskCount = ref(0)
const pageRefreshKey = ref(0)
const messages = ref([])
const legacySummary = ref({ total: 0, p0: 0, p1: 0, handled: 0, wrong_ai_result: 0, sent: 0 })
const currentUser = computed(() => authState.user)
const sidebarCollapsed = ref(localStorage.getItem('smart_office_sidebar_collapsed') === '1')
const hubOpen = ref(false)
const hubActive = ref('tasks')
const hubLoading = ref(false)
const hubTasks = ref([])
const hubNotifications = ref([])
let unreadTimer = null

const pageMeta = {
  workbench: { title: '智能工作台', description: '工作、申请、待办、通知与合作动态的一体化入口' },
  tasks: { title: '待办中心', description: '集中处理审批、申请进度、部门消息与未读提醒' },
  oa_apply: { title: 'OA 智能申请', description: '通过自然语言快速完成 OA 表单' },
  my_applications: { title: '我的申请', description: '查看本人申请记录与审批状态' },
  approval_center: { title: '审批中心', description: '处理本部门待审批申请' },
  notifications: { title: '通知中心', description: '查看申请、审批与系统通知' },
  profile: { title: '个人中心', description: '员工资料与密码管理' },
  users: { title: '员工与权限', description: '管理员工账号、角色与状态' },
  messages: { title: '飞书消息中心', description: '按账号权限查看本部门业务消息分类和处理结果' },
  message_dashboard: { title: '消息分流仪表盘', description: '飞书业务消息分流数据统计' },
  workflows: { title: 'Dify 应用管理', description: '管理不同 Dify 应用的独立配置' },
  rules: { title: '规则配置', description: '管理本地业务分流规则' },
  doc_search: { title: '内部文档智能检索', description: '连接公司知识库，用自然语言查询制度、流程与业务文档' },
  quiz_generate: { title: '员工考核出题与批阅', description: '生成考核题目、上传员工答卷并完成智能批阅' },
  training_analysis: { title: '考核评估与培训建议', description: '按个人、部门或全员范围分析考核结果并生成培训方案' },
  meeting_minutes: { title: '会议纪要生成', description: '将会议内容整理为结构化纪要与待办' },
  report_generate: { title: '日报与阶段报表', description: '提交个人日报并生成日报、周报、月报或阶段汇总' },
}
const currentPage = computed(() => pageMeta[activeMenu.value] || { title: '功能建设中', description: '该功能已预留' })

const menuGroups = [
  { key: 'workspace', label: '工作空间', items: [
    { key: 'workbench', label: '智能工作台', icon: '⌂' },
    { key: 'tasks', label: '待办中心', icon: '✓' },
    { key: 'notifications', label: '通知中心', icon: '◉' },
    { key: 'messages', label: '消息中心', icon: 'N', permission: 'message.view_department' },
    { key: 'profile', label: '个人中心', icon: '◎' }
  ]},
  { key: 'oa', label: 'OA 办公', items: [
    { key: 'oa_apply', label: '智能申请', icon: 'AI', permission: 'oa.create' },
    { key: 'my_applications', label: '我的申请', icon: 'OA', permission: 'oa.view_own' },
    { key: 'approval_center', label: '审批中心', icon: '✓', permission: 'oa.approve' }
  ]},
  { key: 'ai', label: 'AI 业务工具', items: [
    { key: 'doc_search', label: '内部文档检索', icon: '⌕', permission: 'ai.use' },
    { key: 'quiz_generate', label: '考核出题与批阅', icon: '?', permission: 'ai.use' },
    { key: 'training_analysis', label: '考核评估与培训', icon: 'Σ', permission: 'ai.use' },
    { key: 'meeting_minutes', label: '会议纪要生成', icon: 'M', permission: 'ai.use' },
    { key: 'report_generate', label: '日报与阶段报表', icon: 'R', permission: 'ai.use' },
  ]},
  { key: 'admin', label: '系统管理', items: [
    { key: 'users', label: '员工与权限', icon: 'U', permission: 'user.manage' },
    { key: 'message_dashboard', label: '消息仪表盘', icon: 'D', permission: 'message.view' },
    { key: 'workflows', label: 'Dify 应用', icon: 'W', permission: 'workflow.manage' },
    { key: 'rules', label: '规则配置', icon: 'R', permission: 'rule.manage' }
  ]}
]

const visibleMenuGroups = computed(() => {
  if (currentUser.value?.must_change_password) {
    return [{ key: 'security', label: '安全设置', items: [{ key: 'profile', label: '修改初始密码', icon: '◎' }] }]
  }
  return menuGroups.map(group => ({
    ...group,
    items: group.items.filter(item => !item.permission || hasPermission(item.permission))
  })).filter(group => group.items.length)
})

const activeSection = computed(() => {
  if (['oa_apply', 'my_applications', 'approval_center'].includes(activeMenu.value)) return 'oa'
  if (['doc_search', 'quiz_generate', 'training_analysis', 'meeting_minutes', 'report_generate'].includes(activeMenu.value)) return 'ai'
  if (['users', 'message_dashboard', 'workflows', 'rules'].includes(activeMenu.value)) return 'admin'
  return 'work'
})

const activeSectionName = computed(() => ({
  work: '工作空间',
  oa: 'OA 办公',
  ai: 'AI 业务工具',
  admin: '系统管理'
}[activeSection.value]))

function forcePasswordChangePage(showMessage = true) {
  if (!currentUser.value) return
  activeMenu.value = 'profile'
  if (showMessage) ElMessage.warning('当前为初始密码，请先修改密码后再使用其他功能')
}

onMounted(async () => {
  window.addEventListener('smart-office-password-change-required', forcePasswordChangePage)
  window.addEventListener('visibilitychange', handleVisibilityChange)

  if (currentUser.value?.must_change_password) activeMenu.value = 'profile'
  const restoredUser = await restoreSession()
  if (restoredUser) {
    if (restoredUser.must_change_password) {
      forcePasswordChangePage(true)
    } else {
      activeMenu.value = 'workbench'
      await refreshUnread()
      startUnreadPolling()
      if (hasPermission('message.view_department')) loadAdminData()
    }
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('smart-office-password-change-required', forcePasswordChangePage)
  window.removeEventListener('visibilitychange', handleVisibilityChange)
  stopUnreadPolling()
})

async function handleLoginSuccess(user) {
  activeMenu.value = user.must_change_password ? 'profile' : 'workbench'
  stopUnreadPolling()
  if (!user.must_change_password) {
    await refreshUnread()
    startUnreadPolling()
    if (hasPermission('message.view_department')) loadAdminData()
  }
}

async function handlePasswordChanged(user) {
  if (!user || user.must_change_password) return
  activeMenu.value = 'workbench'
  await refreshUnread()
  startUnreadPolling()
  if (hasPermission('message.view_department')) await loadAdminData()
  ElMessage.success('安全设置完成，全部已授权功能现已可用')
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('smart_office_sidebar_collapsed', sidebarCollapsed.value ? '1' : '0')
}

function navigate(page) {
  // 兼容 main.py 和历史通知中保存的 message_center 页面键。
  const pageAliases = { message_center: 'messages' }
  page = pageAliases[page] || page

  if (currentUser.value?.must_change_password && page !== 'profile') {
    forcePasswordChangePage(true)
    return
  }
  const item = menuGroups.flatMap(group => group.items).find(entry => entry.key === page)
  if (item?.permission && !hasPermission(item.permission)) {
    ElMessage.warning('当前账号无权访问该功能')
    return
  }
  activeMenu.value = page
  hubOpen.value = false
  if (page === 'workbench') pageRefreshKey.value += 1
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function handleNotificationNavigate(page, businessId) {
  if (businessId) sessionStorage.setItem('smart_office_target_business_id', String(businessId))
  navigate(page || 'notifications')
}

async function refreshUnread() {
  if (!currentUser.value || currentUser.value.must_change_password) return
  try {
    const [notificationResponse, taskResponse] = await Promise.all([
      getNotifications({ page: 1, page_size: 1 }),
      getTaskSummary()
    ])
    unreadCount.value = notificationResponse.data.unread_count || 0
    taskCount.value = taskResponse.data.counts?.all || 0
  } catch (error) {
    console.debug('加载待办与通知数量失败', error)
  }
}

function startUnreadPolling() {
  stopUnreadPolling()
  if (!currentUser.value || currentUser.value.must_change_password) return
  unreadTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') refreshUnread()
  }, 20000)
}

function stopUnreadPolling() {
  if (unreadTimer) {
    window.clearInterval(unreadTimer)
    unreadTimer = null
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'visible') refreshUnread()
}

async function loadAdminData() {
  if (!hasPermission('message.view_department')) return

  try {
    // 普通员工和部门领导只加载本人可见的部门消息；
    // 只有平台管理员/超级管理员才额外加载全局仪表盘。
    if (hasPermission('message.view')) {
      const [summaryResponse, messageResponse] = await Promise.all([
        getDashboardSummary(),
        getMessages(100)
      ])
      legacySummary.value = summaryResponse.data
      messages.value = messageResponse.data
    } else {
      const messageResponse = await getMessages(100)
      messages.value = messageResponse.data
    }
  } catch (error) {
    console.debug('加载消息中心数据失败', error)
  }
}

async function openHub(tab = 'tasks') {
  hubActive.value = tab
  hubOpen.value = true
  hubLoading.value = true
  try {
    const [taskResponse, notificationResponse] = await Promise.all([
      getTasks({ page: 1, page_size: 6 }),
      getNotifications({ page: 1, page_size: 6 })
    ])
    hubTasks.value = taskResponse.data.items || []
    hubNotifications.value = notificationResponse.data.items || []
    taskCount.value = taskResponse.data.counts?.all ?? taskCount.value
    unreadCount.value = notificationResponse.data.unread_count ?? unreadCount.value
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '协同中心加载失败')
  } finally {
    hubLoading.value = false
  }
}

function openHubItem(page, businessId) {
  if (businessId) sessionStorage.setItem('smart_office_target_business_id', String(businessId))
  navigate(page)
}

function hubTaskIcon(item) {
  if (item.category === 'approval') return '审'
  if (item.category === 'application') return '申'
  if (item.category === 'department_message') return '部'
  return '知'
}

function hubNoticeIcon(type) {
  if (type === 'oa_approved') return '✓'
  if (type === 'oa_rejected') return '×'
  if (type === 'oa_submitted') return 'OA'
  if (type === 'feishu_department_message') return '部'
  return '知'
}

function formatHubTime(value) {
  if (!value) return ''
  const text = String(value).replace('T', ' ')
  return text.slice(5, 16)
}

async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen?.()
    } else {
      await document.exitFullscreen?.()
    }
  } catch (error) {
    ElMessage.info('当前浏览器未允许全屏显示')
  }
}

function handleSearch() {
  const keyword = searchText.value.trim()
  if (!keyword) return
  const aliases = [
    ['申请', 'oa_apply'], ['待办', 'tasks'], ['审批', 'approval_center'], ['通知', 'notifications'], ['员工', 'users'],
    ['工作流', 'workflows'], ['Dify', 'workflows'], ['规则', 'rules'], ['消息', 'messages'], ['文档', 'doc_search'],
    ['考核', 'quiz_generate'], ['出题', 'quiz_generate'], ['批阅', 'quiz_generate'], ['评估', 'training_analysis'],
    ['培训', 'training_analysis'], ['日报', 'report_generate'], ['周报', 'report_generate'], ['报表', 'report_generate'],
    ['会议', 'meeting_minutes'], ['合作', 'workbench']
  ]
  const match = aliases.find(([name]) => keyword.toLowerCase().includes(name.toLowerCase()))
  if (match) {
    navigate(match[1])
    if (keyword.includes('合作')) openHub('cooperation')
  } else {
    ElMessage.info('暂未找到匹配功能')
  }
  searchText.value = ''
}

async function handleUserCommand(command) {
  if (command === 'profile') return navigate('profile')
  if (command === 'tasks') return navigate('tasks')
  if (command === 'notifications') return navigate('notifications')
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出当前账号吗？', '退出登录', { type: 'warning' })
      stopUnreadPolling()
      await logout()
      activeMenu.value = 'workbench'
      unreadCount.value = 0
      taskCount.value = 0
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') console.error(error)
    }
  }
}
</script>
