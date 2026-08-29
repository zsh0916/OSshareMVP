<template>
  <div class="page-shell workflow-page">
    <div class="page-title-row standardized-page-head">
      <div>
        <span class="page-kicker">DIFY APPLICATIONS</span>
        <h2>Dify 应用管理</h2>
        <p>统一管理应用模式、模块绑定、API Key、超时与调用方式。</p>
      </div>
      <div class="title-actions">
        <el-button @click="loadWorkflows">刷新列表</el-button>
        <el-button type="primary" @click="openCreate">新增应用</el-button>
      </div>
    </div>

    <el-card class="management-card">
    <template #header>
      <div class="table-header">
        <div>
          <div class="card-header">Dify 应用管理</div>
          <div class="card-subtitle">每个 Dify 应用独立配置 API Key、应用模式、模块绑定、超时和调用方式。</div>
        </div>

      </div>
    </template>

    <el-alert
      title="Workflow 与 Advanced Chat 使用不同请求格式；平台会根据“应用模式”自动选择 /workflows/run 或 /chat-messages。"
      type="success"
      show-icon
      style="margin-bottom: 16px"
    />

    <el-table class="workflow-table" :data="workflows" border stripe v-loading="loading" style="width: 100%">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="应用名称" min-width="170" />
      <el-table-column label="应用模式" width="140">
        <template #default="{ row }">
          <el-tag :type="row.app_mode === 'advanced-chat' ? 'success' : 'primary'">
            {{ row.app_mode === 'advanced-chat' ? 'Advanced Chat' : 'Workflow' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="module_key" label="模块绑定" min-width="170" />
      <el-table-column prop="api_base" label="API Base" min-width="210" />
      <el-table-column prop="endpoint" label="Endpoint" width="150" />
      <el-table-column prop="timeout_seconds" label="超时/秒" width="90" />
      <el-table-column prop="api_key_masked" label="API Key" width="170" />
      <el-table-column label="状态" width="85">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="说明" min-width="320" show-overflow-tooltip />
      <el-table-column label="操作" min-width="310">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="primary" @click="openTest(row)">测试</el-button>
            <el-button size="small" :type="row.enabled ? 'warning' : 'success'" @click="toggleEnabled(row)">
              {{ row.enabled ? '停用' : '启用' }}
            </el-button>
            <el-button size="small" type="danger" @click="removeWorkflow(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && workflows.length === 0" description="暂无 Dify 应用配置" />

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑 Dify 应用' : '新增 Dify 应用'" width="760px">
      <el-form label-width="130px">
        <el-form-item label="应用名称"><el-input v-model="form.name" placeholder="例如：OA智能申请对话Agent" /></el-form-item>
        <el-form-item label="应用模式">
          <el-select v-model="form.app_mode" style="width: 100%" @change="handleModeChange">
            <el-option label="Dify Workflow" value="workflow" />
            <el-option label="Dify Advanced Chat / Chatbot" value="advanced-chat" />
          </el-select>
        </el-form-item>
        <el-form-item label="模块绑定">
          <el-select v-model="form.module_key" clearable filterable allow-create style="width: 100%" placeholder="一个业务模块绑定一条启用配置">
            <el-option label="飞书消息分流" value="feishu_message_router" />
            <el-option label="OA 智能申请对话" value="oa_application_agent" />
            <el-option label="OA 意图识别" value="oa_application_intent" />
            <el-option label="内部文档检索" value="document_search" />
            <el-option label="会议纪要" value="meeting_minutes" />
            <el-option label="员工考核出题与批阅" value="employee_assessment" />
            <el-option label="员工考核评估与培训建议" value="employee_assessment_analysis" />
            <el-option label="日报与阶段报表" value="report_generate" />
          </el-select>
        </el-form-item>
        <el-form-item label="API Base"><el-input v-model="form.api_base" placeholder="http://192.168.88.100/v1" /></el-form-item>
        <el-form-item label="Endpoint"><el-input v-model="form.endpoint" :placeholder="modeEndpoint" /></el-form-item>
        <el-form-item label="API Key"><el-input v-model="form.api_key" show-password placeholder="新增时必填；编辑留空表示不修改" /></el-form-item>
        <el-form-item label="超时时间">
          <el-input-number v-model="form.timeout_seconds" :min="30" :max="900" :step="30" />
          <span class="form-tip">高级对话建议 300 秒</span>
        </el-form-item>
        <el-form-item v-if="form.app_mode === 'advanced-chat'" label="响应方式">
          <el-radio-group v-model="form.response_mode">
            <el-radio value="streaming">流式（推荐）</el-radio>
            <el-radio value="blocking">阻塞</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="使用系统代理">
          <el-switch v-model="form.use_system_proxy" :active-value="1" :inactive-value="0" />
          <span class="form-tip">内网 Dify 建议关闭，避免 192.168.x.x 被代理转发</span>
        </el-form-item>
        <el-form-item label="校验 HTTPS 证书"><el-switch v-model="form.verify_ssl" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="输入字段说明"><el-input v-model="form.input_schema_json" type="textarea" :rows="6" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="是否启用"><el-switch v-model="form.enabled" :active-value="1" :inactive-value="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveWorkflow">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="testDialogVisible" title="测试 Dify 应用" width="860px">
      <el-alert
        :title="`正在测试：${testingWorkflow?.name || ''}（${testingWorkflow?.app_mode || ''}）`"
        type="info"
        show-icon
        style="margin-bottom: 12px"
      />
      <template v-if="testingWorkflow?.app_mode === 'advanced-chat'">
        <div class="card-subtitle field-title">对话内容 query：</div>
        <el-input v-model="testQuery" type="textarea" :rows="4" placeholder="例如：你好，或完整的 OA 申请内容" />
      </template>
      <div class="card-subtitle field-title">inputs JSON：</div>
      <el-input v-model="testInputsText" type="textarea" :rows="8" />
      <div style="margin-top: 12px"><el-button type="primary" :loading="testing" @click="submitTest">运行测试</el-button></div>
      <el-divider />
      <div class="card-subtitle field-title">返回结果：</div>
      <pre class="json-preview">{{ testResultText }}</pre>
    </el-dialog>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createWorkflow, deleteWorkflow, getWorkflows, testWorkflow, updateWorkflow } from '../api'

const workflows = ref([])
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const dialogVisible = ref(false)
const testDialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref(null)
const testingWorkflow = ref(null)
const form = ref(emptyForm())
const testInputsText = ref('{}')
const testQuery = ref('')
const testResultText = ref('暂无结果')

const modeEndpoint = computed(() => form.value.app_mode === 'advanced-chat' ? '/chat-messages' : '/workflows/run')

function emptyForm() {
  return {
    name: '', workflow_type: 'dify', app_mode: 'workflow', module_key: '',
    api_base: 'http://127.0.0.1/v1', api_key: '', endpoint: '/workflows/run',
    timeout_seconds: 300, response_mode: 'auto', verify_ssl: 1, use_system_proxy: 0,
    description: '', input_schema_json: '{}', enabled: 1
  }
}

function handleModeChange(mode) {
  form.value.endpoint = mode === 'advanced-chat' ? '/chat-messages' : '/workflows/run'
  form.value.response_mode = mode === 'advanced-chat' ? 'streaming' : 'blocking'
  if (mode === 'advanced-chat' && form.value.timeout_seconds < 120) form.value.timeout_seconds = 300
}

async function loadWorkflows() {
  loading.value = true
  try { workflows.value = (await getWorkflows()).data }
  catch (e) { console.error(e); ElMessage.error('加载 Dify 应用失败') }
  finally { loading.value = false }
}

function openCreate() { isEdit.value = false; currentId.value = null; form.value = emptyForm(); dialogVisible.value = true }
function openEdit(row) {
  isEdit.value = true; currentId.value = row.id
  form.value = {
    name: row.name, workflow_type: row.workflow_type || 'dify', app_mode: row.app_mode || 'workflow',
    module_key: row.module_key || '', api_base: row.api_base, api_key: '', endpoint: row.endpoint,
    timeout_seconds: row.timeout_seconds || 300, response_mode: row.response_mode || 'auto',
    verify_ssl: row.verify_ssl ?? 1, use_system_proxy: row.use_system_proxy ?? 0,
    description: row.description || '', input_schema_json: row.input_schema_json || '{}', enabled: row.enabled
  }
  dialogVisible.value = true
}

async function saveWorkflow() {
  if (!form.value.name || !form.value.api_base || !form.value.endpoint) return ElMessage.warning('请填写名称、API Base 和 Endpoint')
  if (!isEdit.value && !form.value.api_key) return ElMessage.warning('新增应用时必须填写 API Key')
  try {
    JSON.parse(form.value.input_schema_json || '{}')
  } catch { return ElMessage.error('输入字段说明必须是合法 JSON') }
  saving.value = true
  try {
    if (isEdit.value) await updateWorkflow(currentId.value, form.value)
    else await createWorkflow(form.value)
    ElMessage.success(isEdit.value ? '应用配置已更新' : '应用配置已创建')
    dialogVisible.value = false
    await loadWorkflows()
  } catch (e) { console.error(e); ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}

async function toggleEnabled(row) {
  try { await updateWorkflow(row.id, { enabled: row.enabled ? 0 : 1 }); await loadWorkflows(); ElMessage.success('状态已更新') }
  catch (e) { console.error(e); ElMessage.error('启停失败') }
}

async function removeWorkflow(row) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.name}」吗？`, '确认删除', { type: 'warning' })
    await deleteWorkflow(row.id); await loadWorkflows(); ElMessage.success('已删除')
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

function openTest(row) {
  testingWorkflow.value = row
  testResultText.value = '暂无结果'
  testQuery.value = row.app_mode === 'advanced-chat' ? '你好' : ''
  try {
    const schema = JSON.parse(row.input_schema_json || '{}')
    testInputsText.value = JSON.stringify(schema, null, 2)
  } catch { testInputsText.value = '{}' }
  testDialogVisible.value = true
}

async function submitTest() {
  let inputs
  try { inputs = JSON.parse(testInputsText.value || '{}') }
  catch { return ElMessage.error('inputs 不是合法 JSON') }
  if (testingWorkflow.value?.app_mode === 'advanced-chat' && !testQuery.value.trim()) return ElMessage.warning('请输入测试对话内容')
  testing.value = true; testResultText.value = '测试中...'
  try {
    const res = await testWorkflow(testingWorkflow.value.id, { inputs, query: testQuery.value, user: 'web-test-user' })
    testResultText.value = JSON.stringify(res.data, null, 2)
    res.data.success ? ElMessage.success('测试成功') : ElMessage.warning('测试失败，请查看返回内容')
  } catch (e) {
    console.error(e); testResultText.value = JSON.stringify(e?.response?.data || { message: e.message }, null, 2); ElMessage.error('测试异常')
  } finally { testing.value = false }
}

onMounted(loadWorkflows)
</script>

<style scoped>
.json-preview { background: #101828; color: #d0d5dd; padding: 16px; border-radius: 8px; max-height: 420px; overflow: auto; white-space: pre-wrap; font-family: Consolas, Monaco, monospace; }
.form-tip { margin-left: 12px; color: #667085; font-size: 12px; }
.field-title { margin: 12px 0 8px; }
</style>
