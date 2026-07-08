export const resources = {
  zh: {
    translation: {
      common: {
        cancel: '取消',
        loading: '加载中',
        languageChinese: '中文',
        languageEnglish: 'English',
      },
      header: {
        guest: '访客',
        signOut: '退出登录',
        languageLabel: '语言',
      },
      login: {
        intro: '使用你的 Flarum 账号登录。',
        failedTitle: '登录失败',
        invalidCredentials: 'Flarum 凭据无效。',
        genericError: '无法登录，请稍后重试。',
        accountLabel: 'Flarum 账号或邮箱',
        passwordLabel: '密码',
        submit: '登录',
      },
    },
  },
  en: {
    translation: {
      common: {
        cancel: 'Cancel',
        loading: 'Loading',
        languageChinese: '中文',
        languageEnglish: 'English',
      },
      header: {
        guest: 'Guest',
        signOut: 'Sign out',
        languageLabel: 'Language',
      },
      login: {
        intro: 'Sign in with your Flarum account.',
        failedTitle: 'Sign in failed',
        invalidCredentials: 'Flarum credentials are invalid.',
        genericError: 'Unable to sign in. Please try again.',
        accountLabel: 'Flarum account or email',
        passwordLabel: 'Password',
        submit: 'Sign in',
      },
    },
  },
} as const
