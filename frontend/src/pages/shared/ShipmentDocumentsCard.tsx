import { useQuery } from '@tanstack/react-query'
import { useState, type JSX } from 'react'
import { ApiError } from '../../api/client'
import { packingListKeys } from '../../api/keys'
import {
  packingListApi,
  type DocumentLang,
  type PackingList,
} from '../../api/packingList'
import { Badge, Banner, Button, Card, Mono } from '../../design/components'
import { toast } from '../../design/toast'
import { runDocument } from '../../lib/documents'
import { formatDate } from '../../lib/format'
import { STALE_30S } from '../../lib/queryClient'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ShipmentDocumentsCard.module.css'

export interface ShipmentDocumentsCardProps {
  packingList: PackingList
  /** Staff can share documents directly to the customer's WhatsApp. */
  canShareWhatsApp?: boolean
}

function LangToggle({
  name,
  ariaLabel,
  value,
  options,
  onChange,
}: {
  name: string
  ariaLabel: string
  value: DocumentLang
  options: { value: DocumentLang; label: string }[]
  onChange: (lang: DocumentLang) => void
}): JSX.Element {
  return (
    <div className={styles.langSwitch} role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt) => (
        <label
          key={opt.value}
          className={[
            styles.langOption,
            value === opt.value ? styles.langOptionActive : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <input
            type="radio"
            name={name}
            value={opt.value}
            checked={value === opt.value}
            onChange={() => onChange(opt.value)}
            className={styles.srOnly}
          />
          {opt.label}
        </label>
      ))}
    </div>
  )
}

/**
 * Independent bilingual document downloads (Loading Receipt + Packing List) with dual-format
 * PDF/PNG support, multi-page image guardrail, and optional staff WhatsApp sharing (ENG-4 & ENG-5).
 */
export function ShipmentDocumentsCard({
  packingList,
  canShareWhatsApp = false,
}: ShipmentDocumentsCardProps): JSX.Element {
  const [lrLang, setLrLang] = useState<DocumentLang>('zh')
  const [plLang, setPlLang] = useState<DocumentLang>('en')
  const [sharingDoc, setSharingDoc] = useState<'loading_receipt' | 'packing_list' | null>(null)
  const [shareError, setShareError] = useState<string | null>(null)

  const { data: docs } = useQuery({
    queryKey: [...packingListKeys.detail(packingList.id), 'documents', lrLang, plLang],
    queryFn: () =>
      packingListApi.documents(packingList.id, {
        lang_lr: lrLang,
        lang_pl: plLang,
      }),
    enabled: Boolean(packingList.id) && typeof packingListApi.documents === 'function',
    staleTime: STALE_30S,
  })

  const lrAvailable =
    docs?.loading_receipt.available ??
    (packingList.status === 'approved' && Boolean(packingList.loading_receipt_number))
  const lrRef = docs?.loading_receipt.reference ?? packingList.loading_receipt_number ?? null
  const lrPages = docs?.loading_receipt.page_count ?? 1
  const lrImageEligible = docs ? docs.loading_receipt.image_eligible : lrAvailable
  const lrDisabledReason = docs?.loading_receipt.image_disabled_reason ?? null

  const shipDate =
    docs?.packing_list.ship_date ?? packingList.ship_date ?? packingList.container_ship_date ?? null
  const etaDate =
    docs?.packing_list.estimated_arrival_date ??
    packingList.estimated_arrival_date ??
    packingList.container_eta ??
    null
  const plFinalized = docs?.packing_list.finalized ?? Boolean(shipDate)
  const plPages = docs?.packing_list.page_count ?? 1
  const plImageEligible = docs ? docs.packing_list.image_eligible : true
  const plDisabledReason = docs?.packing_list.image_disabled_reason ?? null

  const hasCustomerPhone = Boolean(
    docs?.customer_whatsapp ||
      docs?.customer_phone ||
      packingList.customer_whatsapp ||
      packingList.customer_phone,
  )

  async function handleShareWhatsApp(docType: 'loading_receipt' | 'packing_list'): Promise<void> {
    setSharingDoc(docType)
    setShareError(null)
    const lang = docType === 'loading_receipt' ? lrLang : plLang
    const label = docType === 'loading_receipt' ? 'Loading receipt' : 'Packing list'
    try {
      const res = await packingListApi.shareWhatsApp(packingList.id, {
        document_type: docType,
        lang,
      })
      toast.success(
        `${label} sent via WhatsApp (${res.format_sent === 'image' ? 'Image' : 'PDF'})`,
        res.notice ?? `Sent to ${res.recipient_phone}`,
      )
    } catch (err) {
      setShareError(err instanceof ApiError ? err.message : `Could not send ${label.toLowerCase()} on WhatsApp.`)
    } finally {
      setSharingDoc(null)
    }
  }

  return (
    <Card>
      <div className={styles.card}>
      <SectionHead
        title="Documents"
        sub="Download or share the Loading Receipt (Chinese or English) and Packing List in PDF or Image format."
      />

      {shareError && <Banner variant="error">{shareError}</Banner>}

      <div className={styles.docList}>
        {/* 1. Loading Receipt (ENG-4 / ENG-5) */}
        <div className={styles.docRow}>
          <div className={styles.docHeader}>
            <div className={styles.docTitleGroup}>
              <div className={styles.docTitleRow}>
                <span className={styles.docTitle}>Loading receipt</span>
                {lrRef && <Mono>{lrRef}</Mono>}
                <Badge variant={lrAvailable ? 'success' : 'neutral'} size="sm">
                  {lrAvailable ? 'Ready' : 'Issued on approval'}
                </Badge>
              </div>
              <span className={styles.docSub}>
                {lrAvailable
                  ? `China warehouse loading proof with full item dimensions (${lrPages} ${lrPages === 1 ? 'page' : 'pages'}).`
                  : 'Automatically generated as soon as this packing list is approved.'}
              </span>
            </div>
            <LangToggle
              name={`lr-lang-${packingList.id}`}
              ariaLabel="Loading receipt language"
              value={lrLang}
              options={[
                { value: 'zh', label: '中文' },
                { value: 'en', label: 'EN' },
              ]}
              onChange={setLrLang}
            />
          </div>

          {lrAvailable && lrDisabledReason && (
            <Banner variant="warning" title="Multi-page document — PDF only">
              {lrDisabledReason}
            </Banner>
          )}

          {lrAvailable && (
            <div className={styles.controlsRow}>
              <div className={styles.actionsGroup}>
                <Button
                  variant="secondary"
                  size="sm"
                  icon="file"
                  onClick={() =>
                    void runDocument('the loading receipt PDF', () =>
                      packingListApi.loadingReceiptPdf(packingList.id, lrLang),
                    )
                  }
                >
                  Download PDF
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  icon="download"
                  disabled={!lrImageEligible}
                  title={lrDisabledReason ?? 'Download single-page PNG image'}
                  onClick={() =>
                    void runDocument('the loading receipt image', () =>
                      packingListApi.loadingReceiptImage(packingList.id, lrLang),
                    )
                  }
                >
                  Download Image (PNG)
                </Button>
              </div>
              {canShareWhatsApp && (
                <Button
                  variant="ghost"
                  size="sm"
                  icon="arrowright"
                  loading={sharingDoc === 'loading_receipt'}
                  disabled={!hasCustomerPhone || sharingDoc !== null}
                  title={
                    !hasCustomerPhone
                      ? 'Customer has no WhatsApp or phone number on file'
                      : lrImageEligible
                        ? 'Sends as PNG Image on WhatsApp'
                        : `Multi-page (${lrPages} pages) — sends as PDF on WhatsApp`
                  }
                  onClick={() => void handleShareWhatsApp('loading_receipt')}
                >
                  Send on WhatsApp ({lrImageEligible ? 'Image' : `PDF · ${lrPages}p`})
                </Button>
              )}
            </div>
          )}
        </div>

        {/* 2. Packing List (ENG-2 / ENG-4 / ENG-5) */}
        <div className={styles.docRow}>
          <div className={styles.docHeader}>
            <div className={styles.docTitleGroup}>
              <div className={styles.docTitleRow}>
                <span className={styles.docTitle}>Packing list</span>
                {packingList.reference && <Mono>{packingList.reference}</Mono>}
                <Badge variant={plFinalized ? 'success' : 'info'} size="sm">
                  {plFinalized ? 'Finalized' : 'Preliminary'}
                </Badge>
              </div>
              <span className={styles.docSub}>
                {plFinalized
                  ? `Shipped ${formatDate(shipDate!)}${etaDate ? ` · ETA ${formatDate(etaDate)}` : ''} · ${plPages} ${plPages === 1 ? 'page' : 'pages'}.`
                  : `Pre-departure packing list — finalized with Shipping date & ETA when container moves to In transit (${plPages} ${plPages === 1 ? 'page' : 'pages'}).`}
              </span>
            </div>
            <LangToggle
              name={`pl-lang-${packingList.id}`}
              ariaLabel="Packing list language"
              value={plLang}
              options={[
                { value: 'en', label: 'EN' },
                { value: 'zh', label: '中文' },
              ]}
              onChange={setPlLang}
            />
          </div>

          {plDisabledReason && (
            <Banner variant="warning" title="Multi-page document — PDF only">
              {plDisabledReason}
            </Banner>
          )}

          <div className={styles.controlsRow}>
            <div className={styles.actionsGroup}>
              <Button
                variant="secondary"
                size="sm"
                icon="file"
                onClick={() =>
                  void runDocument('the packing list PDF', () =>
                    packingListApi.pdf(packingList.id, plLang),
                  )
                }
              >
                Download PDF
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon="download"
                disabled={!plImageEligible}
                title={plDisabledReason ?? 'Download single-page PNG image'}
                onClick={() =>
                  void runDocument('the packing list image', () =>
                    packingListApi.image(packingList.id, plLang),
                  )
                }
              >
                Download Image (PNG)
              </Button>
            </div>
            {canShareWhatsApp && (
              <Button
                variant="ghost"
                size="sm"
                icon="arrowright"
                loading={sharingDoc === 'packing_list'}
                disabled={!hasCustomerPhone || sharingDoc !== null}
                title={
                  !hasCustomerPhone
                    ? 'Customer has no WhatsApp or phone number on file'
                    : plImageEligible
                      ? 'Sends as PNG Image on WhatsApp'
                      : `Multi-page (${plPages} pages) — sends as PDF on WhatsApp`
                }
                onClick={() => void handleShareWhatsApp('packing_list')}
              >
                Send on WhatsApp ({plImageEligible ? 'Image' : `PDF · ${plPages}p`})
              </Button>
            )}
          </div>
        </div>
      </div>
      </div>
    </Card>
  )
}
