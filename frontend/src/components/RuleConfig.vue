<template>
  <div class="page-shell rule-management-page">
    <div class="page-title-row standardized-page-head">
      <div>
        <span class="page-kicker">ROUTING RULES</span>
        <h2>规则配置</h2>
        <p>管理关键词、群、时间、来源权重以及推送阈值。</p>
      </div>
      <div class="title-actions">
        <el-button @click="loadRules">刷新列表</el-button>
        <el-button type="primary" @click="openCreate">新增规则</el-button>
      </div>
    </div>
    <el-card class="management-card">
    <template #header>
      <div class="table-header">
        <div>
          <div class="card-header">规则配置</div>
          <div class="card-subtitle">
            管理关键词权重、群权重、时间段权重、来源权重和推送阈值
          </div>
        </div>


      </div>
    </template>

    <el-alert
      title="当前阶段：规则已保存到 SQLite。下一步会让 main.py 从数据库读取规则，替代 config.yaml。"
      type="success"
      show-icon
      style="margin-bottom: 16px"
    />

    <el-table
      :data="rules"
      border
      stripe
      v-loading="loading"
      style="width: 100%"
      height="650"
    >
      <el-table-column prop="id" label="ID" width="70" />

      <el-table-column label="规则类型" width="130">
        <template #default="{ row }">
          <el-tag :type="ruleTypeTag(row.rule_type)">
            {{ ruleTypeText(row.rule_type) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="rule_key" label="规则名称 / 关键词 / 群ID" min-width="240" />

      <el-table-column prop="weight" label="权重 / 阈值" width="120" />

      <el-table-column prop="rule_value" label="附加值" width="160" />

      <el-table-column label="启用状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">
            {{ row.enabled ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column prop="description" label="说明" min-width="220" />

      <el-table-column prop="updated_at" label="更新时间" width="180" />

      <el-table-column label="操作" min-width="250">
        <template #default="{ row }">
          <div class="row-actions">
          <el-button size="small" @click="openEdit(row)">
            编辑
          </el-button>

          <el-button
            size="small"
            :type="row.enabled ? 'warning' : 'success'"
            @click="toggleEnabled(row)"
          >
            {{ row.enabled ? '停用' : '启用' }}
          </el-button>

          <el-button size="small" type="danger" @click="removeRule(row)">
            删除
          </el-button>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑规则' : '新增规则'"
      width="680px"
    >
      <el-form label-width="140px">
        <el-form-item label="规则类型">
          <el-select v-model="form.rule_type" style="width: 100%">
            <el-option label="来源权重 source" value="source" />
            <el-option label="群权重 group" value="group" />
            <el-option label="关键词权重 keyword" value="keyword" />
            <el-option label="时间段权重 time" value="time" />
            <el-option label="推送阈值 threshold" value="threshold" />
          </el-select>
        </el-form-item>

        <el-form-item label="规则名称">
          <el-input
            v-model="form.rule_key"
            placeholder="例如：投诉、退款、oc_xxx、push_above"
          />
        </el-form-item>

        <el-form-item label="权重 / 阈值">
          <el-input-number
            v-model="form.weight"
            :min="0"
            :max="10000"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="附加值">
          <el-input
            v-model="form.rule_value"
            placeholder="可选，目前可以留空"
          />
        </el-form-item>

        <el-form-item label="说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="说明该规则的用途"
          />
        </el-form-item>

        <el-form-item label="是否启用">
          <el-switch
            v-model="form.enabled"
            :active-value="1"
            :inactive-value="0"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">
          取消
        </el-button>

        <el-button type="primary" :loading="saving" @click="saveRule">
          保存
        </el-button>
      </template>
    </el-dialog>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  getRules,
  createRule,
  updateRule,
  deleteRule
} from '../api'

const rules = ref([])
const loading = ref(false)
const saving = ref(false)

const dialogVisible = ref(false)
const isEdit = ref(false)
const currentId = ref(null)

const form = ref(emptyForm())

function emptyForm() {
  return {
    rule_type: 'keyword',
    rule_key: '',
    rule_value: '',
    weight: 10,
    enabled: 1,
    description: ''
  }
}

function ruleTypeText(type) {
  const map = {
    source: '来源权重',
    group: '群权重',
    keyword: '关键词',
    time: '时间段',
    threshold: '阈值'
  }

  return map[type] || type
}

function ruleTypeTag(type) {
  const map = {
    source: 'primary',
    group: 'success',
    keyword: 'warning',
    time: 'info',
    threshold: 'danger'
  }

  return map[type] || 'info'
}

async function loadRules() {
  loading.value = true

  try {
    const res = await getRules()
    rules.value = res.data
  } catch (e) {
    console.error(e)
    ElMessage.error('加载规则失败，请检查后端 /api/rules')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  currentId.value = null
  form.value = emptyForm()
  dialogVisible.value = true
}

function openEdit(row) {
  isEdit.value = true
  currentId.value = row.id

  form.value = {
    rule_type: row.rule_type,
    rule_key: row.rule_key,
    rule_value: row.rule_value || '',
    weight: row.weight || 0,
    enabled: row.enabled,
    description: row.description || ''
  }

  dialogVisible.value = true
}

async function saveRule() {
  if (!form.value.rule_type) {
    ElMessage.warning('请选择规则类型')
    return
  }

  if (!form.value.rule_key) {
    ElMessage.warning('请输入规则名称')
    return
  }

  saving.value = true

  try {
    if (isEdit.value) {
      await updateRule(currentId.value, form.value)
      ElMessage.success('规则已更新')
    } else {
      await createRule(form.value)
      ElMessage.success('规则已新增')
    }

    dialogVisible.value = false
    await loadRules()
  } catch (e) {
    console.error(e)
    ElMessage.error('保存失败，请检查后端接口')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row) {
  const newEnabled = row.enabled ? 0 : 1

  try {
    await updateRule(row.id, {
      enabled: newEnabled
    })

    ElMessage.success(newEnabled ? '规则已启用' : '规则已停用')
    await loadRules()
  } catch (e) {
    console.error(e)
    ElMessage.error('启停失败')
  }
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除规则「${row.rule_key}」吗？`,
      '确认删除',
      {
        type: 'warning'
      }
    )

    await deleteRule(row.id)

    ElMessage.success('规则已删除')
    await loadRules()
  } catch (e) {
    if (e !== 'cancel') {
      console.error(e)
      ElMessage.error('删除失败')
    }
  }
}

onMounted(() => {
  loadRules()
})
</script>
<style scoped>
.page-shell{display:flex;flex-direction:column;gap:20px}.standardized-page-head{display:flex;justify-content:space-between;align-items:flex-end}.page-kicker{color:var(--primary);font-size:11px;font-weight:700;letter-spacing:1.8px}.standardized-page-head h2{margin:7px 0 6px;color:var(--text);font-size:30px}.standardized-page-head p{margin:0;color:var(--muted)}.title-actions,.row-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.row-actions :deep(.el-button){margin-left:0!important}@media(max-width:800px){.standardized-page-head{align-items:flex-start;flex-direction:column}}
</style>
