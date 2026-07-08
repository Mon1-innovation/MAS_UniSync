import i18n from 'i18next'
import {initReactI18next} from 'react-i18next'
import {resources} from './resources'

export const LANGUAGE_STORAGE_KEY = 'mas_unisync_language'
export type SupportedLanguage = keyof typeof resources

export function isSupportedLanguage(value: string | null): value is SupportedLanguage {
  return value === 'zh' || value === 'en'
}

function readStoredLanguage() {
  if (typeof window === 'undefined') {
    return null
  }
  const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return isSupportedLanguage(value) ? value : null
}

i18n.use(initReactI18next).init({
  resources,
  lng: readStoredLanguage() || 'zh',
  fallbackLng: 'zh',
  interpolation: {escapeValue: false},
})

i18n.on('languageChanged', (language) => {
  if (typeof window !== 'undefined' && isSupportedLanguage(language)) {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  }
})

export {i18n}
