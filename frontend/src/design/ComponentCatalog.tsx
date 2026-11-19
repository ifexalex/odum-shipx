import { useState, type JSX, type ReactNode } from 'react'
import {
  Avatar,
  Badge,
  Banner,
  Button,
  Card,
  Check,
  Chip,
  Field,
  KolaMark,
  Mono,
  Modal,
  ShipxWordmark,
  StatCard,
  Table,
  TenantBrand,
  ToggleSwitch,
  type BadgeVariant,
  type BannerVariant,
  type ButtonVariant,
} from './components'
import { PageHeader } from '../shell/PageHeader'
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
  'danger-outline',
  'success',
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

      <Section title="Buttons">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', alignItems: 'center' }}>
          {BUTTON_VARIANTS.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant}
            </Button>
          ))}
          <Button variant="accent">accent (single per screen)</Button>
          <Button variant="primary" size="sm">
            sm
          </Button>
          <Button variant="primary" size="lg">
            lg
          </Button>
          <Button variant="primary" icon="download">
            With icon
          </Button>
          <Button variant="primary" loading>
            Loading
          </Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
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
          <Check checked={false} />
          <Check checked />
          <Check partial />
          <Check disabled />
        </div>
      </Section>

      <Section title="ToggleSwitch">
        <div style={{ display: 'flex', gap: 'var(--space-4)', alignItems: 'center' }}>
          <ToggleSwitch checked={toggle1} onChange={setToggle1} label="Email notifications" />
          <ToggleSwitch checked={toggle2} onChange={setToggle2} label="SMS notifications" />
          <ToggleSwitch checked={false} onChange={() => undefined} disabled label="Disabled" />
        </div>
      </Section>

      <Section title="Field">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', maxWidth: 640 }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Email" name="email" placeholder="you@company.com" required />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Reference" name="ref" icon="search" optional helper="Container or tracking number" />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Field label="Amount" name="amount" error="Required" />
          </div>
          <div style={{ flex: '1 0 100%' }}>
            <Field label="Notes" name="notes" multiline rows={3} />
          </div>
        </div>
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

      <Section title="Modal">
        <Button variant="primary" onClick={() => setModalOpen(true)}>
          Open modal
        </Button>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Confirm payment"
          footer={
            <>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="accent" onClick={() => setModalOpen(false)}>
                Confirm payment
              </Button>
            </>
          }
        >
          This action cannot be undone.
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
