<template>
  <div class="page-shell">
    <div class="page-title-row">
      <div>
        <span class="page-kicker">ACCOUNT & PERMISSION</span>
        <h2>员工与权限</h2>
        <p>员工数据来自 employee_info.csv，可在此调整角色、部门与账号状态。</p>
      </div>
      <el-button type="primary" @click="loadData">刷新数据</el-button>
    </div>

    <section class="filter-card">
      <el-input v-model="keyword" clearable placeholder="搜索姓名、工号、岗位或邮箱" style="width: 320px" @keyup.enter="search" />
      <el-select v-model="departmentId" clearable placeholder="全部部门" style="width: 170px" @change="search">
        <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>
      <el-select v-model="roleCode" clearable placeholder="全部角色" style="width: 170px" @change="search">
        <el-option v-for="item in roles" :key="item.code" :label="item.name" :value="item.code" />
      </el-select>
      <el-button @click="search">查询</el-button>
    </section>

    <section class="table-card" v-loading="loading">
      <el-table :data="items" empty-text="暂无员工数据">
        <el-table-column prop="employee_id" label="工号" width="90" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column prop="department_name" label="部门" width="120" />
        <el-table-column prop="position" label="岗位" min-width="170" />
        <el-table-column prop="email" label="邮箱" min-width="210" />
        <el-table-column prop="role_name" label="角色" width="120">
          <template #default="{ row }"><span class="role-pill" :class="row.role_code">{{ row.role_name }}</span></template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="90">
          <template #default="{ row }"><span :class="row.is_active ? 'active-text' : 'disabled-text'">{{ row.is_active ? '启用' : '停用' }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="resetPassword(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-row"><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="loadData" /></div>
    </section>

    <el-dialog v-model="editVisible" title="编辑员工权限" width="560px">
      <el-form v-if="editing" label-width="100px">
        <el-form-item label="员工"><el-input :model-value="`${editing.employee_id} · ${editing.name}`" disabled /></el-form-item>
        <el-form-item label="岗位"><el-input v-model="editForm.position" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="editForm.email" /></el-form-item>
        <el-form-item label="部门">
          <el-select v-model="editForm.department_id" style="width:100%"><el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id" /></el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role_code" style="width:100%"><el-option v-for="item in roles" :key="item.code" :label="item.name" :value="item.code" /></el-select>
        </el-form-item>
        <el-form-item label="账号状态"><el-switch v-model="editForm.is_active" :active-value="1" :inactive-value="0" active-text="启用" inactive-text="停用" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDepartments, getRoles, getUsers, resetUserPassword, updateUser } from '../api/index.js'

const loading=ref(false),saving=ref(false),items=ref([]),total=ref(0),page=ref(1),keyword=ref(''),departmentId=ref(null),roleCode=ref('')
const pageSize=30
const departments=ref([]),roles=ref([]),editVisible=ref(false),editing=ref(null)
const editForm=reactive({role_code:'employee',is_active:1,department_id:null,position:'',email:''})

onMounted(async()=>{await Promise.all([loadMeta(),loadData()])})
async function loadMeta(){const [d,r]=await Promise.all([getDepartments(),getRoles()]);departments.value=d.data||[];roles.value=r.data||[]}
async function loadData(){loading.value=true;try{const res=await getUsers({page:page.value,page_size:pageSize,keyword:keyword.value,department_id:departmentId.value||undefined,role_code:roleCode.value||undefined});items.value=res.data.items||[];total.value=res.data.total||0}finally{loading.value=false}}
function search(){page.value=1;loadData()}
function openEdit(row){editing.value=row;Object.assign(editForm,{role_code:row.role_code,is_active:Number(row.is_active),department_id:row.department_id,position:row.position||'',email:row.email||''});editVisible.value=true}
async function saveEdit(){saving.value=true;try{await updateUser(editing.value.id,{...editForm});ElMessage.success('员工信息已更新');editVisible.value=false;await loadData()}catch(error){ElMessage.error(error.response?.data?.detail||'保存失败')}finally{saving.value=false}}
async function resetPassword(row){try{await ElMessageBox.confirm(`确定重置 ${row.name} 的密码吗？`,'重置密码',{type:'warning'});const res=await resetUserPassword(row.id,{});await ElMessageBox.alert(`临时密码：${res.data.temporary_password}\n员工首次登录后必须修改密码。`,'密码已重置',{confirmButtonText:'我已记录'});}catch(error){if(error!=='cancel'&&error!=='close')ElMessage.error(error.response?.data?.detail||'重置失败')}}
</script>

<style scoped>
.page-shell{display:flex;flex-direction:column;gap:20px}.page-title-row{display:flex;justify-content:space-between;align-items:flex-end}.page-kicker{color:#6f8dff;font-size:11px;letter-spacing:2px}h2{color:#f8fafc;margin:7px 0 6px;font-size:28px}.page-title-row p{color:#727d91;margin:0}.filter-card,.table-card{border:1px solid #202638;background:#10131d;border-radius:18px}.filter-card{padding:16px;display:flex;gap:10px}.table-card{padding:14px}.pagination-row{display:flex;justify-content:flex-end;padding:18px 4px 4px}.role-pill{display:inline-flex;padding:4px 9px;border-radius:999px;font-size:11px;background:#252b3b;color:#aab4c4}.role-pill.department_manager{background:rgba(128,91,255,.14);color:#a98dff}.role-pill.platform_admin,.role-pill.super_admin{background:rgba(75,111,255,.14);color:#86a1ff}.active-text{color:#45d6a6}.disabled-text{color:#ef7084}@media(max-width:900px){.page-title-row{flex-direction:column;align-items:flex-start;gap:14px}.filter-card{flex-wrap:wrap}}
</style>
