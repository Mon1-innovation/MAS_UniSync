import {Box, Button} from '@primer/react'
import {useTranslation} from 'react-i18next'
import type {SupportedLanguage} from '../i18n'

const languages: SupportedLanguage[] = ['zh', 'en']

export function LanguageSwitcher({className}: {className?: string}) {
  const {i18n, t} = useTranslation()
  const currentLanguage = i18n.resolvedLanguage === 'en' ? 'en' : 'zh'

  return (
    <Box className={className ? `language-switcher ${className}` : 'language-switcher'} role="group" aria-label={t('header.languageLabel')}>
      {languages.map((language) => {
        const isActive = currentLanguage === language
        return (
          <Button
            key={language}
            type="button"
            size="small"
            variant={isActive ? 'primary' : 'invisible'}
            aria-pressed={isActive}
            onClick={() => {
              void i18n.changeLanguage(language)
            }}
          >
            {language === 'zh' ? t('common.languageChinese') : t('common.languageEnglish')}
          </Button>
        )
      })}
    </Box>
  )
}
