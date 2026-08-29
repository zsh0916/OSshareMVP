<template>
  <section class="analysis-page">
    <div class="analysis-hero">
      <div>
        <p class="eyebrow">ASSESSMENT INSIGHT</p>
        <h1>考核评估与培训建议</h1>
        <p>按个人、部门或全员范围汇总考核结果，生成薄弱项分析与分层培训方案。</p>
      </div>
      <div :class="['status-chip', status.configured ? 'ready' : 'warning']">
        <span></span>{{ status.configured ? `已连接：${status.workflow_name || '考核评估应用'}` : '尚未配置' }}
      </div>
    </div>

    <el-alert
      v-if="!status.configured"
      type="warning"
      :closable="false"
      title="请在 Dify 应用管理中配置 module_key=employee_assessment_analysis"
      style="margin-bottom: 18px"
    />

    <div class="analysis-grid">
      <el-card class="form-card" shadow="never">
        <template #header>
          <div class="card-heading">
            <div><strong>查询条件</strong><small>平台会根据当前账号角色限制可查询范围</small></div>
            <el-button text :disabled="loading" @click="resetForm">重置</el-button>
          </div>
        </template>

        <el-form label-position="top">
          <el-form-item label="分析范围" required>
            <el-radio-group v-model="form.scope" @change="handleScopeChange">
              <el-radio-button v-for="item in scopeOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item v-if="form.scope === 'personal'" label="员工姓名或工号" required>
            <el-input
              v-model="form.target"
              :disabled="isEmployee"
              maxlength="80"
              placeholder="请输入员工代号或平台工号，例如：USER_BETA 或 EMP002"
            />
            <div v-if="isEmployee" class="field-tip">普通员工仅能查询本人，系统已自动使用当前账号。</div>
            <div v-else-if="isDepartmentManager" class="field-tip">部门领导仅能查询本部门员工。</div>
          </el-form-item>

          <el-form-item v-else-if="form.scope === 'department'" label="部门" required>
            <el-select
              v-if="isAdmin"
              v-model="form.target"
              filterable
              style="width: 100%"
              placeholder="请选择需要分析的部门"
            >
              <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.name" />
            </el-select>
            <el-input v-else v-model="form.target" disabled />
            <div v-if="isDepartmentManager" class="field-tip">部门领导仅能分析本人所在部门。</div>
          </el-form-item>

          <el-form-item label="考核类型" required>
            <el-select v-model="form.assessmentType" style="width: 100%" placeholder="请选择需要分析的考核类型">
              <el-option v-for="item in assessmentTypes" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>

          <el-form-item label="补充要求">
            <el-input
              v-model="form.extraRequirements"
              type="textarea"
              :rows="4"
              maxlength="500"
              show-word-limit
              placeholder="请输入分析重点，例如：重点关注连续两次未达标人员，并给出两周复训安排"
            />
          </el-form-item>

          <el-button
            type="primary"
            size="large"
            class="main-action"
            :loading="loading"
            :disabled="!status.configured"
            @click="submitAnalysis"
          >
            {{ loading ? '正在查询数据并生成分析…' : '生成考核分析与培训建议' }}
          </el-button>
        </el-form>
      </el-card>

      <el-card class="guide-card" shadow="never">
        <template #header><strong>权限与工作流说明</strong></template>
        <div class="guide-item"><b>01</b><div><strong>普通员工</strong><p>仅查看本人考核分析与个人学习建议。</p></div></div>
        <div class="guide-item"><b>02</b><div><strong>部门领导</strong><p>可查看本部门员工或本部门整体分析。</p></div></div>
        <div class="guide-item"><b>03</b><div><strong>平台管理员</strong><p>可按个人、部门或全员范围生成分析。</p></div></div>
        <div class="guide-item"><b>04</b><div><strong>报告展示</strong><p>生成后以弹窗展示，标题、加粗、列表等 Markdown 格式会自动排版。</p></div></div>
        <div class="identity-box">
          <span>当前账号</span>
          <strong>{{ currentUser?.name || '当前用户' }}</strong>
          <small>{{ currentUser?.department_name || '未配置部门' }} · {{ currentUser?.role_name || '' }}</small>
        </div>
      </el-card>
    </div>

    <div v-if="result" class="result-ready-bar">
      <div>
        <span class="ready-icon">✓</span>
        <div>
          <strong>考核分析报告已生成</strong>
          <small>{{ scopeLabel(result.scope) }} · {{ result.target || '全员' }} · {{ result.assessment_type }}</small>
        </div>
      </div>
      <el-button type="primary" @click="reportDialogVisible = true">查看完整报告</el-button>
    </div>

    <el-dialog
      v-model="reportDialogVisible"
      title="考核分析与培训建议"
      width="880px"
      class="analysis-report-dialog"
      append-to-body
      destroy-on-close
    >
      <div v-if="result" class="report-shell">
        <div class="report-meta">
          <div><span>分析范围</span><strong>{{ scopeLabel(result.scope) }}</strong></div>
          <div><span>查询对象</span><strong>{{ result.target || '全员' }}</strong></div>
          <div><span>考核类型</span><strong>{{ result.assessment_type || '全部' }}</strong></div>
        </div>
        <article class="report-markdown" v-html="renderedReport"></article>
      </div>
      <template #footer>
        <el-button @click="reportDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="copyResult">复制报告</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { renderSafeMarkdown } from '../utils/markdown.js'
import {
  analyzeEmployeeAssessment,
  getDepartments,
  getEmployeeAssessmentAnalysisStatus
} from '../api/index.js'

const props = defineProps({
  currentUser: { type: Object, default: () => ({}) }
})

const loading = ref(false)
const status = ref({ configured: false, allowed_scopes: ['personal'] })
const departments = ref([])
const result = ref(null)
const reportDialogVisible = ref(false)

const assessmentTypes = ['全部', '员工入职考核', '技能考核', '业务知识考核', '学习能力考核', '综合考核']
const roleCode = computed(() => props.currentUser?.role_code || 'employee')
const isEmployee = computed(() => roleCode.value === 'employee')
const isDepartmentManager = computed(() => roleCode.value === 'department_manager')
const isAdmin = computed(() => ['platform_admin', 'super_admin'].includes(roleCode.value))
const ownTarget = computed(() => props.currentUser?.employee_id || props.currentUser?.name || '')
const ownDepartment = computed(() => props.currentUser?.department_name || '')

const form = ref({
  scope: 'personal',
  target: ownTarget.value,
  assessmentType: '全部',
  extraRequirements: ''
})

const scopeOptions = computed(() => {
  const allowed = status.value.allowed_scopes || ['personal']
  const labels = { personal: '个人', department: '部门', all: '全员' }
  return allowed.map(value => ({ value, label: labels[value] || value }))
})

const renderedReport = computed(() => renderSafeMarkdown(result.value?.report || ''))

function scopeLabel(value) {
  return ({ personal: '个人分析', department: '部门分析', all: '全员分析' })[value] || value
}

function setTargetForScope() {
  if (form.value.scope === 'personal') {
    if (isEmployee.value) form.value.target = ownTarget.value
    else if (!form.value.target || form.value.target === ownDepartment.value) form.value.target = ownTarget.value
  } else if (form.value.scope === 'department') {
    if (isDepartmentManager.value) form.value.target = ownDepartment.value
    else if (form.value.target === ownTarget.value) form.value.target = ''
  } else {
    form.value.target = ''
  }
}

function handleScopeChange() {
  result.value = null
  reportDialogVisible.value = false
  setTargetForScope()
}

function resetForm() {
  form.value.scope = (status.value.allowed_scopes || ['personal'])[0] || 'personal'
  form.value.assessmentType = '全部'
  form.value.extraRequirements = ''
  form.value.target = form.value.scope === 'department' ? ownDepartment.value : ownTarget.value
  result.value = null
  reportDialogVisible.value = false
}

async function loadStatus() {
  try {
    const response = await getEmployeeAssessmentAnalysisStatus()
    status.value = response.data
    if (!(status.value.allowed_scopes || []).includes(form.value.scope)) {
      form.value.scope = (status.value.allowed_scopes || ['personal'])[0]
    }
    setTargetForScope()
  } catch (error) {
    console.error(error)
    status.value = { configured: false, allowed_scopes: ['personal'] }
  }
}

async function loadDepartments() {
  if (!isAdmin.value) return
  try { departments.value = (await getDepartments()).data || [] }
  catch (error) { console.error(error) }
}

async function submitAnalysis() {
  if (form.value.scope !== 'all' && !String(form.value.target || '').trim()) {
    return ElMessage.warning('请选择或填写查询对象')
  }
  loading.value = true
  result.value = null
  reportDialogVisible.value = false
  try {
    const response = await analyzeEmployeeAssessment({
      scope: form.value.scope,
      target: form.value.target,
      assessment_type: form.value.assessmentType,
      extra_requirements: form.value.extraRequirements
    })
    result.value = response.data
    reportDialogVisible.value = true
    ElMessage.success('考核分析已生成')
  } catch (error) {
    console.error(error)
    const detail = error?.response?.data?.detail || '生成考核分析失败'
    if (String(detail).includes('operation') || String(detail).includes('API Key') || error?.response?.status === 409) {
      await ElMessageBox.alert(
        String(detail),
        'Dify 应用绑定不匹配',
        {
          confirmButtonText: '我知道了',
          type: 'error'
        }
      )
    } else {
      ElMessage.error(detail)
    }
  } finally {
    loading.value = false
  }
}

async function copyResult() {
  try {
    await navigator.clipboard.writeText(result.value?.report || '')
    ElMessage.success('报告已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

onMounted(async () => {
  await loadStatus()
  await loadDepartments()
})
</script>

<style scoped>
.analysis-page { padding: 4px; color: #e5e7eb; }
.analysis-hero { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; padding: 28px 30px; margin-bottom: 18px; border: 1px solid rgba(99, 102, 241, .35); border-radius: 18px; background: linear-gradient(135deg, #111827, #1e2f5f); box-shadow: 0 16px 38px rgba(2, 6, 23, .25); color: white; }
.analysis-hero h1 { margin: 4px 0 8px; font-size: 28px; }
.analysis-hero p { margin: 0; color: #cbd5e1; }
.eyebrow { margin: 0; letter-spacing: 1.5px; font-size: 12px; color: #93c5fd; }
.status-chip { display: flex; align-items: center; gap: 8px; padding: 8px 13px; border: 1px solid rgba(255,255,255,.12); border-radius: 999px; background: rgba(255,255,255,.1); white-space: nowrap; }
.status-chip span { width: 8px; height: 8px; border-radius: 50%; background: #f59e0b; }
.status-chip.ready span { background: #34d399; box-shadow: 0 0 10px rgba(52, 211, 153, .7); }
.analysis-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, .8fr); gap: 18px; }
.form-card, .guide-card { border: 1px solid rgba(148, 163, 184, .2); border-radius: 16px; background: #101827; color: #e5e7eb; }
.form-card :deep(.el-card__header), .guide-card :deep(.el-card__header) { border-bottom-color: rgba(148, 163, 184, .16); }
.form-card :deep(.el-form-item__label) { color: #dbeafe; font-weight: 600; }
.card-heading { display: flex; justify-content: space-between; align-items: center; gap: 18px; }
.card-heading div { display: flex; flex-direction: column; gap: 4px; }
.card-heading strong { color: #f8fafc; font-size: 18px; }
.card-heading small, .field-tip { color: #94a3b8; font-size: 12px; }
.main-action { width: 100%; margin-top: 4px; }
.guide-card :deep(.el-card__header) strong { color: #f8fafc; }
.guide-item { display: flex; gap: 12px; padding: 14px 0; border-bottom: 1px solid rgba(148, 163, 184, .14); }
.guide-item b { display: grid; place-items: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 9px; background: rgba(99, 102, 241, .18); color: #a5b4fc; }
.guide-item strong { color: #f1f5f9; font-size: 14px; }
.guide-item p { margin: 5px 0 0; color: #a8b3c7; line-height: 1.6; font-size: 13px; }
.identity-box { margin-top: 18px; padding: 16px; border: 1px solid rgba(96, 165, 250, .18); border-radius: 12px; background: rgba(30, 41, 59, .76); display: flex; flex-direction: column; gap: 4px; }
.identity-box strong { color: #f8fafc; }
.identity-box span, .identity-box small { color: #94a3b8; font-size: 12px; }
.result-ready-bar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 18px; padding: 18px 20px; border: 1px solid rgba(52, 211, 153, .26); border-radius: 14px; background: rgba(6, 78, 59, .22); }
.result-ready-bar > div { display: flex; align-items: center; gap: 12px; }
.result-ready-bar div div { display: flex; flex-direction: column; gap: 3px; }
.result-ready-bar strong { color: #ecfdf5; }
.result-ready-bar small { color: #a7f3d0; }
.ready-icon { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; background: #10b981; color: white; font-weight: 800; }
@media (max-width: 960px) { .analysis-grid { grid-template-columns: 1fr; } .analysis-hero { flex-direction: column; } }
</style>

<style>
.analysis-report-dialog.el-dialog { overflow: hidden; border-radius: 18px; background: #ffffff; box-shadow: 0 26px 80px rgba(15, 23, 42, .28); }
.analysis-report-dialog .el-dialog__header { margin: 0; padding: 20px 24px; border-bottom: 1px solid #e5e7eb; }
.analysis-report-dialog .el-dialog__title { color: #111827; font-size: 20px; font-weight: 750; }
.analysis-report-dialog .el-dialog__body { padding: 0; }
.analysis-report-dialog .el-dialog__footer { padding: 14px 24px 18px; border-top: 1px solid #e5e7eb; }
.report-shell { max-height: 72vh; overflow-y: auto; padding: 22px 26px 30px; background: #f8fafc; }
.report-meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 18px; }
.report-meta div { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border: 1px solid #dbeafe; border-radius: 10px; background: #fff; }
.report-meta span { color: #64748b; font-size: 12px; }
.report-meta strong { color: #0f172a; font-size: 14px; }
.report-markdown { padding: 24px 28px; border: 1px solid #e2e8f0; border-radius: 14px; background: #fff; color: #24324a; font-size: 15px; line-height: 1.85; }
.report-markdown h2, .report-markdown h3, .report-markdown h4 { margin: 24px 0 10px; color: #0f172a; line-height: 1.35; }
.report-markdown h2:first-child, .report-markdown h3:first-child, .report-markdown h4:first-child { margin-top: 0; }
.report-markdown h2 { padding-bottom: 9px; border-bottom: 1px solid #dbeafe; font-size: 22px; }
.report-markdown h3 { padding-left: 10px; border-left: 4px solid #6366f1; font-size: 18px; }
.report-markdown h4 { font-size: 16px; }
.report-markdown p { margin: 8px 0; }
.report-markdown ul, .report-markdown ol { margin: 8px 0 12px; padding-left: 25px; }
.report-markdown li { margin: 5px 0; }
.report-markdown strong { color: #111827; font-weight: 750; }
.report-markdown code { padding: 2px 6px; border-radius: 5px; background: #eef2ff; color: #4338ca; font-family: Consolas, monospace; }
@media (max-width: 720px) { .analysis-report-dialog.el-dialog { width: 94% !important; } .report-meta { grid-template-columns: 1fr; } .report-shell { padding: 16px; } .report-markdown { padding: 18px; } }
</style>
