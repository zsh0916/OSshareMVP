<template>
  <div class="page-shell">
    <div class="page-title-row">
      <div>
        <span class="page-kicker">APPROVAL CENTER</span>
        <h2>审批中心</h2>
        <p>处理你有权限审批的 OA 申请，并查看本人历史审批记录。</p>
      </div>
      <el-button type="primary" :loading="loading" @click="loadData">刷新</el-button>
    </div>

    <section class="approval-overview">
      <div><span>当前待审批</span><strong>{{ pendingTotal }}</strong></div>
      <div><span>本人已处理</span><strong>{{ historyTotal }}</strong></div>
      <div><span>审批身份</span><strong>{{ user?.role_name }}</strong></div>
    </section>

    <section class="approval-panel">
      <div class="approval-tabs">
        <button :class="{ active: activeTab === 'pending' }" @click="switchTab('pending')">
          待我审批 <i>{{ pendingTotal }}</i>
        </button>
        <button :class="{ active: activeTab === 'history' }" @click="switchTab('history')">
          我已处理 <i>{{ historyTotal }}</i>
        </button>
      </div>

      <div class="approval-list" v-loading="loading">
        <div v-if="!items.length" class="empty-state">
          {{ activeTab === 'pending' ? '暂无待审批申请' : '暂无历史审批记录' }}
        </div>

        <article v-for="item in items" :key="item.id" class="approval-card">
          <div class="approval-type">{{ shortType(item.application_type_name) }}</div>
          <div class="approval-main">
            <div class="approval-title">
              <strong>{{ item.application_type_name }}</strong>
              <span class="status-pill" :class="item.status">{{ statusName(item.status) }}</span>
            </div>
            <p>{{ item.summary || `${item.applicant_name}提交申请` }}</p>
            <div class="approval-meta">
              <span>申请人：{{ item.applicant_name }}</span>
              <span>部门：{{ item.department }}</span>
              <span>提交：{{ formatTime(item.submitted_at || item.created_at) }}</span>
              <span v-if="activeTab === 'history'">处理：{{ formatTime(item.approved_at || item.rejected_at) }}</span>
            </div>
          </div>
          <div class="approval-actions">
            <el-button @click="openDetail(item)">查看详情</el-button>
            <template v-if="activeTab === 'pending'">
              <el-button type="success" @click="openDecision(item, 'approve')">通过</el-button>
              <el-button type="danger" plain @click="openDecision(item, 'reject')">驳回</el-button>
            </template>
          </div>
        </article>

        <div class="pagination-row" v-if="total > pageSize">
          <el-pagination
            v-model:current-page="page"
            :page-size="pageSize"
            :total="total"
            layout="total, prev, pager, next"
            @current-change="loadData"
          />
        </div>
      </div>
    </section>

    <el-drawer v-model="detailVisible" title="审批详情" size="52%">
      <div v-if="detail" class="detail-wrap">
        <div class="detail-hero">
          <div>
            <small>申请编号 #{{ detail.id }}</small>
            <h3>{{ detail.application_type_name }}</h3>
            <p>{{ detail.summary }}</p>
          </div>
          <span class="status-pill large" :class="detail.status">{{ detail.status_name || statusName(detail.status) }}</span>
        </div>

        <div class="detail-grid">
          <div><span>申请人</span><strong>{{ detail.applicant_name }}</strong></div>
          <div><span>所属部门</span><strong>{{ detail.department }}</strong></div>
          <div><span>提交时间</span><strong>{{ formatTime(detail.submitted_at || detail.created_at) }}</strong></div>
          <div><span>审批人</span><strong>{{ detail.approver_name || '尚未处理' }}</strong></div>
        </div>

        <div class="detail-section">
          <h4>申请内容</h4>
          <div class="field-list">
            <div v-for="field in detailFields" :key="field.key">
              <span>{{ field.label }}</span>
              <strong>{{ formatValue(field.value) }}</strong>
            </div>
          </div>
        </div>

        <div class="detail-section" v-if="detail.approval_comment">
          <h4>审批意见</h4>
          <div class="comment-box">{{ detail.approval_comment }}</div>
        </div>

        <div class="detail-section" v-if="detail.approval_records?.length">
          <h4>审批记录</h4>
          <div class="timeline">
            <div v-for="record in detail.approval_records" :key="record.id">
              <i></i>
              <div>
                <strong>{{ record.approver_name }} · {{ record.action === 'approve' ? '通过' : '驳回' }}</strong>
                <p>{{ record.comment || '无审批意见' }}</p>
                <small>{{ formatTime(record.created_at) }}</small>
              </div>
            </div>
          </div>
        </div>

        <div class="drawer-actions" v-if="detail.status === 'submitted'">
          <el-button type="success" @click="openDecision(detail, 'approve')">审批通过</el-button>
          <el-button type="danger" plain @click="openDecision(detail, 'reject')">驳回申请</el-button>
        </div>
      </div>
    </el-drawer>

    <el-dialog v-model="decisionVisible" :title="decisionAction === 'approve' ? '确认审批通过' : '驳回申请'" width="520px">
      <el-input
        v-model="comment"
        type="textarea"
        :rows="5"
        maxlength="500"
        show-word-limit
        :placeholder="decisionAction === 'approve' ? '可填写审批意见（选填）' : '请填写驳回原因（必填）'"
      />
      <template #footer>
        <el-button @click="decisionVisible = false">取消</el-button>
        <el-button
          :type="decisionAction === 'approve' ? 'success' : 'danger'"
          :loading="processing"
          @click="submitDecision"
        >
          {{ decisionAction === 'approve' ? '确认通过' : '确认驳回' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  approveOaApplication,
  getApprovalHistory,
  getOaApplicationDetail,
  getPendingApprovals,
  rejectOaApplication
} from '../api/index.js'

const props = defineProps({ user: { type: Object, default: null } })
const loading = ref(false)
const processing = ref(false)
const items = ref([])
const total = ref(0)
const pendingTotal = ref(0)
const historyTotal = ref(0)
const activeTab = ref('pending')
const page = ref(1)
const pageSize = 20
const detailVisible = ref(false)
const decisionVisible = ref(false)
const detail = ref(null)
const selected = ref(null)
const decisionAction = ref('approve')
const comment = ref('')

const detailFields = computed(() => {
  const fields = detail.value?.submit_data?.fields || detail.value?.form_data || {}
  return Object.entries(fields).map(([key, field]) => ({
    key,
    label: typeof field === 'object' ? (field.label || key) : key,
    value: typeof field === 'object' ? field.value : field
  }))
})

onMounted(async () => {
  await loadTotals()
  await loadData()
  const targetId = Number(sessionStorage.getItem('smart_office_target_business_id') || 0)
  if (targetId) {
    sessionStorage.removeItem('smart_office_target_business_id')
    await openDetail({ id: targetId })
  }
})

async function loadTotals() {
  try {
    const [pendingResponse, historyResponse] = await Promise.all([
      getPendingApprovals({ page: 1, page_size: 1 }),
      getApprovalHistory({ page: 1, page_size: 1 })
    ])
    pendingTotal.value = pendingResponse.data.total || 0
    historyTotal.value = historyResponse.data.total || 0
  } catch (error) {
    console.debug('加载审批统计失败', error)
  }
}

async function loadData() {
  loading.value = true
  try {
    const request = activeTab.value === 'pending' ? getPendingApprovals : getApprovalHistory
    const response = await request({ page: page.value, page_size: pageSize })
    items.value = response.data.items || []
    total.value = response.data.total || 0
    if (activeTab.value === 'pending') pendingTotal.value = total.value
    else historyTotal.value = total.value
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载审批数据失败')
  } finally {
    loading.value = false
  }
}

function switchTab(tab) {
  activeTab.value = tab
  page.value = 1
  loadData()
}

async function openDetail(item) {
  try {
    const response = await getOaApplicationDetail(item.id)
    detail.value = response.data
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载详情失败')
  }
}

function openDecision(item, action) {
  selected.value = item
  decisionAction.value = action
  comment.value = ''
  decisionVisible.value = true
}

async function submitDecision() {
  if (decisionAction.value === 'reject' && !comment.value.trim()) {
    ElMessage.warning('驳回时必须填写原因')
    return
  }
  if (!selected.value?.id) {
    ElMessage.error('未找到待审批申请')
    return
  }

  processing.value = true
  try {
    if (decisionAction.value === 'approve') {
      await approveOaApplication(selected.value.id, { comment: comment.value.trim() })
    } else {
      await rejectOaApplication(selected.value.id, { comment: comment.value.trim() })
    }
    ElMessage.success(decisionAction.value === 'approve' ? '申请已通过' : '申请已驳回')
    decisionVisible.value = false
    detailVisible.value = false
    await loadTotals()
    await loadData()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '审批失败')
  } finally {
    processing.value = false
  }
}

function shortType(value) {
  return String(value || 'OA').replace('申请单', '').replace('申请', '').slice(0, 4)
}

function statusName(status) {
  return {
    draft: '草稿',
    submitted: '待审批',
    approved: '已通过',
    rejected: '已驳回',
    cancelled: '已撤回'
  }[status] || status || '-'
}

function formatTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)
}
</script>

<style scoped>
.page-shell { display:flex; flex-direction:column; gap:20px; }
.page-title-row { display:flex; justify-content:space-between; align-items:flex-end; }
.page-kicker { color:#6f8dff; font-size:11px; letter-spacing:2px; }
h2 { color:#f8fafc; margin:7px 0 6px; font-size:28px; }
.page-title-row p { color:#727d91; margin:0; }
.approval-overview { display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }
.approval-overview>div { padding:20px; border:1px solid #22293b; border-radius:17px; background:#11141f; }
.approval-overview span,.approval-overview strong { display:block; }
.approval-overview span { color:#778195; font-size:12px; }
.approval-overview strong { color:#e6ebf3; font-size:22px; margin-top:8px; }
.approval-panel { border:1px solid #202638; background:#0f121b; border-radius:20px; overflow:hidden; }
.approval-tabs { display:flex; gap:6px; padding:14px 18px; border-bottom:1px solid #202638; }
.approval-tabs button { border:0; background:transparent; color:#6f788b; padding:10px 15px; border-radius:10px; cursor:pointer; }
.approval-tabs button.active { color:#e7ecf5; background:#1a2030; }
.approval-tabs i { display:inline-flex; align-items:center; justify-content:center; min-width:20px; height:20px; padding:0 6px; margin-left:6px; border-radius:99px; background:#252c3e; color:#98a8d9; font-style:normal; font-size:10px; }
.approval-list { display:flex; flex-direction:column; gap:12px; padding:18px; min-height:360px; }
.approval-card { display:grid; grid-template-columns:58px 1fr auto; gap:16px; align-items:center; border:1px solid #22293b; border-radius:18px; background:#10131d; padding:18px 20px; }
.approval-type { width:52px; height:52px; display:grid; place-items:center; border-radius:15px; background:linear-gradient(135deg,#24315c,#1c2543); color:#89a3ff; font-size:12px; font-weight:700; }
.approval-title { display:flex; align-items:center; gap:10px; }
.approval-title strong { color:#e5eaf2; }
.status-pill { display:inline-flex; padding:4px 9px; border-radius:999px; font-size:11px; background:#252a38; color:#a7b0c2; }
.status-pill.submitted { background:rgba(240,161,28,.13); color:#f3b64c; }
.status-pill.approved { background:rgba(29,190,138,.13); color:#4bd8aa; }
.status-pill.rejected { background:rgba(239,90,111,.13); color:#ff8293; }
.status-pill.large { padding:8px 13px; font-size:13px; }
.approval-main p { color:#727c90; margin:6px 0; }
.approval-meta { display:flex; flex-wrap:wrap; gap:18px; color:#596375; font-size:11px; }
.approval-actions { display:flex; gap:8px; }
.pagination-row { display:flex; justify-content:flex-end; padding:16px; }
.empty-state { text-align:center; color:#596477; padding:80px; }
.detail-wrap { color:#e2e7ef; }
.detail-hero { display:flex; justify-content:space-between; gap:20px; padding:24px; border-radius:18px; background:linear-gradient(135deg,#171c2d,#10131e); border:1px solid #272e42; }
.detail-hero small,.detail-hero p { color:#7c8699; }
.detail-hero h3 { font-size:26px; margin:8px 0; }
.detail-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:16px 0; }
.detail-grid>div,.field-list>div { padding:15px; border:1px solid #252c3e; border-radius:13px; background:#121622; }
.detail-grid span,.field-list span { display:block; color:#737e91; font-size:12px; margin-bottom:6px; }
.detail-section { margin-top:22px; }
.field-list { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.comment-box { padding:16px; border-radius:13px; background:#171b27; color:#b9c2d1; line-height:1.8; }
.timeline>div { display:grid; grid-template-columns:12px 1fr; gap:12px; padding:0 0 20px; }
.timeline i { width:8px; height:8px; border-radius:50%; background:#4d73ff; margin-top:6px; box-shadow:0 0 0 5px rgba(77,115,255,.12); }
.timeline p { color:#7b8598; margin:5px 0; }
.timeline small { color:#586174; }
.drawer-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:24px; }
@media(max-width:900px) {
  .approval-card { grid-template-columns:50px 1fr; }
  .approval-actions { grid-column:1/-1; }
  .approval-overview { grid-template-columns:1fr; }
  .page-title-row { align-items:flex-start; flex-direction:column; gap:14px; }
  .detail-grid,.field-list { grid-template-columns:1fr; }
}
</style>
