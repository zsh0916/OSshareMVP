<template>
  <div class="page-shell">
    <div class="page-title-row">
      <div>
        <span class="page-kicker">MY APPLICATIONS</span>
        <h2>我的申请</h2>
        <p>查看本人提交的全部 OA 申请及审批结果。</p>
      </div>
      <div class="title-actions">
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 150px" @change="loadData">
          <el-option label="草稿" value="draft" />
          <el-option label="待审批" value="submitted" />
          <el-option label="已通过" value="approved" />
          <el-option label="已驳回" value="rejected" />
        </el-select>
        <el-button @click="loadData">刷新</el-button>
        <el-button type="primary" @click="$emit('navigate', 'oa_apply')">发起申请</el-button>
      </div>
    </div>

    <section class="table-card" v-loading="loading">
      <el-table :data="items" class="dark-table" empty-text="暂无申请记录" @row-click="openDetail">
        <el-table-column prop="id" label="编号" width="80" />
        <el-table-column prop="application_type_name" label="申请类型" min-width="150" />
        <el-table-column prop="summary" label="申请摘要" min-width="240" show-overflow-tooltip />
        <el-table-column prop="department" label="部门" width="120" />
        <el-table-column prop="status_name" label="状态" width="110">
          <template #default="{ row }">
            <span class="status-badge" :class="row.status">{{ row.status_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" width="170">
          <template #default="{ row }">{{ formatTime(row.submitted_at || row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-row">
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="loadData" />
      </div>
    </section>

    <el-drawer v-model="drawerVisible" title="OA 申请详情" size="48%">
      <div v-if="detail" class="detail-wrap">
        <div class="detail-hero">
          <div>
            <span>申请编号 #{{ detail.id }}</span>
            <h3>{{ detail.application_type_name }}</h3>
            <p>{{ detail.summary }}</p>
          </div>
          <span class="status-badge large" :class="detail.status">{{ detail.status_name }}</span>
        </div>

        <div class="detail-grid">
          <div><span>申请人</span><strong>{{ detail.applicant_name }}</strong></div>
          <div><span>所属部门</span><strong>{{ detail.department }}</strong></div>
          <div><span>提交时间</span><strong>{{ formatTime(detail.submitted_at || detail.created_at) }}</strong></div>
          <div><span>审批人</span><strong>{{ detail.approver_name || '待分配' }}</strong></div>
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
              <div><strong>{{ record.approver_name }} · {{ record.action === 'approve' ? '通过' : '驳回' }}</strong><p>{{ record.comment || '无审批意见' }}</p><small>{{ formatTime(record.created_at) }}</small></div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getOaApplicationDetail, listOaApplications } from '../api/index.js'

defineEmits(['navigate'])
const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const status = ref('')
const drawerVisible = ref(false)
const detail = ref(null)

const detailFields = computed(() => {
  const fields = detail.value?.submit_data?.fields || detail.value?.form_data || {}
  return Object.entries(fields).map(([key, field]) => ({
    key,
    label: typeof field === 'object' ? (field.label || key) : key,
    value: typeof field === 'object' ? field.value : field
  }))
})

onMounted(async () => {
  await loadData()
  const targetId = Number(sessionStorage.getItem('smart_office_target_business_id') || 0)
  if (targetId) {
    sessionStorage.removeItem('smart_office_target_business_id')
    await openDetail({ id: targetId })
  }
})

async function loadData() {
  loading.value = true
  try {
    const response = await listOaApplications({ scope: 'mine', status: status.value, page: page.value, page_size: pageSize })
    items.value = response.data.items || []
    total.value = response.data.total || 0
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  try {
    const response = await getOaApplicationDetail(row.id)
    detail.value = response.data
    drawerVisible.value = true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载申请详情失败')
  }
}

function formatTime(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '-' }
function formatValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}
</script>

<style scoped>
.page-shell{display:flex;flex-direction:column;gap:20px}.page-title-row{display:flex;justify-content:space-between;align-items:flex-end}.page-kicker{color:#6f8dff;font-size:11px;letter-spacing:2px}h2{color:#f8fafc;margin:7px 0 6px;font-size:28px}.page-title-row p{color:#727d91;margin:0}.title-actions{display:flex;gap:10px}.table-card{border:1px solid #202638;background:#10131d;border-radius:20px;padding:16px;min-height:480px}.pagination-row{display:flex;justify-content:flex-end;padding:18px 4px 4px}.status-badge{display:inline-flex;padding:5px 10px;border-radius:999px;font-size:11px;background:#252a38;color:#a7b0c2}.status-badge.submitted{background:rgba(240,161,28,.13);color:#f3b74f}.status-badge.approved{background:rgba(29,190,138,.13);color:#4bd8aa}.status-badge.rejected{background:rgba(239,90,111,.13);color:#ff8293}.status-badge.draft{background:rgba(111,127,154,.14);color:#9ca8ba}.status-badge.large{font-size:13px;padding:8px 13px}.detail-wrap{color:#dfe5ee}.detail-hero{display:flex;justify-content:space-between;gap:20px;padding:24px;border-radius:18px;background:linear-gradient(135deg,#171c2d,#10131e);border:1px solid #272e42}.detail-hero span,.detail-hero p{color:#7e889b}.detail-hero h3{font-size:26px;margin:8px 0}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}.detail-grid>div,.field-list>div{padding:15px;border:1px solid #252c3e;border-radius:13px;background:#121622}.detail-grid span,.field-list span{display:block;color:#737e91;font-size:12px;margin-bottom:6px}.detail-section{margin-top:22px}.detail-section h4{margin:0 0 12px}.field-list{display:grid;grid-template-columns:1fr 1fr;gap:10px}.comment-box{padding:16px;border-radius:13px;background:#171b27;color:#b9c2d1;line-height:1.8}.timeline>div{display:grid;grid-template-columns:12px 1fr;gap:12px;padding:0 0 20px}.timeline i{width:8px;height:8px;border-radius:50%;background:#4d73ff;margin-top:6px;box-shadow:0 0 0 5px rgba(77,115,255,.12)}.timeline p{color:#7b8598;margin:5px 0}.timeline small{color:#586174}@media(max-width:900px){.page-title-row{flex-direction:column;align-items:flex-start;gap:16px}.detail-grid,.field-list{grid-template-columns:1fr}}
</style>
