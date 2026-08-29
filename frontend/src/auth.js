import { computed, reactive } from 'vue'
import { getCurrentUser, loginAccount, logoutAccount } from './api/index.js'

const TOKEN_KEY = 'smart_office_access_token'
const USER_KEY = 'smart_office_current_user'
const RESTORE_TIMEOUT_MS = 12000

function loadStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch (error) {
    localStorage.removeItem(USER_KEY)
    return null
  }
}

export const authState = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  user: loadStoredUser(),
  ready: false
})

export const isLoggedIn = computed(() => Boolean(authState.token && authState.user))

export function hasPermission(permission) {
  const permissions = authState.user?.permissions || []
  return permissions.includes('*') || permissions.includes(permission)
}

export function persistAuth(token, user) {
  authState.token = token || ''
  authState.user = user || null

  if (token) {
    localStorage.setItem(TOKEN_KEY, token)
  } else {
    localStorage.removeItem(TOKEN_KEY)
  }

  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_KEY)
  }
}

function timeoutPromise(milliseconds) {
  return new Promise((_, reject) => {
    window.setTimeout(() => {
      reject(new Error(`登录状态恢复超时（${milliseconds / 1000}秒）`))
    }, milliseconds)
  })
}

export async function login(username, password) {
  const response = await loginAccount({ username, password })
  persistAuth(response.data.access_token, response.data.user)
  authState.ready = true
  return response.data
}

/**
 * 重新从后端获取当前用户信息并更新本地登录状态。
 * ProfileCenter 修改初始密码、修改个人信息后会调用此函数。
 */
export async function refreshCurrentUser() {
  if (!authState.token) {
    persistAuth('', null)
    authState.ready = true
    return null
  }

  try {
    const response = await getCurrentUser()
    persistAuth(authState.token, response.data)
    return response.data
  } catch (error) {
    const status = error?.response?.status

    // Token 无效或登录已过期时，清理本地状态。
    if (status === 401) {
      persistAuth('', null)
    }

    throw error
  } finally {
    authState.ready = true
  }
}

export async function restoreSession() {
  // 无 Token 时立即结束加载并显示登录页。
  if (!authState.token) {
    persistAuth('', null)
    authState.ready = true
    return null
  }

  try {
    const response = await Promise.race([
      getCurrentUser(),
      timeoutPromise(RESTORE_TIMEOUT_MS)
    ])

    persistAuth(authState.token, response.data)
    return response.data
  } catch (error) {
    console.warn('恢复登录状态失败，已返回登录页：', error)
    persistAuth('', null)
    return null
  } finally {
    // 无论后端不可达、请求超时、Token 失效或发生异常，都不能永久停在加载页。
    authState.ready = true
  }
}

export async function logout() {
  try {
    if (authState.token) {
      await logoutAccount()
    }
  } catch (error) {
    console.debug('退出接口调用失败', error)
  } finally {
    persistAuth('', null)
    authState.ready = true
  }
}

window.addEventListener('smart-office-unauthorized', () => {
  persistAuth('', null)
  authState.ready = true
})
