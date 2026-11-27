/**
 * ExportButton — a split button that lets the user choose xlsx, csv, or pdf.
 *
 * The primary click triggers the default format (xlsx). The chevron opens a
 * dropdown with all supported formats. PDF opens in a new tab; xlsx/csv
 * trigger a browser download.
 *
 * Usage:
 *   <ExportButton
 *     formats={['xlsx', 'csv', 'pdf']}
 *     onExport={(fmt) => packingListApi.export(id, fmt)}
 *   />
 *
 * The `formats` prop controls which options appear — only list formats the
 * backend actually supports for that endpoint.
 */
import { useRef, useState, type JSX } from 'react'
import type { ExportFormat } from '../../api/client'
import { Button } from './Button'
import { Icon } from './Icon'
import styles from './ExportButton.module.css'
import { runDocument } from '../../lib/documents'

// Generic over the formats actually offered, so `formats={['xlsx', 'csv']}`
// narrows onExport's parameter to 'xlsx' | 'csv' — callers backed by endpoints
// without PDF support don't need casts.
export interface ExportButtonProps<F extends ExportFormat = ExportFormat> {
  formats: readonly F[]
  onExport: (format: F) => Promise<void>
  size?: 'sm' | 'md'
  disabled?: boolean
}

const FORMAT_LABEL: Record<ExportFormat, string> = {
  xlsx: 'Excel (.xlsx)',
  csv:  'CSV (.csv)',
  pdf:  'PDF (new tab)',
  png:  'Image (.png)',
}

const FORMAT_ICON: Record<ExportFormat, 'download' | 'arrowright'> = {
  xlsx: 'download',
  csv:  'download',
  pdf:  'arrowright',
  png:  'download',
}

export function ExportButton<F extends ExportFormat>({
  formats,
  onExport,
  size = 'md',
  disabled,
}: ExportButtonProps<F>): JSX.Element {
  const [open, setOpen] = useState(false)
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const defaultFormat = formats[0]!

  // Feedback while the file is prepared and the reason if it fails (FD-44): it used to fail without a word.
  async function handleExport(fmt: F): Promise<void> {
    setExporting(fmt)
    setOpen(false)
    try {
      await runDocument(fmt === 'pdf' ? 'the PDF' : 'the export', () => onExport(fmt))
    } finally {
      setExporting(null)
    }
  }

  return (
    <div ref={containerRef} className={styles.root}>
      <div className={styles.splitGroup}>
        {/* Primary button — triggers default format */}
        <Button
          variant="secondary"
          size={size}
          icon="download"
          loading={exporting === defaultFormat}
          disabled={disabled || exporting !== null}
          onClick={() => void handleExport(defaultFormat)}
        >
          Export
        </Button>

        {/* Chevron — opens format picker (only if multiple formats) */}
        {formats.length > 1 && (
          <button
            type="button"
            className={styles.chevron}
            disabled={disabled || exporting !== null}
            onClick={() => setOpen((o) => !o)}
            aria-label="Choose export format"
          >
            <Icon name="chevdown" size={12} color="var(--color-ink-4)" />
          </button>
        )}
      </div>

      {open && (
        <>
          {/* Click-away overlay */}
          <div className={styles.overlay} onClick={() => setOpen(false)} />
          <div className={styles.dropdown}>
            {formats.map((fmt) => (
              <button
                key={fmt}
                type="button"
                className={styles.dropdownItem}
                onClick={() => void handleExport(fmt)}
              >
                <Icon name={FORMAT_ICON[fmt]} size={14} color="var(--color-ink-3)" />
                <span>{FORMAT_LABEL[fmt]}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
