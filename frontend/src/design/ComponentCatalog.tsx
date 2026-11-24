import { useRef, useState, type JSX, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { TenantQuota } from '../api/tenantManagement'
import { useDateRangeFilter } from '../hooks/useDateRangeFilter'
import {
  Action,
  Avatar,
  Combobox,
  CountrySelect,
  DateRangeFilter,
  EmptyState,
  ErrorState,
  ExportButton,
  FileInput,
  Icon,
  Kvp,
  LimitReachedModal,
  MenuButton,
  ConfirmDialog,
  LinesSkeleton,
  ListFooter,
  LocaleCard,
  PageSkeleton,
  PhoneField,
  Pressable,
  QuickActionCard,
  Skeleton,
  StateSelect,
  Stepper,
  ThemeToggle,
  UserCell,
  type StaffLocale,
  Badge,
  Banner,
  Button,
  Card,
  Check,
  Chip,
  CellInput,
  CellSelect,
  CellCheckbox,
  CellRadio,
  DialogGuard,
  ModalOverlay,
  CheckboxField,
  ColorField,
  DateField,
  Field,
  RadioGroup,
  SearchField,
  Select,
  IconButton,
  KolaMark,
  Mono,
  Modal,
  RoleBadge,
  ShipxWordmark,
  StatCard,
  StatusBadge,
  Table,
  ToastRegion,
  TenantBrand,
  ToggleSwitch,
  type BadgeVariant,
  type BannerVariant,
  type ButtonVariant,
} from './components'
import { PageHeader } from '../shell/PageHeader'
import { toast } from './toast'
import { STATUS_REGISTRY, type StatusKind, statusesOf } from './status'
import { claimProgress, claimSteps, containerSteps } from './steps'
import { SectionHead } from '../shell/SectionHead'
import { Tabs } from '../shell/Tabs'
import { TopBar } from '../shell/TopBar'
import { Sidebar } from '../shell/Sidebar'
import { PageShell } from '../shell/PageShell'

const BUTTON_VARIANTS: ButtonVariant[] = [
  'primary',
  'secondary',
  'ghost',
  'danger',
  'danger-ghost',
]
const BADGE_VARIANTS: BadgeVariant[] = ['success', 'warning', 'error', 'info', 'accent', 'purple', 'neutral', 'primary']
const BANNER_VARIANTS: BannerVariant[] = ['info', 'success', 'warning', 'error']

const DEMO_QUOTA: TenantQuota = {
  tenant_id: 'demo',
  period: '2026-11',
  subscription_tier: 'starter',
  limits: { users: { used: 10, max: 10 }, containers_per_month: { used: 4, max: 20 }, storage_gb: { used: 1, max: 5 } },
  api_calls: 0,
  notifications: { sms_sent: 0, whatsapp_sent: 0, emails_sent: 0 },
}

const WIZARD_STEPS = [
  { key: 'details', label: 'Details', sub: 'Customer + container' },
  { key: 'items', label: 'Items', sub: 'Cartons + measurements' },
  { key: 'review', label: 'Review', sub: 'Verify + submit' },
]

/** A labelled frame for one demo, so each state in a row says what it shows. */
function Demo({ label, width, children }: { label: string; width?: number; children: ReactNode }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', width, maxWidth: '100%' }}>
      <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-ink-4)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)' }}>{label}</span>
      {children}
    </div>
  )
}

function DateRangeDemo(): JSX.Element {
  const range = useDateRangeFilter()
  return <DateRangeFilter range={range} label="Created" />
}

function Section({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <section style={{ marginBottom: 'var(--space-12)' }}>
      <SectionHead title={title} />
      {children}
    </section>
  )
}

// Dev-only component catalog — every component in src/design/components and
// src/shell with every variant/prop combination, for design QA sign-off.
// Mounted at /component-catalog only when import.meta.env.DEV (see App.tsx).
export function ComponentCatalog(): JSX.Element {
  const [modalOpen, setModalOpen] = useState(false)
  const [toggle1, setToggle1] = useState(true)
  const [toggle2, setToggle2] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')
  const [tableSelected, setTableSelected] = useState<boolean[]>([false, true, false])
  const [combo, setCombo] = useState<string | null>(null)
  const [country, setCountry] = useState('Nigeria')
  const [state, setState] = useState('')
  const [phone, setPhone] = useState('')
  const [locale, setLocale] = useState<StaffLocale>('en')
  const [limitOpen, setLimitOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [overlayOpen, setOverlayOpen] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [opened, setOpened] = useState<string | null>(null)

  return (
    <div style={{ padding: 'var(--space-8)', maxWidth: 1100 }}>
      {/* The page header (FD-14) with every slot filled: status, a meta line of facts, primary, secondary, overflow. */}
      <PageHeader
        title="Component catalog"
        status={<Badge variant="success">Step 2 gate</Badge>}
        meta={['Every shared component', 'every variant and state', 'light and dark']}
        primary={<Button variant="primary" icon="plus">Primary action</Button>}
        actions={<Button variant="secondary">Secondary</Button>}
        more={[
          { label: 'Overflow action', icon: 'file', onSelect: () => undefined },
          { label: 'Destructive action', tone: 'danger', onSelect: () => undefined },
        ]}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-8)' }}>
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>
          Theme (system, light, dark): every section below reads in both.
        </span>
        <ThemeToggle />
      </div>

      <Section title="Brand marks">
        <div style={{ display: 'flex', gap: 'var(--space-6)', alignItems: 'center', background: 'var(--color-forest-dark)', padding: 'var(--space-4)', borderRadius: 'var(--radius-md)' }}>
          <KolaMark size={32} color="var(--color-primary-bright)" />
          <ShipxWordmark />
          <ShipxWordmark showBy />
          <TenantBrand name="Acme Logistics" />
        </div>
      </Section>

      <Section title="Buttons (FD-07)">
        <ul style={{ margin: '0 0 var(--space-4)', paddingLeft: 'var(--space-5)', color: 'var(--color-ink-3)', lineHeight: 'var(--leading-body)' }}>
          <li><strong>primary</strong> — the main action of a screen or dialog, one per area.</li>
          <li><strong>secondary</strong> — every other action, and the only button a table row may carry (small). The row itself opens the record.</li>
          <li><strong>ghost</strong> — low-emphasis actions beside others: Cancel, Clear, Remove, View all.</li>
          <li><strong>danger</strong> — the irreversible commit inside a confirmation (&quot;Delete warehouse&quot;).</li>
          <li><strong>danger-ghost</strong> — the way into something destructive (&quot;Cancel container&quot;), never a filled button beside a primary.</li>
          <li><strong>accent</strong> — paying and signing in only; a test keeps it there.</li>
          <li>Heights 32 / 40 / 48 px, 44 px minimum on touch screens. Direction is a trailing icon, not a typed arrow. A button that changes data is disabled during read-only impersonation without any page code.</li>
          <li>Pages write no raw <code>&lt;button&gt;</code>: <code>Button</code>, <code>IconButton</code> (label required), a router <code>Link</code> to navigate, or <code>Pressable</code> for a clickable tile or row.</li>
        </ul>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', alignItems: 'center' }}>
          {BUTTON_VARIANTS.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant}
            </Button>
          ))}
          <Button variant="accent">accent (paying and signing in only)</Button>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', alignItems: 'center', marginTop: 'var(--space-4)' }}>
          <Button variant="secondary" size="sm">sm 32</Button>
          <Button variant="secondary">md 40</Button>
          <Button variant="secondary" size="lg">lg 48</Button>
          <Button variant="primary" icon="download">With icon</Button>
          <Button variant="ghost" trailingIcon="arrowright">View all</Button>
          <Button variant="primary" loading>Loading</Button>
          <Button variant="primary" disabled>Disabled</Button>
          <IconButton icon="x" label="Close" />
          <IconButton icon="x" label="Remove item" variant="danger-ghost" size="sm" />
          <IconButton icon="download" label="Download" variant="secondary" />
        </div>
      </Section>

      <Section title="Badges">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
          {BADGE_VARIANTS.map((variant) => (
            <Badge key={variant} variant={variant}>
              {variant}
            </Badge>
          ))}
          <Badge variant="success" dot={false} size="sm">
            no dot, sm
          </Badge>
        </div>
      </Section>

      <Section title="Statuses (FD-08)">
        <p style={{ margin: '0 0 var(--space-4)', color: 'var(--color-ink-3)' }}>
          Every status of every record, from the registry in <code>design/status.ts</code>. Colour rule: neutral not
          started or done with nothing to do; info moving along; warning waiting on someone; success done; error
          refused or lost; primary a container cleared and in Nigeria. Pages render <code>StatusBadge</code>, never
          their own map.
        </p>
        <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
          {(Object.keys(STATUS_REGISTRY) as StatusKind[]).map((kind) => (
            <div key={kind} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-2)' }}>
              <Mono>{kind}</Mono>
              {statusesOf(kind).map((status) => (
                <StatusBadge key={status} kind={kind} status={status} />
              ))}
            </div>
          ))}
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-2)' }}>
            <Mono>roles</Mono>
            {(['tenant_admin', 'china_office_staff', 'nigeria_office_staff', 'warehouse_attendant', 'customer'] as const).map((role) => (
              <RoleBadge key={role} role={role} />
            ))}
          </div>
        </div>
      </Section>

      <Section title="Chips">
        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <Chip active>In transit</Chip>
          <Chip>Cleared</Chip>
          <Chip count={4}>With count</Chip>
          <Chip dismissible>Dismissible</Chip>
        </div>
      </Section>

      <Section title="Avatar">
        <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center' }}>
          <Avatar name="Adaeze Eze" />
          <Avatar name="Joe Operator" roleColor="platform" />
          <Avatar name="Joe Operator" roleColor="china" />
          <Avatar name="Joe Operator" roleColor="nigeria" />
          <Avatar name="Joe Operator" roleColor="warehouse" />
          <Avatar name="Joe Operator" roleColor="customer" size={48} />
        </div>
      </Section>

      <Section title="Mono">
        <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
          <Mono>SHPX-2024-00012</Mono>
          <Mono color="var(--color-error)">-12,000.00</Mono>
        </div>
      </Section>

      <Section title="Cards and stat cards (FD-10)">
        <ul style={{ margin: '0 0 var(--space-4)', paddingLeft: 'var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)' }}>
          <li>A stat card holds one figure. A word or a status goes in the record's key-value list.</li>
          <li>Labels wrap between words, never inside one, and are never cut off; the figure scales to the card.</li>
          <li>A table inside a card uses the card's edge as its frame.</li>
        </ul>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
          <StatCard label="Active containers" value={42} icon="container" />
          <StatCard label="Revenue" value="₦1.2M" trend={{ direction: 'up', pct: 12 }} sublabel="vs last month" />
          <StatCard label="Disputes" value={3} trend={{ direction: 'down', pct: 5 }} />
          <StatCard label="Outstanding (30+ days)" value="₦12,345,678" sublabel="unpaid and partly paid invoices" icon="coin" />
          <StatCard label="Cartons on note" value="3 of 12" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--space-3)' }}>
          <Card>Plain card (padding default)</Card>
          <Card padding="large">Large padding</Card>
          <Card padding="none">
            <Table dense columns={[{ title: 'Item' }, { title: 'Qty', type: 'number' }]} rows={[{ cells: ['Table in a card', '2'] }]} />
          </Card>
        </div>
      </Section>

      <Section title="Key-value list">
        <Card>
          <Kvp label="Reference" value={<Mono>REL-2026-0042</Mono>} />
          <Kvp label="Type" value="Partial release" />
          <Kvp label="Payment status" value={<StatusBadge kind="invoice" status="partially_paid" />} />
          <Kvp label="Warehouse" value="Apapa main warehouse — Plot 12, Wharf Road, Apapa, Lagos" divider={false} />
        </Card>
      </Section>

      <Section title="Check">
        <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
          <Check label="Unchecked" checked={false} />
          <Check label="Checked" checked />
          <Check label="Some selected" partial />
          <Check label="Disabled" disabled />
        </div>
      </Section>

      <Section title="ToggleSwitch">
        <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
          <ToggleSwitch checked={toggle1} onChange={setToggle1} label="Email notifications" />
          <ToggleSwitch checked={toggle2} onChange={setToggle2} label="SMS notifications" />
          <ToggleSwitch checked={false} onChange={() => undefined} disabled label="Disabled" />
        </div>
      </Section>

      <Section title="Field family (FD-11, FD-50)">
        <p style={{ margin: '0 0 var(--space-4)', color: 'var(--color-ink-3)' }}>
          Pages use these, never a raw <code>&lt;input&gt;</code>, <code>&lt;select&gt;</code> or <code>&lt;textarea&gt;</code>.
          Every control takes a required <code>label</code> (<code>hideLabel</code> keeps it for screen readers); only
          optional fields are marked. A select with nothing to choose says why and links to the fix. A list filter bar
          has one date control, presets and a custom range in one popover.
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', maxWidth: 720 }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Email" name="email" placeholder="you@company.com" required />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Reference" name="ref" icon="search" optional helper="Container or tracking number" />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Amount" name="amount" error="Enter an amount above zero." />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Select label="Payment method" name="method" placeholder="Choose a method" options={[{ value: 'cash', label: 'Cash' }, { value: 'transfer', label: 'Bank transfer' }]} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Select label="Warehouse" name="wh" options={[]} empty={{ message: 'No warehouses yet.', action: { label: 'Add a warehouse', to: '/admin/config/warehouses' } }} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <DateField label="Ship date" name="ship" value="2026-11-13" onChange={() => undefined} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <ColorField label="Brand colour" name="colour" value="#1c7922" onChange={() => undefined} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <SearchField label="Search containers" placeholder="Container number, vessel…" value="" onChange={() => undefined} />
          </div>
          <div style={{ flex: '1 0 100%' }}>
            <RadioGroup label="Refund preference" name="pref" value="bank" onChange={() => undefined} layout="cards" options={[{ value: 'bank', label: 'Bank account', hint: 'Within 5–7 business days' }, { value: 'credit', label: 'Credit', hint: 'On the next shipment' }]} />
          </div>
          <div style={{ flex: '1 0 100%' }}>
            <CheckboxField label="Release with outstanding balance" hint="Needs a manager's approval notes" checked={false} onChange={() => undefined} />
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
            <CellInput label="Weight (kg), item 1" type="number" defaultValue="12.5" style={{ width: 96 }} />
            <CellSelect label="Package type, item 1" defaultValue="carton" style={{ width: 120 }}>
              <option value="carton">Carton</option>
              <option value="bale">Bale</option>
            </CellSelect>
            <CellCheckbox label="Fragile, item 1" defaultChecked />
            <CellRadio label="Primary role, row 1" name="catalog_primary" defaultChecked />
            <CellRadio label="Primary role, row 2" name="catalog_primary" />
          </div>
          <div style={{ flex: '1 0 100%' }}>
            <Field label="Notes" name="notes" multiline rows={3} optional />
          </div>
        </div>
      </Section>

      <Section title="Toasts (FD-21)">
        <p style={{ margin: '0 0 var(--space-4)', color: 'var(--color-ink-3)' }}>
          Every successful change ends with a toast naming what happened and to which record: top right on desktop,
          bottom on a phone, four seconds, read once by screen readers. Banners are for state that lasts. Call{' '}
          <code>toast.success(title, body)</code> from <code>design/toast</code>, or give a React Query mutation{' '}
          <code>meta.successToast</code>.
        </p>
        <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <Button variant="secondary" onClick={() => toast.success('Payment recorded', 'ACM-INV-20261119-0042')}>
            Success toast
          </Button>
          <Button variant="secondary" onClick={() => toast.info('Message queued to send again')}>
            Info toast
          </Button>
          <Button variant="secondary" onClick={() => toast.error('Could not reach the server', 'Your change was not saved.')}>
            Error toast
          </Button>
        </div>
        <ToastRegion />
      </Section>

      <Section title="Banner">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {BANNER_VARIANTS.map((variant) => (
            <Banner key={variant} variant={variant} title={`${variant} banner`} dismissible>
              Example {variant} message body.
            </Banner>
          ))}
        </div>
      </Section>

      <Section title="Modal (FD-12)">
        <p style={{ margin: '0 0 var(--space-4)', color: 'var(--color-ink-3)' }}>
          Sizes <code>sm</code> 480, <code>md</code> 560 (default), <code>lg</code> 720, <code>xl</code> 960; hand-rolled
          dialogs use <code>--dialog-*</code>. Title 16 px semibold. Footer: Cancel, then the commit button on the right,
          named for the action and the object (&quot;Record payment&quot;). Once something is typed, a backdrop click or
          Escape asks &quot;Discard your changes?&quot; — type below, then click outside.
        </p>
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          Open modal
        </Button>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          size="sm"
          title="Record payment"
          footer={
            <>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={() => setModalOpen(false)}>
                Record payment
              </Button>
            </>
          }
        >
          <Field label="Amount (₦)" name="catalog_amount" type="number" />
        </Modal>
        <Button variant="secondary" mutates={false} onClick={() => setOverlayOpen(true)} style={{ marginLeft: 'var(--space-3)' }}>
          Open hand-rolled dialog
        </Button>
        {overlayOpen && (
          <ModalOverlay onClose={() => setOverlayOpen(false)}>
            <Card radius="xl" padding="large" style={{ width: 'var(--dialog-sm)' }}>
              <DialogGuard onClose={() => setOverlayOpen(false)} />
              <p style={{ marginTop: 0 }}>A page's own dialog panel inside <code>ModalOverlay</code>, guarded by <code>DialogGuard</code>.</p>
              <Field label="Reason" name="catalog_reason" />
              <Button variant="ghost" onClick={() => setOverlayOpen(false)}>Close</Button>
            </Card>
          </ModalOverlay>
        )}
      </Section>

      <Section title="Tabs">
        <Tabs
          items={[
            { key: 'overview', label: 'Overview' },
            { key: 'history', label: 'History' },
          ]}
          active={activeTab}
          onChange={setActiveTab}
        />
      </Section>

      <Section title="Table (FD-13)">
        <ul style={{ margin: '0 0 var(--space-4)', paddingLeft: 'var(--space-5)', fontSize: 'var(--text-sm)', color: 'var(--color-ink-2)' }}>
          <li>Each column declares its type: reference (monospaced), number and money (right-aligned, unit in the title), date, status, action.</li>
          <li>A row opens its record from anywhere on it; its first cell is the keyboard control. No "View" column.</li>
          <li>Below 600 px of its own width a table becomes cards. The list counts once, in the footer.</li>
        </ul>
        <Card padding="none">
          <Table
            columns={[
              { title: 'Reference', type: 'reference', sortable: true },
              { title: 'Customer' },
              { title: 'Total (₦)', type: 'money' },
              { title: 'Status', type: 'status' },
              { title: 'Billed', type: 'date' },
              { title: '', type: 'action' },
            ]}
            rows={[
              {
                onOpen: () => setOpened('INV-A-002'),
                openLabel: 'Open invoice INV-A-002',
                cells: [<Mono key="r">INV-A-002</Mono>, 'Ibrahim Musa', <Mono key="t">₦139,500</Mono>, <StatusBadge key="s" kind="invoice" status="released_with_outstanding" />, '13 Nov', null],
              },
              {
                onOpen: () => setOpened('INV-A-003'),
                openLabel: 'Open invoice INV-A-003',
                suspended: true,
                cells: [<Mono key="r">INV-A-003</Mono>, 'Ngozi Adeyemi', <Mono key="t">₦111,600</Mono>, <StatusBadge key="s" kind="invoice" status="unpaid" />, '13 Nov', <Button key="a" size="sm" variant="secondary" mutates={false} onClick={() => setOpened('Record payment')}>Record payment</Button>],
              },
            ]}
          />
          <ListFooter shown={2} total={68} hasMore onLoadMore={() => undefined} noun="billing records" nounOne="billing record" />
        </Card>
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-ink-3)' }}>Last opened: {opened ?? 'nothing yet'}</p>
        <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <Demo label="Phone width: cards" width={360}>
            <Card padding="none">
              <Table
                columns={[{ title: 'Reference', type: 'reference' }, { title: 'Total (₦)', type: 'money' }, { title: 'Status', type: 'status' }]}
                rows={[{ onOpen: () => setOpened('INV-A-001'), cells: [<Mono key="r">INV-A-001</Mono>, <Mono key="t">₦104,625</Mono>, <StatusBadge key="s" kind="invoice" status="paid" />] }]}
              />
            </Card>
          </Demo>
          <Demo label="Loading" width={360}>
            <Card padding="none">
              <Table columns={[{ title: 'Reference', type: 'reference' }, { title: 'Total (₦)', type: 'money' }]} rows={[]} loading />
            </Card>
          </Demo>
          <Demo label="Empty" width={360}>
            <Card padding="none">
              <Table columns={[{ title: 'Reference', type: 'reference' }]} rows={[]} emptyState={<EmptyState compact title="No billing records match this filter" onClearFilters={() => undefined} />} />
            </Card>
          </Demo>
        </div>
        <Demo label="Selectable">
        <Table
          selectable
          columns={[{ title: 'Container', sortable: true }, { title: 'Status' }, { title: 'Weight', align: 'right' }]}
          rows={[
            { cells: ['SHPX-001', <Badge key="a" variant="info">In transit</Badge>, <Mono key="b">1,200kg</Mono>], selected: tableSelected[0] },
            { cells: ['SHPX-002', <Badge key="a" variant="success">Cleared</Badge>, <Mono key="b">900kg</Mono>], selected: tableSelected[1] },
            { cells: ['SHPX-003', <Badge key="a" variant="warning">Pending</Badge>, <Mono key="b">450kg</Mono>], selected: tableSelected[2] },
          ]}
          onSelectRow={(rowIndex, selected) =>
            setTableSelected((prev) => prev.map((value, index) => (index === rowIndex ? selected : value)))
          }
          onSelectAll={(selected) => setTableSelected((prev) => prev.map(() => selected))}
        />
        </Demo>
      </Section>


      <Section title="Stepper (FD-09)">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          <Demo label="Progress: in transit (staff wording)">
            <Stepper steps={containerSteps('staff')} current={2} label="Container progress" />
          </Demo>
          <Demo label="Progress: complete (customer wording)">
            <Stepper steps={containerSteps('customer')} current={7} complete label="Shipment progress" />
          </Demo>
          <Demo label="Progress: refused at a step">
            <Stepper
              steps={[{ key: 'a', label: 'Accounts review' }, { key: 'b', label: 'Manager approval' }, { key: 'c', label: 'Paid out' }]}
              current={1}
              failed
              label="Refund progress"
            />
          </Demo>
          <Demo label="Wizard: step 2">
            <Stepper mode="wizard" steps={WIZARD_STEPS} current={1} label="Packing list steps" />
          </Demo>
          <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
            <Demo label="Phone width: compact" width={360}>
              <Stepper steps={containerSteps('customer')} current={2} label="Shipment progress" />
            </Demo>
            <Demo label="Phone width: claim, refused" width={360}>
              <Stepper steps={claimSteps('customer')} current={claimProgress('under_inspection').current} failed label="Claim progress" />
            </Demo>
          </div>
        </div>
      </Section>

      <Section title="Empty, loading and error states (FD-20)">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--space-4)' }}>
          <Demo label="Empty: first use">
            <Card>
              <EmptyState icon="container" title="No containers yet" body="Create the first one to start packing." action={{ label: 'Create container', onClick: () => undefined }} />
            </Card>
          </Demo>
          <Demo label="Empty: no results">
            <Card>
              <EmptyState title="No invoices match these filters" onClearFilters={() => undefined} />
            </Card>
          </Demo>
          <Demo label="Error with retry">
            <Card>
              <ErrorState title="Couldn't load this invoice" error={new ApiError({ type: 'about:blank', title: 'Service unavailable', status: 503, detail: 'upstream down', error_code: 'SERVICE_UNAVAILABLE' }, 'req-1234')} onRetry={() => undefined} />
            </Card>
          </Demo>
          <Demo label="Error, compact">
            <ErrorState compact title="Couldn't load the list" error={new Error('boom')} onRetry={() => undefined} />
          </Demo>
          <Demo label="Lines loading">
            <Card>
              <LinesSkeleton label="Loading billing" lines={3} />
            </Card>
          </Demo>
          <Demo label="Skeleton shapes">
            <Card>
              <Skeleton width="60%" height={20} />
              <div style={{ height: 'var(--space-2)' }} />
              <Skeleton width="40%" />
            </Card>
          </Demo>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--space-4)', marginTop: 'var(--space-4)' }}>
          {(['detail', 'list', 'form'] as const).map((kind) => (
            <Demo key={kind} label={`Page skeleton: ${kind}`}>
              <div style={{ height: 260, overflow: 'hidden', border: '1px dashed var(--color-line)', borderRadius: 'var(--radius-md)' }}>
                <PageSkeleton kind={kind} label={`Loading ${kind}`} />
              </div>
            </Demo>
          ))}
        </div>
      </Section>

      <Section title="More controls">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--space-4)' }}>
          <Demo label="Combobox">
            <Combobox
              ariaLabel="Container"
              value={combo}
              onChange={setCombo}
              placeholder="Pick a container"
              options={[{ value: 'a', label: 'ACME001001', meta: '76 CBM · rec. 70' }, { value: 'b', label: 'ACME001002', meta: '33 CBM' }]}
            />
          </Demo>
          <Demo label="Country, state, phone">
            <CountrySelect label="Country" value={country} onChange={setCountry} />
            <StateSelect label="State" country={country} value={state} onChange={setState} optional />
            <PhoneField label="Phone" value={phone} onChange={setPhone} />
          </Demo>
          <Demo label="Date range filter">
            <DateRangeDemo />
          </Demo>
          <Demo label="Export">
            <ExportButton formats={['xlsx', 'csv'] as const} onExport={async () => undefined} />
          </Demo>
          <Demo label="File input (hidden, opened by a button)">
            <FileInput ref={fileRef} label="Upload document" />
            <Button variant="secondary" icon="upload" mutates={false} onClick={() => fileRef.current?.click()}>
              Choose file
            </Button>
          </Demo>
          <Demo label="Language">
            <LocaleCard value={locale} onChange={setLocale} />
          </Demo>
          <Demo label="More-actions menu, pressable tile, guarded action">
            <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'center', flexWrap: 'wrap' }}>
              <MenuButton
                label="More actions for ACME001001"
                items={[
                  { label: 'Download PDF', icon: 'download', onSelect: () => undefined },
                  { label: 'Cancel invoice', tone: 'danger', onSelect: () => undefined },
                ]}
              />
              <Pressable style={{ padding: 'var(--space-3)', border: '1px solid var(--color-line)', borderRadius: 'var(--radius-md)' }}>Pressable tile</Pressable>
              <Action variant="primary" size="sm">Change data</Action>
            </div>
          </Demo>
          <Demo label="Quick action">
            <QuickActionCard icon="plus" title="Invite staff" sub="Add a team member" cta="Invite" onAction={() => undefined} />
          </Demo>
          <Demo label="User cell, icons">
            <UserCell name="Ngozi Adeyemi" email="ngozi@example.com" />
            <div style={{ display: 'flex', gap: 'var(--space-3)', color: 'var(--color-ink-2)' }}>
              <Icon name="container" size={18} />
              <Icon name="ship" size={18} />
              <Icon name="coin" size={18} />
              <Icon name="warn" size={18} />
              <Icon name="check" size={18} />
            </div>
          </Demo>
          <Demo label="Confirm a destructive action (FD-24)">
            <Button variant="danger-ghost" onClick={() => setConfirmOpen(true)}>Delete container</Button>
            <ConfirmDialog
              open={confirmOpen}
              title="Delete container MSCU1234567?"
              confirmLabel="Delete container"
              undo={false}
              typeToConfirm="MSCU1234567"
              onConfirm={() => setConfirmOpen(false)}
              onCancel={() => setConfirmOpen(false)}
            >
              It has no packing lists and will be removed from ShipX.
            </ConfirmDialog>
          </Demo>
          <Demo label="Plan limit dialog">
            <Button variant="secondary" mutates={false} onClick={() => setLimitOpen(true)}>Show limit reached</Button>
            {limitOpen && <LimitReachedModal resource="users" quota={DEMO_QUOTA} onClose={() => setLimitOpen(false)} />}
          </Demo>
        </div>
      </Section>

      <Section title="App shell (Sidebar + TopBar + PageShell)">
        <div style={{ height: 360, border: '1px solid var(--color-line)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <PageShell
            sidebar={
              <Sidebar
                role="nigeria"
                items={[
                  {
                    group: 'Operations',
                    items: [
                      { icon: 'container', label: 'Containers', active: true },
                      { icon: 'package', label: 'Packing lists', count: 12 },
                    ],
                  },
                ]}
              />
            }
            topbar={<TopBar role="nigeria" notifications={3} user={{ name: 'Adaeze Eze', role: 'Staff' }} />}
          >
            <div>Page content goes here: a PageHeader, then the page.</div>
          </PageShell>
        </div>
      </Section>
    </div>
  )
}
