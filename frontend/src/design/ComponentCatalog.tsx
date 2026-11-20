import { useState, type JSX, type ReactNode } from 'react'
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  Check,
  Chip,
  CellInput,
  CellSelect,
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

  return (
    <div style={{ padding: 'var(--space-8)', maxWidth: 1100 }}>
      <PageHeader
        eyebrow="Design QA"
        title="ShipX Component Catalog"
        subtitle="Every shared component with every variant — FE-03 acceptance criteria"
      />

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

      <Section title="Card / StatCard">
        <div style={{ display: 'flex', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
          <Card>Plain card</Card>
          <StatCard label="Active containers" value={42} icon="container" />
          <StatCard label="Revenue" value="₦1.2M" trend={{ direction: 'up', pct: 12 }} sublabel="vs last month" />
          <StatCard label="Disputes" value={3} trend={{ direction: 'down', pct: 5 }} />
        </div>
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

      <Section title="Table">
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
      </Section>

      <Section title="App shell (Sidebar + TopBar + PageShell)">
        <div style={{ height: 360, border: '1px solid var(--color-line)', borderRadius: 'var(--radius-lg)', overflow: 'hidden' }}>
          <PageShell
            sidebar={
              <Sidebar
                role="nigeria"
                user={{ name: 'Adaeze Eze', role: 'Nigeria Office Staff' }}
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
            topbar={<TopBar role="nigeria" title="Containers" notifications={3} user={{ name: 'Adaeze Eze', role: 'Staff' }} />}
          >
            <div>Page content goes here.</div>
          </PageShell>
        </div>
      </Section>
    </div>
  )
}
