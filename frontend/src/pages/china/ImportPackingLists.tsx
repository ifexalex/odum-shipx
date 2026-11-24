import { useRef, useState, type ChangeEvent, type DragEvent, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { excelApi, type ImportErrorDetail, type ImportResult, type ManifestImportResult } from '../../api/excel'
import { FileTooLargeError, UploadFailedError, uploadImportFile } from '../../api/uploads'
import { Banner, Button, Card, Icon, Mono, Pressable, Select, FileInput, Stepper, Table } from '../../design/components'
import { useContainerLookup } from '../../hooks/useContainers'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ImportPackingLists.module.css'
import { plural } from '../../lib/format'

/**
 * Two genuinely different import shapes share this wizard:
 *
 * - `manifest`  — the forwarder's own export (the file staff actually receive).
 *                 The container comes from the file's "PARTIAL NO" header, and
 *                 containers/customers/packing lists are created as needed.
 * - `template`  — a filled ShipX packing-list template, imported against a
 *                 container the user picks, with customers that must already exist.
 */
type ImportMode = 'manifest' | 'template'

interface WizardStepsProps {
  current: 1 | 2 | 3
}

/** The import's three steps (FD-09: the shared Stepper in wizard mode). */
function WizardSteps({ current, mode }: WizardStepsProps & { mode: ImportMode }): JSX.Element {
  const steps = [
    { key: 'upload', label: 'Upload file', sub: mode === 'manifest' ? 'Pick the .xlsx manifest' : 'Pick container + .xlsx' },
    { key: 'confirm', label: 'Confirm import', sub: 'Create packing lists' },
    { key: 'results', label: 'Results', sub: 'Per-row outcome' },
  ]
  return (
    <Card padding="default">
      <Stepper mode="wizard" steps={steps} current={current - 1} complete={current === 3} label="Import steps" />
    </Card>
  )
}

/** The rows an import skipped and why. Manifest imports also name the sheet each row came from. */
function SkippedRowsTable({ details, showSheet }: { details: ImportErrorDetail[]; showSheet: boolean }): JSX.Element {
  return (
    <div className={styles.errorSection}>
      <Card padding="none">
        <div className={styles.tableHead}>
          <SectionHead title="Skipped rows" sub={`${details.length} ${details.length === 1 ? 'row' : 'rows'} skipped`} />
        </div>
        <Table
          columns={[
            { title: 'Row', type: 'number' },
            ...(showSheet ? [{ title: 'Sheet' }] : []),
            { title: 'Field' },
            { title: 'Value' },
            { title: 'Reason' },
          ]}
          rows={details.map((detail) => ({
            cells: [
              <Mono key="row">{detail.row}</Mono>,
              ...(showSheet ? [<span key="sheet">{detail.sheet ?? '—'}</span>] : []),
              <span key="field">{detail.field}</span>,
              <span key="value">{detail.value}</span>,
              <span key="reason">{detail.error}</span>,
            ],
          }))}
        />
      </Card>
    </div>
  )
}

export function ImportPackingLists(): JSX.Element {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [mode, setMode] = useState<ImportMode>('manifest')
  const containerLookup = useContainerLookup({ status: 'loading' })
  const containers = containerLookup.data?.data ?? []
  const [containerId, setContainerId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [importing, setImporting] = useState(false)
  const [actionError, setError] = useState<string | null>(null)
  const loadError = containerLookup.error
    ? containerLookup.error instanceof ApiError
      ? containerLookup.error.message
      : 'Could not load containers.'
    : null
  const error = actionError ?? loadError
  const [result, setResult] = useState<ImportResult | null>(null)
  const [manifestResult, setManifestResult] = useState<ManifestImportResult | null>(null)

  const selectedContainer = containers.find((c) => c.id === containerId)

  function handleFileChange(event: ChangeEvent<HTMLInputElement>): void {
    const picked = event.target.files?.[0]
    if (picked) setFile(picked)
  }

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault()
    setDragging(false)
    const dropped = event.dataTransfer.files[0]
    if (dropped) setFile(dropped)
  }

  async function handleConfirmImport(): Promise<void> {
    // Manifest imports carry their own container, so only the template mode
    // needs one selected here.
    if (!file || (mode === 'template' && !containerId)) return
    setImporting(true)
    setError(null)
    try {
      const fileKey = await uploadImportFile(file)
      if (mode === 'manifest') {
        setManifestResult(await excelApi.importManifest(fileKey))
      } else {
        setResult(await excelApi.importPackingList(containerId, fileKey))
      }
      setStep(3)
    } catch (err) {
      if (err instanceof UploadFailedError || err instanceof FileTooLargeError) {
        setError(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Import failed.')
      }
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className={styles.wrap}>
      <PageHeader
        title="Import from Excel"
        meta="Bring a container’s cargo into ShipX in one pass — either your forwarder’s own manifest export, or a filled ShipX template."
      />

      <WizardSteps current={step} mode={mode} />
      <div className={styles.spacer} />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't import">{error}</Banner>
        </div>
      )}

      {step === 1 && (
        <Card padding="large">
          <SectionHead
            title="What are you importing?"
            sub="Pick the kind of file you have, then upload it."
          />
          <div className={styles.spacerLg} />

          <div className={styles.modeGrid} role="radiogroup" aria-label="Import type">
            {([
              {
                value: 'manifest' as const,
                title: 'Forwarder manifest',
                sub: 'The export your shipping agent sends you. ShipX reads the container from the file and creates any customers it doesn’t already have.',
              },
              {
                value: 'template' as const,
                title: 'ShipX packing-list template',
                sub: 'A blank template you filled in yourself. You pick the container, and every customer must already exist in ShipX.',
              },
            ]).map((option) => (
              <Pressable
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                className={[styles.modeCard, mode === option.value ? styles.modeCardActive : ''].join(' ')}
                onClick={() => setMode(option.value)}
              >
                <span className={styles.modeRadio} aria-hidden="true">
                  {mode === option.value && <Icon name="check" size={12} stroke={3} color="#fff" />}
                </span>
                <span className={styles.modeText}>
                  <span className={styles.modeTitle}>{option.title}</span>
                  <span className={styles.modeSub}>{option.sub}</span>
                </span>
              </Pressable>
            ))}
          </div>

          {mode === 'manifest' ? (
            <div className={styles.banner}>
              <Banner variant="info" title="No container needed">
                The container is read from the manifest’s own <strong>PARTIAL NO</strong> heading. If ShipX
                doesn’t have that container yet, it will be created along with any missing customers.
              </Banner>
            </div>
          ) : (
          <div className={styles.selectField}>
            <Select label="Container"
              id="importContainerSelect"
              value={containerId}
              onChange={(event) => setContainerId(event.target.value)}
            >
              <option value="">Select a container…</option>
              {containers.map((container) => (
                <option key={container.id} value={container.id}>
                  {container.container_number}
                </option>
              ))}
            </Select>
          </div>
          )}

          <div
            className={[styles.dropzone, dragging ? styles.dropzoneActive : ''].join(' ')}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className={styles.dropzoneIcon}>
              <Icon name="upload" size={24} stroke={2.5} color="#fff" />
            </div>
            <div className={styles.dropzoneTitle}>Drag &amp; drop your .xlsx file here</div>
            <div className={styles.dropzoneSub}>or click to browse · .xlsx only, up to 5 MB</div>
            <FileInput ref={fileInputRef} label="Choose .xlsx file" accept=".xlsx" onChange={handleFileChange} />
          </div>

          {file && (
            <div className={styles.selectedFile}>
              <div className={styles.selectedFileIcon}>
                <Icon name="file" size={18} />
              </div>
              <div className={styles.selectedFileText}>
                <div className={styles.selectedFileName}>{file.name}</div>
                <div className={styles.selectedFileMeta}>{(file.size / 1024).toFixed(0)} KB</div>
              </div>
              <Icon name="check" size={18} color="var(--color-success)" stroke={2.5} />
              <Button variant="ghost" size="sm" onClick={() => setFile(null)}>
                Remove
              </Button>
            </div>
          )}

          <div className={styles.actionsRow}>
            <Button variant="ghost" onClick={() => navigate('/packing-lists')}>
              Cancel
            </Button>
            <Button
              variant="primary"
              trailingIcon="arrowright"
              disabled={!file || (mode === 'template' && !containerId)}
              onClick={() => setStep(2)}
            >
              Next: Confirm
            </Button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <>
          <Card>
            <SectionHead title="Confirm import" sub="Review before importing — this happens in a single step." />
            <div className={styles.spacerLg} />
            <div className={styles.summaryRow}>
              <span className={styles.summaryLabel}>Container</span>
              {mode === 'manifest' ? (
                <span className={styles.summaryMuted}>Read from the file</span>
              ) : (
                <Mono>{selectedContainer?.container_number ?? '—'}</Mono>
              )}
            </div>
            <div className={styles.summaryRow}>
              <span className={styles.summaryLabel}>File</span>
              <span>{file?.name}</span>
            </div>
            <div className={styles.spacerLg} />
            {mode === 'manifest' ? (
              <Banner variant="info" title="How manifest import works">
                ShipX reads every sheet in the workbook, creates the container from its <strong>PARTIAL NO</strong>
                {' '}heading if it doesn’t exist, and adds any customers it doesn’t recognise (matched on
                phone number). Packing lists are created in <strong>pending approval</strong> — ready for a second
                person to approve — so a large import doesn't leave every row needing an individual submit first.
                Importing the same file twice is safe — rows already present are counted as
                duplicates rather than added again.
              </Banner>
            ) : (
              <Banner variant="info" title="How import works">
                ShipX parses the file and creates one pending-approval packing list per customer found in it. Rows with errors
                (unknown customer, invalid number/date, etc.) are skipped automatically and listed in the results —
                there’s no preview step before committing, and no way to selectively skip rows; that decision is
                made row-by-row by the backend.
              </Banner>
            )}
          </Card>
          <div className={styles.actionsRow}>
            <Button variant="ghost" icon="arrowleft" onClick={() => setStep(1)}>
              Back: Upload
            </Button>
            <Button variant="primary" icon="check" loading={importing} onClick={() => void handleConfirmImport()}>
              Confirm &amp; import
            </Button>
          </div>
        </>
      )}

      {step === 3 && manifestResult && (
        <>
          <Card>
            <SectionHead
              title="Import complete"
              sub={`${plural(manifestResult.items_created, 'item')} added across ${plural(manifestResult.packing_lists_created, 'packing list')}, ready for approval`}
            />
            <div className={styles.spacerLg} />
            <div className={styles.statsGrid}>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Rows read</div>
                <div className={styles.statValue}>{manifestResult.total_rows}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Items added</div>
                <div className={styles.statValue}>{manifestResult.items_created}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Already imported</div>
                <div className={styles.statValue}>{manifestResult.items_skipped_duplicate}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Skipped (errors)</div>
                <div className={styles.statValue}>{manifestResult.errors}</div>
              </div>
            </div>
            <div className={styles.spacerLg} />
            <SectionHead title="Created for you" sub="Records ShipX added because they weren’t here yet" />
            <div className={styles.spacerLg} />
            <div className={styles.statsGrid}>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Containers</div>
                <div className={styles.statValue}>{manifestResult.containers_created}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Customers</div>
                <div className={styles.statValue}>{manifestResult.customers_created}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Packing lists</div>
                <div className={styles.statValue}>{manifestResult.packing_lists_created}</div>
              </div>
            </div>
            {manifestResult.items_skipped_duplicate > 0 && manifestResult.items_created === 0 && (
              <>
                <div className={styles.spacerLg} />
                <Banner variant="info" title="Nothing new to add">
                  Every row in this file was already imported, so nothing was duplicated.
                </Banner>
              </>
            )}
          </Card>

          {manifestResult.error_details.length > 0 && (
            <SkippedRowsTable details={manifestResult.error_details} showSheet />
          )}

          <div className={styles.actionsRow}>
            <Button
              variant="secondary"
              icon="upload"
              onClick={() => {
                setStep(1)
                setFile(null)
                setManifestResult(null)
              }}
            >
              Import another file
            </Button>
            <Button variant="secondary" onClick={() => navigate('/containers')}>
              View containers
            </Button>
            <Button
              variant="primary"
              trailingIcon="arrowright"
              onClick={() => navigate('/packing-lists?status=pending_approval')}
            >
              Review pending lists
            </Button>
          </div>
        </>
      )}

      {step === 3 && result && (
        <>
          <Card>
            <SectionHead title="Import complete" sub={`${plural(result.packing_lists_created, 'packing list')} ready for approval`} />
            <div className={styles.spacerLg} />
            <div className={styles.statsGrid}>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Total rows</div>
                <div className={styles.statValue}>{result.total_rows}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Imported</div>
                <div className={styles.statValue}>{result.imported}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Skipped (errors)</div>
                <div className={styles.statValue}>{result.errors}</div>
              </div>
              <div className={styles.statTile}>
                <div className={styles.statLabel}>Packing lists</div>
                <div className={styles.statValue}>{result.packing_lists_created}</div>
              </div>
            </div>
          </Card>

          {result.error_details.length > 0 && <SkippedRowsTable details={result.error_details} showSheet={false} />}

          <div className={styles.actionsRow}>
            <Button variant="secondary" icon="upload" onClick={() => { setStep(1); setFile(null); setResult(null) }}>
              Import another file
            </Button>
            <Button variant="primary" trailingIcon="arrowright" onClick={() => navigate('/packing-lists')}>
              View packing lists
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
