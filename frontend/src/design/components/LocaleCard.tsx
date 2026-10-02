/**
 * LocaleCard — notification language selector (EN / ZH).
 *
 * Used on:
 *   - StaffUserDetail (admin sets locale for any user)
 *   - StaffProfile (user sets their own locale via PATCH /v1/tenant/me)
 *
 * Controls notification template language only — not the UI language.
 */
import type { JSX } from 'react'
import { Banner, Mono } from './index'
import styles from './LocaleCard.module.css'

export type StaffLocale = 'en' | 'zh'

export interface LocaleCardProps {
  value: StaffLocale
  onChange: (locale: StaffLocale) => void
}

interface LangOptionProps {
  locale: StaffLocale
  label: string
  sub: string
  active: boolean
  onSelect: () => void
}

function LangOption({ locale, label, sub, active, onSelect }: LangOptionProps): JSX.Element {
  return (
    <label
      htmlFor={`locale-${locale}`}
      className={[styles.option, active ? styles.optionActive : ''].filter(Boolean).join(' ')}
    >
      <input
        id={`locale-${locale}`}
        type="radio"
        name="locale"
        value={locale}
        checked={active}
        onChange={onSelect}
        className={styles.radio}
      />
      <span className={[styles.radioCircle, active ? styles.radioCircleActive : ''].filter(Boolean).join(' ')}>
        {active && <span className={styles.radioDot} />}
      </span>
      <div>
        <div className={styles.optionLabel}>{label}</div>
        <div className={styles.optionSub}>{sub}</div>
      </div>
    </label>
  )
}

export function LocaleCard({ value, onChange }: LocaleCardProps): JSX.Element {
  return (
    <div className={styles.root}>
      <div className={styles.options}>
        <LangOption
          locale="en"
          label="English"
          sub="EN — default"
          active={value === 'en'}
          onSelect={() => onChange('en')}
        />
        <LangOption
          locale="zh"
          label="中文 (简体)"
          sub="ZH — Simplified Chinese"
          active={value === 'zh'}
          onSelect={() => onChange('zh')}
        />
      </div>
      <div className={styles.banner}>
        <Banner variant="info" icon="info">
          Maps to <Mono color="var(--color-info-strong)">tenant_user.locale</Mono>. Notification
          templates render in the selected language where a ZH template exists.
        </Banner>
      </div>
    </div>
  )
}
