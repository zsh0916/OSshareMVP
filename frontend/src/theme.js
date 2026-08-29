import { computed, ref } from 'vue'

const STORAGE_KEY = 'smart_office_theme'
const currentTheme = ref('dark')
let initialized = false

function resolveInitialTheme() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved === 'dark' || saved === 'light') return saved
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function applyTheme(theme) {
  const nextTheme = theme === 'light' ? 'light' : 'dark'
  currentTheme.value = nextTheme
  document.documentElement.dataset.theme = nextTheme
  document.documentElement.style.colorScheme = nextTheme
  localStorage.setItem(STORAGE_KEY, nextTheme)
}

export function initTheme() {
  if (!initialized) {
    initialized = true
    applyTheme(resolveInitialTheme())
  } else {
    applyTheme(currentTheme.value)
  }
  return currentTheme.value
}

export function setTheme(theme) {
  applyTheme(theme)
}

export function toggleTheme() {
  applyTheme(currentTheme.value === 'dark' ? 'light' : 'dark')
}

export function useTheme() {
  return {
    currentTheme,
    isDark: computed(() => currentTheme.value === 'dark'),
    initTheme,
    setTheme,
    toggleTheme
  }
}
