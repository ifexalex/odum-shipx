import { useRef, useState, type ChangeEvent, type DragEvent, type JSX } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { excelApi, type ImportResult, type ManifestImportResult } from '../../api/excel'
import { UploadFailedError, uploadImportFile } from '../../api/uploads'
import { Banner, Button, Card, Icon, Mono } from '../../design/components'
import { useContainerLookup } from '../../hooks/useContainers'
import { PageHeader } from '../../shell/PageHeader'
import { SectionHead } from '../../shell/SectionHead'
import styles from './ImportPackingLists.module.css'

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

function WizardSteps({ current, mode }: WizardStepsProps & { mode: ImportMode }): JSX.Element {
  const steps: { n: 1 | 2 | 3; label: string; sub: string }[] = [
    { n: 1, label: 'Upload file', sub: mode === 'manifest' ? 'Pick the .xlsx manifest' : 'Pick container + .xlsx' },
    { n: 2, label: 'Confirm import', sub: 'Create packing lists' },
    { n: 3, label: 'Results', sub: 'Per-row outcome' },
  ]
  return (
    <Card padding={0}>
      <div className={styles.steps}>
        {steps.map((step, index) => {
          const done = step.n < current
          const isCurrent = step.n === current
          return (
            <div key={step.n} className={styles.stepWrap}>
              <div className={[styles.step, isCurrent ? styles.stepActive : ''].join(' ')}>
                <div className={[styles.stepCircle, done ? styles.stepDone : '', isCurrent ? styles.stepCurrent : ''].join(' ')}>
                  {done ? <Icon name="check" size={16} stroke={3} color="#fff" /> : step.n}
                </div>
                <div>
                  <div className={styles.stepLabel}>{step.label}</div>
                  <div className={styles.stepSub}>{step.sub}</div>
                </div>
              </div>
              {index < steps.length - 1 && <Icon name="chevright" size={14} color="var(--color-ink-4)" />}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export function ImportPackingLists(): JSX.Element {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [mode, setMode] = useState<ImportMode>('manifest')
  const containerLookup = useContainerLookup()
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
      if (err instanceof UploadFailedError) {
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
        eyebrow="China-side · bulk entry"
        title="Import from Excel"
        subtitle="Bring a container’s cargo into ShipX in one pass — either your forwarder’s own manifest export, or a filled ShipX template."
      />

      <WizardSteps current={step} mode={mode} />
      <div className={styles.spacer} />

      {error && (
        <div className={styles.banner}>
          <Banner variant="error" title="Couldn't import">{error}</Banner>
        </div>
      )}

      {step === 1 && (
        <Card padding={32}>
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
              <button
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
              </button>
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
            <label className={styles.selectLabel} htmlFor="importContainerSelect">
              Container<span className={styles.required}>*</span>
            </label>
            <select
              id="importContainerSelect"
              className={styles.select}
              value={containerId}
              onChange={(event) => setContainerId(event.target.value)}
            >
              <option value="">Select a container…</option>
              {containers.map((container) => (
                <option key={container.id} value={container.id}>
                  {container.container_number}
                </option>
              ))}
            </select>
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
            <div className={styles.dropzoneSub}>or click to browse · .xlsx only</div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx"
              className={styles.hiddenInput}
              onChange={handleFileChange}
              aria-label="Choose .xlsx file"
            />
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
              <button type="button" className={styles.removeFile} onClick={() => setFile(null)}>
                Remove
              </button>
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
            <Button variant="accent" icon="check" loading={importing} onClick={() => void handleConfirmImport()}>
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
              sub={`${manifestResult.items_created} item(s) added across ${manifestResult.packing_lists_created} packing list(s), ready for approval`}
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
            <div className={styles.errorSection}>
              <Card padding={0}>
                <div className={styles.tableHead}>
                  <SectionHead
                    title="Skipped rows"
                    sub={`${manifestResult.error_details.length} row(s) skipped`}
                  />
                </div>
                <table className={styles.errorTable}>
                  <thead>
                    <tr>
                      <th>Sheet</th>
                      <th>Row</th>
                      <th>Field</th>
                      <th>Value</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {manifestResult.error_details.map((detail, index) => (
                      <tr key={index}>
                        <td>{detail.sheet ?? '—'}</td>
                        <td>
                          <Mono>{detail.row}</Mono>
                        </td>
                        <td>{detail.field}</td>
                        <td>{detail.value}</td>
                        <td>{detail.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
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
            <Button variant="primary" trailingIcon="arrowright" onClick={() => navigate('/containers')}>
              View containers
            </Button>
          </div>
        </>
      )}

      {step === 3 && result && (
        <>
          <Card>
            <SectionHead title="Import complete" sub={`${result.packing_lists_created} packing list(s) ready for approval`} />
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

          {result.error_details.length > 0 && (
            <div className={styles.errorSection}>
              <Card padding={0}>
                <div className={styles.tableHead}>
                  <SectionHead title="Skipped rows" sub={`${result.error_details.length} row(s) skipped`} />
                </div>
                <table className={styles.errorTable}>
                  <thead>
                    <tr>
                      <th>Row</th>
                      <th>Field</th>
                      <th>Value</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.error_details.map((detail, index) => (
                      <tr key={index}>
                        <td>
                          <Mono>{detail.row}</Mono>
                        </td>
                        <td>{detail.field}</td>
                        <td>{detail.value}</td>
                        <td>{detail.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          )}

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
