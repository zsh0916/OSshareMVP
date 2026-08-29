<template>
  <div class="oa-page">
    <div class="oa-header">
      <div>
        <h2>OA 智能申请</h2>
        <p>员工只需要通过自然语言说明需求，AI 会自动收集字段，最后生成 OA 确认页。</p>
      </div>
      <div class="header-actions">
        <el-select
          v-if="canManageWorkflow"
          v-model="selectedWorkflowId"
          style="width: 240px"
          placeholder="选择 OA 对话应用"
          @change="handleWorkflowChange"
        >
          <el-option
            v-for="item in oaWorkflows"
            :key="item.id"
            :label="item.name"
            :value="item.id"
          />
        </el-select>
        <el-button @click="resetConversation">新建申请</el-button>
        <el-button type="primary" :disabled="!canOpenConfirm" @click="openConfirmDrawer">
          生成 OA 确认页
        </el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="15">
        <el-card class="chat-card" shadow="never">
          <template #header>
            <div class="card-title">
              <span>AI 对话申请</span>
              <el-tag v-if="templateName" type="success">{{ templateName }}</el-tag>
              <el-tag v-else type="info">未识别申请类型</el-tag>
            </div>
          </template>

          <div ref="chatBodyRef" class="chat-body">
            <div
              v-for="item in messages"
              :key="item.id"
              class="chat-item"
              :class="item.role"
            >
              <div class="avatar">
                {{ item.role === 'user' ? '我' : 'AI' }}
              </div>
              <div class="bubble">
                <div class="content" v-html="formatMessage(item.content)"></div>
                <div v-if="item.details && item.details.length" class="field-preview">
                  <div class="field-preview-head">
                    <span>已识别的申请信息</span>
                    <el-button
                      link
                      type="primary"
                      size="small"
                      @click="copyDetailsToInput(item.details)"
                    >
                      复制到输入框修改
                    </el-button>
                  </div>
                  <div class="field-preview-sentence">
                    {{ detailsToSentence(item.details) }}
                  </div>
                </div>
                <div v-if="item.tips && item.tips.length" class="tips">
                  <el-tag
                    v-for="tip in item.tips"
                    :key="tip"
                    size="small"
                    effect="plain"
                  >
                    {{ tip }}
                  </el-tag>
                </div>
              </div>
            </div>

            <div v-if="sending" class="chat-item assistant thinking-item" aria-live="polite">
              <div class="avatar">AI</div>
              <div class="bubble thinking-bubble">
                <span>正在理解你的申请并整理字段</span>
                <i></i><i></i><i></i>
              </div>
            </div>
          </div>

          <div class="input-area">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="4"
              resize="none"
              placeholder="请输入申请需求，例如：我要请假；我要报销客户接待餐费；我要申请下周出差。"
              :disabled="sending"
              @keydown.ctrl.enter="sendMessage"
            />
            <div class="input-actions">
              <span class="hint">Ctrl + Enter 发送</span>
              <el-button type="primary" :loading="sending" @click="sendMessage">
                发送
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="9">
        <el-card shadow="never" class="status-card">
          <template #header>
            <div class="card-title">
              <span>申请识别状态</span>
              <el-tag v-if="readyForConfirm" type="success">可确认</el-tag>
              <el-tag v-else type="warning">收集中</el-tag>
            </div>
          </template>

          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="当前模板">
              {{ templateName || '未识别' }}
            </el-descriptions-item>
            <el-descriptions-item label="模板ID">
              {{ templateId || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="当前阶段">
              {{ currentPhase || '-' }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="section">
            <div class="section-title">已提取信息</div>
            <el-empty
              v-if="Object.keys(extractedData).length === 0"
              description="暂无提取信息"
              :image-size="80"
            />
            <div v-else class="kv-list">
              <div
                v-for="(value, key) in extractedData"
                :key="key"
                class="kv-row"
              >
                <span class="kv-key">{{ getFieldLabel(key) }}</span>
                <span class="kv-value">{{ formatValue(value) }}</span>
              </div>
            </div>
          </div>

          <div class="section">
            <div class="section-title">缺失信息</div>
            <el-empty
              v-if="missingFields.length === 0"
              description="暂无必填缺失"
              :image-size="70"
            />
            <div v-else class="tag-list">
              <el-tag
                v-for="field in missingFields"
                :key="field"
                type="danger"
                effect="plain"
              >
                {{ getFieldLabel(field) }}
              </el-tag>
            </div>
          </div>

          <div class="section">
            <el-alert
              title="说明"
              type="info"
              :closable="false"
              show-icon
            >
              <template #default>
                Dify 负责收集和整理 OA 申请信息；真正提交前，仍需员工在平台确认窗口中核对并手动提交。
              </template>
            </el-alert>
          </div>
        </el-card>

        <el-card shadow="never" class="records-card">
          <template #header>
            <div class="card-title">
              <span>最近 OA 申请</span>
              <el-button link type="primary" @click="loadApplications">刷新</el-button>
            </div>
          </template>

          <el-table
            :data="applications"
            size="small"
            max-height="260"
            empty-text="暂无申请记录"
          >
            <el-table-column prop="application_type_name" label="类型" min-width="110" />
            <el-table-column prop="applicant_name" label="申请人" width="90" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'submitted' ? 'success' : 'info'" size="small">
                  {{ row.status === 'submitted' ? '已提交' : '草稿' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-drawer
      v-model="confirmDrawerVisible"
      size="52%"
      title="OA 申请确认页"
      destroy-on-close
    >
      <div v-if="!confirmFields.length">
        <el-empty description="暂无可确认字段" />
      </div>

      <el-form
        v-else
        label-width="130px"
        class="confirm-form"
      >
        <el-alert
          title="请核对以下信息。确认无误后，点击“保存草稿”或“确认并提交”。"
          type="warning"
          :closable="false"
          show-icon
          class="mb-16"
        />

        <el-row :gutter="12">
          <el-col
            v-for="field in confirmFields"
            :key="field.key"
            :span="field.type === 'textarea' ? 24 : 12"
          >
            <el-form-item
              :label="field.label"
              :required="field.required"
            >
              <el-input
                v-if="field.type === 'textarea'"
                v-model="confirmForm[field.key]"
                type="textarea"
                :rows="3"
                :placeholder="field.hint || `请输入${field.label}`"
              />

              <el-input-number
                v-else-if="field.type === 'number'"
                v-model="confirmForm[field.key]"
                :min="0"
                :precision="2"
                :disabled="isIdentityField(field.key)"
                style="width: 100%"
              />

              <el-select
                v-else-if="field.type === 'select'"
                v-model="confirmForm[field.key]"
                clearable
                filterable
                :disabled="isIdentityField(field.key)"
                style="width: 100%"
                :placeholder="field.hint || `请选择${field.label}`"
              >
                <el-option
                  v-for="option in field.options || []"
                  :key="option"
                  :label="option"
                  :value="option"
                />
              </el-select>

              <el-date-picker
                v-else-if="field.type === 'date'"
                v-model="confirmForm[field.key]"
                type="date"
                :disabled="isIdentityField(field.key)"
                value-format="YYYY-MM-DD"
                style="width: 100%"
                :placeholder="field.hint || `请选择${field.label}`"
              />

              <el-date-picker
                v-else-if="field.type === 'datetime'"
                v-model="confirmForm[field.key]"
                type="datetime"
                value-format="YYYY-MM-DD HH:mm"
                format="YYYY-MM-DD HH:mm"
                style="width: 100%"
                :placeholder="field.hint || `请选择${field.label}`"
              />

              <el-input
                v-else
                v-model="confirmForm[field.key]"
                :disabled="isIdentityField(field.key)"
                :placeholder="field.hint || `请输入${field.label}`"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="confirmDrawerVisible = false">取消</el-button>
          <el-button :loading="saving" @click="saveDraft">保存草稿</el-button>
          <el-button type="primary" :loading="submitting" @click="saveAndSubmit">
            确认并提交
          </el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  chatWithOaAgent,
  createOaApplication,
  listOaApplications,
  submitOaApplication,
  getOaAgentConfig,
  deleteOaAgentSession
} from '../api/index.js'

const props = defineProps({
  currentUser: { type: Object, default: null }
})

const canManageWorkflow = computed(() => {
  const permissions = props.currentUser?.permissions || []
  return permissions.includes('*') || permissions.includes('workflow.manage')
})

const workflows = ref([])
const selectedWorkflowId = ref(null)

const oaWorkflows = computed(() => workflows.value.filter((item) => item.enabled && (item.app_mode === 'advanced-chat' || String(item.endpoint || '').includes('chat-messages'))))
const selectedWorkflow = computed(() => oaWorkflows.value.find((item) => item.id === selectedWorkflowId.value) || null)

const inputText = ref('')
const sending = ref(false)
const saving = ref(false)
const submitting = ref(false)
const chatBodyRef = ref(null)

const sessionId = ref(createSessionId())
const messages = ref([
  {
    id: createMessageId(),
    role: 'assistant',
    content: `你好，${props.currentUser?.name || '员工'}。你的申请人和部门信息将自动使用当前登录账号，你只需说明“我要请假”“我要报销”“我要出差”等需求。`,
    tips: []
  }
])

const templateId = ref('')
const templateName = ref('')
const currentPhase = ref('')
const extractedData = ref({})
const missingFields = ref([])
const fieldMeta = ref({})
const submitData = ref(null)
const readyForConfirm = ref(false)
const originConversationText = ref('')

const confirmDrawerVisible = ref(false)
const confirmForm = reactive({})
const applications = ref([])

const confirmFields = computed(() => {
  if (submitData.value && submitData.value.fields) {
    return Object.entries(submitData.value.fields).map(([key, field]) => ({
      key,
      label: field.label || key,
      type: normalizeFieldType(field.type),
      required: Boolean(field.required),
      options: field.options || [],
      hint: field.hint || '',
      validation_rule: field.validation_rule || ''
    }))
  }

  return Object.entries(fieldMeta.value || {}).map(([key, field]) => ({
    key,
    label: field.label || key,
    type: normalizeFieldType(field.type),
    required: Boolean(field.required),
    options: field.options || [],
    hint: field.hint || '',
    validation_rule: field.validation_rule || ''
  }))
})

const canOpenConfirm = computed(() => {
  return readyForConfirm.value || Boolean(submitData.value)
})

onMounted(async () => {
  await loadWorkflowOptions()
  loadApplications()
})

function createSessionId() {
  return `oa_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function createMessageId() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function scrollChatToBottom() {
  nextTick(() => {
    if (chatBodyRef.value) {
      chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    }
  })
}

function addMessage(role, content, tips = [], details = []) {
  messages.value.push({
    id: createMessageId(),
    role,
    content: content || '',
    tips: tips || [],
    details: details || []
  })
  scrollChatToBottom()
}

function formatMessage(text) {
  if (!text) return ''
  return String(text)
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function detailsToSentence(details = []) {
  const text = details
    .map((detail) => `${detail.label}：${detail.value || '待补充'}`)
    .join('；')
  return text ? `${text}。` : ''
}

function copyDetailsToInput(details = []) {
  inputText.value = detailsToSentence(details).replace(/。$/, '')
  nextTick(() => scrollChatToBottom())
  ElMessage.success('申请模板已复制到输入框，可直接补充或修改')
}

function normalizeFieldType(type) {
  if (!type) return 'text'
  if (type === 'input') return 'text'
  if (type === 'text') return 'text'
  if (type === 'number') return 'number'
  if (type === 'date') return 'date'
  if (type === 'datetime' || type === 'date-time') return 'datetime'
  if (type === 'textarea') return 'textarea'
  if (type === 'select') return 'select'
  return 'text'
}

function getFieldLabel(key) {
  const meta = fieldMeta.value || {}
  if (meta[key]?.label) return meta[key].label
  if (submitData.value?.fields?.[key]?.label) return submitData.value.fields[key].label

  const fallback = {
    applicant_name: '申请人/报销人',
    department: '所属部门',
    expense_date: '费用发生日期',
    expense_type: '费用类型',
    amount: '金额',
    invoice_number: '发票张数',
    expense_description: '费用说明',
    bank_account: '收款银行账户',
    leave_type: '请假类型',
    start_time: '开始时间',
    end_time: '结束时间',
    duration_hours: '时长/小时',
    leave_reason: '请假原因',
    handover_person: '交接人',
    handover_content: '交接事项',
    destination: '出差地点',
    business_reason: '出差事由'
  }

  return fallback[key] || key
}

function isIdentityField(key) {
  return ['applicant_name', 'name', 'employee_name', 'department', 'dept'].includes(key)
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || sending.value) return

  inputText.value = ''
  addMessage('user', text)

  if (!originConversationText.value) {
    originConversationText.value = text
  } else {
    originConversationText.value += `\n${text}`
  }

  sending.value = true
  scrollChatToBottom()

  try {
    if (!selectedWorkflow.value) {
      throw new Error('请先在 Dify 应用管理中启用并选择 OA Advanced Chat 应用')
    }

    const res = await chatWithOaAgent({
      session_id: sessionId.value,
      message: text,
      workflow_id: selectedWorkflow.value.id,
      workflow_name: selectedWorkflow.value.name,
      module_key: selectedWorkflow.value.module_key || 'oa_application_agent'
    })

    const data = normalizeAgentResult(res.data)
    applyAgentResult(data)
  } catch (error) {
    console.error(error)
    const detail = error?.response?.data?.detail
    const msg = typeof detail === 'string'
      ? detail
      : detail?.message || error.message || 'OA 智能申请调用失败'

    addMessage('assistant', `调用失败：${msg}`)
    ElMessage.error(msg)
  } finally {
    sending.value = false
  }
}

function normalizeAgentResult(data) {
  return {
    reply: data.reply || data.answer || '我已收到你的申请需求。',
    application_type: data.application_type || data.template_id || '',
    application_type_name: data.application_type_name || data.template_name || '',
    template_id: data.template_id || data.application_type || '',
    template_name: data.template_name || data.application_type_name || '',
    current_phase: data.current_phase || '',
    extracted_data: data.extracted_data || {},
    missing_fields: data.missing_fields || [],
    ready_for_confirm: Boolean(data.ready_for_confirm),
    submit_ready: Boolean(data.submit_ready),
    submit_data: data.submit_data || null,
    fields: data.fields || {},
    tips: data.tips || []
  }
}

function applyAgentResult(result) {
  if (result.template_id || result.application_type) {
    templateId.value = result.template_id || result.application_type
  }

  if (result.template_name || result.application_type_name) {
    templateName.value = result.template_name || result.application_type_name
  }

  currentPhase.value = result.current_phase || currentPhase.value

  extractedData.value = {
    ...extractedData.value,
    ...(result.extracted_data || {})
  }

  if (result.fields && Object.keys(result.fields).length > 0) {
    fieldMeta.value = result.fields
  }

  missingFields.value = result.missing_fields || []
  readyForConfirm.value = Boolean(result.ready_for_confirm || result.submit_ready)

  if (result.submit_data) {
    submitData.value = result.submit_data
  }

  const details = buildStructuredDetails(result)
  addMessage('assistant', result.reply, result.tips || [], details)

  if (result.submit_ready) {
    ElMessage.success('AI 已生成 OA 申请数据，请在确认窗口核对')
    openConfirmDrawer()
  }
}

function buildStructuredDetails(result) {
  const data = {
    applicant_name: props.currentUser?.name || '',
    department: props.currentUser?.department_name || '',
    ...extractedData.value,
    ...(result.extracted_data || {})
  }

  const typeText = `${result.template_id || templateId.value || ''} ${result.template_name || templateName.value || ''}`.toLowerCase()
  let keys
  if (typeText.includes('leave') || typeText.includes('请假')) {
    keys = ['applicant_name', 'department', 'leave_type', 'start_time', 'end_time', 'duration_hours', 'leave_reason']
  } else if (typeText.includes('expense') || typeText.includes('报销') || typeText.includes('reimbursement')) {
    keys = ['applicant_name', 'department', 'expense_date', 'expense_type', 'amount', 'invoice_number', 'expense_description']
  } else if (typeText.includes('business') || typeText.includes('出差')) {
    keys = ['applicant_name', 'department', 'start_time', 'end_time', 'destination', 'business_reason']
  } else {
    keys = ['applicant_name', 'department', ...Object.keys(data).filter((key) => !['applicant_name', 'department'].includes(key)).slice(0, 6)]
  }

  const missing = new Set(result.missing_fields || [])
  const labelOverrides = {}
  if (typeText.includes('leave') || typeText.includes('请假')) labelOverrides.applicant_name = '请假人'
  if (typeText.includes('expense') || typeText.includes('报销') || typeText.includes('reimbursement')) labelOverrides.applicant_name = '报销人'

  return [...new Set(keys)].map((key) => {
    const raw = data[key]
    const pending = missing.has(key) || raw === null || raw === undefined || raw === ''
    return {
      key,
      label: labelOverrides[key] || getFieldLabel(key),
      value: pending ? '待补充' : formatValue(raw),
      pending
    }
  })
}

function openConfirmDrawer() {
  if (!canOpenConfirm.value) {
    ElMessage.warning('信息还未收集完整，暂不能生成确认页')
    return
  }

  Object.keys(confirmForm).forEach((key) => {
    delete confirmForm[key]
  })

  if (submitData.value && submitData.value.fields) {
    Object.entries(submitData.value.fields).forEach(([key, field]) => {
      confirmForm[key] = field.value ?? ''
    })
  } else {
    Object.entries(fieldMeta.value || {}).forEach(([key]) => {
      confirmForm[key] = extractedData.value[key] ?? ''
    })
  }

  if (props.currentUser) {
    if ('applicant_name' in confirmForm) confirmForm.applicant_name = props.currentUser.name || ''
    if ('department' in confirmForm) confirmForm.department = props.currentUser.department_name || ''
  }

  confirmDrawerVisible.value = true
}

function buildSubmitDataFromConfirmForm() {
  const fields = {}

  confirmFields.value.forEach((field) => {
    fields[field.key] = {
      label: field.label,
      value: confirmForm[field.key] ?? '',
      type: field.type,
      required: field.required,
      options: field.options || [],
      hint: field.hint || '',
      validation_rule: field.validation_rule || ''
    }
  })

  return {
    template_name: templateName.value,
    template_id: templateId.value,
    fields
  }
}

function buildPayload(status = 'draft') {
  const formData = JSON.parse(JSON.stringify(confirmForm))
  const finalSubmitData = buildSubmitDataFromConfirmForm()

  return {
    application_type: templateId.value || finalSubmitData.template_id || '',
    application_type_name: templateName.value || finalSubmitData.template_name || '',
    scene: 'Dify OA 智能申请',
    intent_text: originConversationText.value,
    applicant_name: props.currentUser?.name || formData.applicant_name || formData.name || formData.employee_name || '',
    department: props.currentUser?.department_name || formData.department || formData.dept || '',
    form_data: formData,
    submit_data: finalSubmitData,
    summary: buildSummary(formData),
    status,
    source: 'web_oa_agent_dify_chat',
    module_key: 'oa_application_agent',
    workflow_name: selectedWorkflow.value?.name || ''
  }
}

function buildSummary(formData) {
  const typeName = templateName.value || 'OA申请'
  const name = props.currentUser?.name || formData.applicant_name || formData.name || formData.employee_name || '员工'
  const dept = props.currentUser?.department_name || formData.department || formData.dept || ''
  return `${dept}${name}提交${typeName}`
}

async function saveDraft() {
  if (!confirmFields.value.length) {
    ElMessage.warning('暂无可保存字段')
    return
  }

  saving.value = true

  try {
    const payload = buildPayload('draft')
    await createOaApplication(payload)
    ElMessage.success('OA 申请草稿已保存')
    confirmDrawerVisible.value = false
    loadApplications()
  } catch (error) {
    console.error(error)
    ElMessage.error('保存草稿失败')
  } finally {
    saving.value = false
  }
}

async function saveAndSubmit() {
  if (!confirmFields.value.length) {
    ElMessage.warning('暂无可提交字段')
    return
  }

  await ElMessageBox.confirm(
    '确认提交该 OA 申请吗？提交后状态将变为已提交。',
    '确认提交',
    {
      confirmButtonText: '确认提交',
      cancelButtonText: '取消',
      type: 'warning'
    }
  )

  submitting.value = true

  try {
    const payload = buildPayload('draft')
    const createRes = await createOaApplication(payload)
    const id = createRes.data.application_id || createRes.data.id

    await submitOaApplication(id)

    ElMessage.success('OA 申请已提交')
    confirmDrawerVisible.value = false
    loadApplications()
    await resetConversation(false)
  } catch (error) {
    console.error(error)
    ElMessage.error('提交失败')
  } finally {
    submitting.value = false
  }
}

async function loadWorkflowOptions() {
  try {
    const res = await getOaAgentConfig()
    workflows.value = res.data || []
    const preferred = oaWorkflows.value.find((item) => item.module_key === 'oa_application_agent')
      || oaWorkflows.value.find((item) => item.name === 'OA智能申请对话Agent')
      || oaWorkflows.value[0]
    selectedWorkflowId.value = preferred?.id || null
    if (!preferred) {
      ElMessage.warning('尚未找到启用中的 OA Advanced Chat 应用，请先到 Dify 应用管理中配置')
    }
  } catch (error) {
    console.error(error)
    ElMessage.error('加载 OA Dify 应用失败')
  }
}

async function handleWorkflowChange() {
  await resetConversation(false)
  ElMessage.success('已切换 OA 对话应用并新建会话')
}

async function loadApplications() {
  try {
    const res = await listOaApplications({ limit: 20 })
    applications.value = res.data.items || []
  } catch (error) {
    console.error(error)
  }
}

async function resetConversation(showMessage = true) {
  const oldSessionId = sessionId.value
  if (oldSessionId) {
    try { await deleteOaAgentSession(oldSessionId) } catch (error) { console.debug('清理旧会话失败', error) }
  }
  sessionId.value = createSessionId()
  inputText.value = ''
  templateId.value = ''
  templateName.value = ''
  currentPhase.value = ''
  extractedData.value = {}
  missingFields.value = []
  fieldMeta.value = {}
  submitData.value = null
  readyForConfirm.value = false
  originConversationText.value = ''
  confirmDrawerVisible.value = false

  Object.keys(confirmForm).forEach((key) => {
    delete confirmForm[key]
  })

  messages.value = [
    {
      id: createMessageId(),
      role: 'assistant',
      content: `已开始新的 OA 申请。当前申请人：${props.currentUser?.name || '员工'}，部门：${props.currentUser?.department_name || '-'}。请直接描述你的需求。`,
      tips: []
    }
  ]

  if (showMessage) {
    ElMessage.success('已新建申请会话')
  }
}
</script>

<style scoped>
.oa-page {
  padding: 4px;
}

.oa-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.oa-header h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
}

.oa-header p {
  margin: 0;
  color: #6b7280;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.chat-card,
.status-card,
.records-card {
  border-radius: 12px;
}

.records-card {
  margin-top: 16px;
}

.card-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chat-body {
  height: 520px;
  overflow-y: auto;
  padding: 8px 4px 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.chat-item {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.chat-item.user {
  flex-direction: row-reverse;
}

.avatar {
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #1f2937;
  color: #fff;
  display: flex;
  justify-content: center;
  align-items: center;
  font-size: 13px;
}

.chat-item.user .avatar {
  background: #409eff;
}

.bubble {
  max-width: 76%;
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
  line-height: 1.7;
  font-size: 14px;
}

.chat-item.user .bubble {
  background: #ecf5ff;
}

.content {
  white-space: normal;
  word-break: break-word;
}

.field-preview {
  margin-top: 10px;
  overflow: hidden;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
}

.field-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 11px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

.field-preview-sentence {
  padding: 11px 12px;
  color: #24324a;
  font-size: 13px;
  line-height: 1.8;
  white-space: normal;
  word-break: break-word;
  user-select: text;
}

.thinking-bubble {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #475569;
}

.thinking-bubble span { margin-right: 3px; }
.thinking-bubble i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
  animation: oa-thinking-dot 1.25s infinite ease-in-out;
}
.thinking-bubble i:nth-child(2) { animation-delay: .15s; }
.thinking-bubble i:nth-child(3) { animation-delay: .3s; }
.thinking-bubble i:nth-child(4) { animation-delay: .45s; }
@keyframes oa-thinking-dot {
  0%, 70%, 100% { transform: translateY(0); opacity: .35; }
  35% { transform: translateY(-4px); opacity: 1; }
}

.tips {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.input-area {
  margin-top: 12px;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
}

.hint {
  color: #9ca3af;
  font-size: 13px;
}

.section {
  margin-top: 18px;
}

.section-title {
  font-weight: 600;
  margin-bottom: 10px;
}

.kv-list {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
}

.kv-row {
  display: flex;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
}

.kv-row:last-child {
  border-bottom: none;
}

.kv-key {
  width: 120px;
  padding: 8px;
  background: #f9fafb;
  color: #4b5563;
}

.kv-value {
  flex: 1;
  padding: 8px;
  color: #111827;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.confirm-form {
  padding-right: 12px;
}

.mb-16 {
  margin-bottom: 16px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>