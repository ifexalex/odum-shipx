// ============================================================
// Shipx — Platform Admin Portal Screens (Section 2)
// 2.1 Dashboard · 2.2 Tenant List · 2.3 Create Tenant
// 2.4 Tenant Detail · 2.5 Platform Settings
// ============================================================

// ============================================================
// SIDEBAR CONFIG (Platform Admin)
// ============================================================
const platformSidebarItems = (active = 'dashboard') => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard', active: active === 'dashboard'},
  ]},
  {group: 'Tenants', items: [
    {icon: 'building', label: 'All Tenants', active: active === 'tenants', count: '12'},
    {icon: 'plus', label: 'Onboard Tenant', active: active === 'new-tenant'},
  ]},
  {group: 'Platform', items: [
    {icon: 'settings', label: 'Settings', active: active === 'settings'},
    {icon: 'log', label: 'Audit Log', active: active === 'audit'},
  ]},
];

const platformUser = {name: 'Alex Ifesinachi', role: 'Platform Admin'};

// ============================================================
// 2.1 — PLATFORM DASHBOARD
// ============================================================
const PlatformDashboard = () => (
  <PageShell
    sidebar={<Sidebar role="platform" items={platformSidebarItems('dashboard')} user={platformUser} />}
    topbar={<TopBar role="platform" title="Platform Overview" user={platformUser} actions={
      <DateRangeButton />
    } />}
  >
    {/* Stat row */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Active Tenants" value="12" trend="+2 this month" trendDir="up" sublabel="2 suspended"
        accent={<Icon name="building" size={20} color={T.green} />} />
      <StatCard label="API Calls (30d)" value="2.84" suffix="M" trend="+18.4%" trendDir="up" sublabel="vs last period"
        accent={<Icon name="chart" size={20} color={T.info} />} />
      <StatCard label="Containers Processed" value="284" trend="+12.4%" trendDir="up" sublabel="this month"
        accent={<Icon name="container" size={20} color={T.copper} />} />
      <StatCard label="Platform MRR" value="₦8.4" suffix="M" trend="+6.2%" trendDir="up" sublabel="₦480k pending"
        accent={<Icon name="coin" size={20} color={T.green} />} />
    </div>

    {/* Two column: health table + activity */}
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 360px', gap: 24, marginBottom: 24}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <SectionHead title="Tenant Health" sub="Live status across all 12 tenants" />
          <a style={{color: T.green, fontSize: 13, fontWeight: 600, cursor: 'pointer'}}>View all →</a>
        </div>
        <Table
          columns={[
            {title: 'Tenant', sortable: true},
            {title: 'Status'},
            {title: 'Plan'},
            {title: 'Users', align: 'right'},
            {title: 'Containers', align: 'right'},
            {title: '', width: 60},
          ]}
          dense
          rows={[
            {cells: [
              <TenantCell name="Acme Logistics" sub="since Jan 2026" color={T.copper} />,
              <Badge variant="success">Active</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Professional</span>,
              <Mono>24 / 50</Mono>, <Mono>87 / 200</Mono>,
              <ViewLink />,
            ]},
            {cells: [
              <TenantCell name="StarShip Cargo" sub="since Mar 2026" color={T.green} />,
              <Badge variant="success">Active</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Enterprise</span>,
              <Mono>38 / 100</Mono>, <Mono>148 / 500</Mono>,
              <ViewLink />,
            ]},
            {cells: [
              <TenantCell name="Eze Freight" sub="since Feb 2026" color={T.info} />,
              <Badge variant="warning">At limit</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Starter</span>,
              <Mono>10 / 10</Mono>, <Mono color={T.warning}>20 / 20</Mono>,
              <ViewLink />,
            ]},
            {cells: [
              <TenantCell name="Apapa Express" sub="since Oct 2025" color={T.warning} />,
              <Badge variant="success">Active</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Professional</span>,
              <Mono>18 / 50</Mono>, <Mono>62 / 200</Mono>,
              <ViewLink />,
            ]},
            {cells: [
              <TenantCell name="Tin Can Logistics" sub="since Nov 2025" color={T.rolePlatform} />,
              <Badge variant="error">Suspended</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Professional</span>,
              <Mono color={T.ink4}>—</Mono>, <Mono color={T.ink4}>—</Mono>,
              <ViewLink />,
            ], suspended: true},
            {cells: [
              <TenantCell name="Naija Cargo Co." sub="since Dec 2025" color={T.roleChina} />,
              <Badge variant="success">Active</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Starter</span>,
              <Mono>6 / 10</Mono>, <Mono>14 / 20</Mono>,
              <ViewLink />,
            ]},
            {cells: [
              <TenantCell name="Lion Freight" sub="since Apr 2026" color={T.copperHover} />,
              <Badge variant="info">Onboarding</Badge>,
              <span style={{fontSize: 12, fontWeight: 600, color: T.ink2}}>Professional</span>,
              <Mono>3 / 50</Mono>, <Mono>2 / 200</Mono>,
              <ViewLink />,
            ]},
          ]}
        />
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px 12px'}}>
          <SectionHead title="Recent Activity" sub="Platform-level events" />
        </div>
        <ActivityFeed />
      </Card>
    </div>

    {/* Quick actions */}
    <SectionHead title="Quick actions" />
    <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16}}>
      <QuickActionCard icon="plus" title="Onboard new tenant" sub="Create a tenant account and provision an admin user" cta="Start onboarding" accent />
      <QuickActionCard icon="log" title="View full audit log" sub="Cross-tenant audit events with filters and JSON diffs" cta="Open audit log" />
      <QuickActionCard icon="settings" title="Platform settings" sub="Notification gateways, plans, maintenance windows" cta="Open settings" />
    </div>
  </PageShell>
);

const TenantCell = ({name, sub, color = T.green}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
    <div style={{width: 28, height: 28, borderRadius: 6, background: color + '22', color: color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 12, fontFamily: T.display}}>
      {name.split(' ').slice(0,2).map(w => w[0]).join('')}
    </div>
    <div>
      <div style={{fontWeight: 600, color: T.ink, fontSize: 13, lineHeight: 1.2}}>{name}</div>
      <div style={{fontSize: 11, color: T.ink4, lineHeight: 1.3}}>{sub}</div>
    </div>
  </div>
);

const ViewLink = () => (
  <button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: 0}}>View</button>
);

const DateRangeButton = () => (
  <button style={{
    display: 'inline-flex', alignItems: 'center', gap: 8, height: 36, padding: '0 14px',
    background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
    fontFamily: T.body, fontSize: 13, fontWeight: 600, color: T.ink2, cursor: 'pointer',
  }}>
    <Icon name="calendar" size={14} color={T.ink3} />
    Last 30 days
    <Icon name="chevdown" size={13} color={T.ink4} />
  </button>
);

const ActivityFeed = () => {
  const events = [
    {icon: 'plus', color: T.green, title: 'Tenant onboarded', meta: 'Lion Freight · Professional plan', who: 'Alex Ifesinachi', when: '2h ago'},
    {icon: 'suspend', color: T.error, title: 'Tenant suspended', meta: 'Tin Can Logistics · payment overdue', who: 'Alex Ifesinachi', when: '4h ago'},
    {icon: 'settings', color: T.info, title: 'WhatsApp gateway updated', meta: 'New phone_number_id rotated', who: 'Joe Nnaemeka', when: '8h ago'},
    {icon: 'chart', color: T.warning, title: 'Eze Freight hit container limit', meta: '20/20 — limit reached for May 2026', who: 'System', when: '1d ago'},
    {icon: 'coin', color: T.green, title: 'Plan upgraded', meta: 'StarShip Cargo · Professional → Enterprise', who: 'Alex Ifesinachi', when: '2d ago'},
    {icon: 'user', color: T.info, title: 'Admin invited', meta: 'naija@naijacargo.co · Tenant Admin', who: 'Alex Ifesinachi', when: '2d ago'},
    {icon: 'log', color: T.rolePlatform, title: 'Audit log exported', meta: 'CSV export · Mar 1 – Apr 30', who: 'Alex Ifesinachi', when: '3d ago'},
    {icon: 'settings', color: T.info, title: 'Plan limits revised', meta: 'Starter: 20 → 25 containers/month', who: 'Joe Nnaemeka', when: '4d ago'},
  ];
  return (
    <div>
      {events.map((e, i) => (
        <div key={i} style={{display: 'flex', gap: 12, padding: '12px 20px', borderTop: i > 0 ? `1px solid ${T.line}` : 'none'}}>
          <div style={{width: 28, height: 28, borderRadius: 8, background: e.color + '18', color: e.color, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
            <Icon name={e.icon} size={14} />
          </div>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.3}}>{e.title}</div>
            <div style={{fontSize: 12, color: T.ink3, marginTop: 2, lineHeight: 1.35}}>{e.meta}</div>
            <div style={{fontSize: 11, color: T.ink4, marginTop: 4}}>by {e.who} · {e.when}</div>
          </div>
        </div>
      ))}
      <div style={{padding: '12px 20px', borderTop: `1px solid ${T.line}`, textAlign: 'center'}}>
        <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View full audit log →</a>
      </div>
    </div>
  );
};

const QuickActionCard = ({icon, title, sub, cta, accent}) => (
  <Card padding={20}>
    <div style={{display: 'flex', gap: 14, alignItems: 'flex-start'}}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: accent ? T.copper : T.greenSoft, color: accent ? '#fff' : T.green,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <Icon name={icon} size={18} stroke={2.3} />
      </div>
      <div style={{flex: 1}}>
        <h4 style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, margin: 0, color: T.ink, letterSpacing: '-0.005em'}}>{title}</h4>
        <p style={{fontSize: 13, color: T.ink3, margin: '4px 0 12px', lineHeight: 1.45}}>{sub}</p>
        <a style={{color: accent ? T.copper : T.green, fontWeight: 700, fontSize: 13, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4}}>
          {cta} <Icon name="arrowright" size={13} stroke={2.5} />
        </a>
      </div>
    </div>
  </Card>
);

// ============================================================
// 2.2 — TENANT LIST
// ============================================================
const TenantList = () => (
  <PageShell
    sidebar={<Sidebar role="platform" items={platformSidebarItems('tenants')} user={platformUser} />}
    topbar={<TopBar role="platform" title="Tenants" breadcrumb={['Platform', 'Tenants']} user={platformUser} actions={
      <Button variant="accent" icon="plus">Onboard new tenant</Button>
    } />}
  >
    {/* Filter bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>13</span></Chip>
          <Chip count={10}>Active</Chip>
          <Chip count={2}>Suspended</Chip>
          <Chip count={1}>Offboarded</Chip>
        </div>
        <div style={{flex: 1, minWidth: 280}}>
          <Field>
            <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
              <Icon name="search" size={14} color={T.ink4} />
              <input placeholder="Search by name, email, ID…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
            </div>
          </Field>
        </div>
        <Button variant="secondary" size="md" icon="filter">More filters</Button>
        <Button variant="secondary" size="md" trailing="chevdown">Sort: Created date</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Tenant', sortable: true},
          {title: 'ID'},
          {title: 'Status'},
          {title: 'Plan'},
          {title: 'Primary contact'},
          {title: 'Users', align: 'right'},
          {title: 'Created', sortable: true},
          {title: '', width: 40},
        ]}
        rows={[
          tenantRow({name: 'Acme Logistics', id: 'tnt_2bN…7sR', sub: 'Lagos, Nigeria', color: T.copper, status: 'active', plan: 'Professional', contact: {name: 'Amara Okafor', email: 'amara@acmelogistics.com'}, users: '24 / 50', created: '14 Jan 2026'}),
          tenantRow({name: 'StarShip Cargo', id: 'tnt_8aK…4mP', sub: 'Lagos, Nigeria', color: T.green, status: 'active', plan: 'Enterprise', contact: {name: 'Olumide Bello', email: 'olu@starship.co'}, users: '38 / 100', created: '02 Mar 2026', selected: true}),
          tenantRow({name: 'Eze Freight', id: 'tnt_3fW…9qD', sub: 'Lagos, Nigeria', color: T.info, status: 'active', plan: 'Starter', contact: {name: 'Ngozi Eze', email: 'ngozi@ezefreight.ng'}, users: '10 / 10', created: '18 Feb 2026'}),
          tenantRow({name: 'Apapa Express', id: 'tnt_1tQ…2bV', sub: 'Lagos, Nigeria', color: T.warning, status: 'active', plan: 'Professional', contact: {name: 'Tunde Bakare', email: 'tunde@apapaexpress.com'}, users: '18 / 50', created: '12 Oct 2025'}),
          tenantRow({name: 'Tin Can Logistics', id: 'tnt_5cR…8jY', sub: 'Lagos, Nigeria', color: T.rolePlatform, status: 'suspended', plan: 'Professional', contact: {name: 'Chiamaka Igwe', email: 'cig@tincanlogistics.ng'}, users: '0 / 50', created: '22 Nov 2025', suspended: true}),
          tenantRow({name: 'Naija Cargo Co.', id: 'tnt_9hT…1nL', sub: 'Onitsha, Nigeria', color: T.roleChina, status: 'active', plan: 'Starter', contact: {name: 'Emeka Nwogu', email: 'em@naijacargo.co'}, users: '6 / 10', created: '08 Dec 2025'}),
          tenantRow({name: 'Lion Freight', id: 'tnt_4dG…5xC', sub: 'Lagos, Nigeria', color: T.copperHover, status: 'onboarding', plan: 'Professional', contact: {name: 'Adaeze Eze', email: 'adaeze@lionfreight.ng'}, users: '3 / 50', created: '11 Apr 2026'}),
          tenantRow({name: 'Kola Cargo Hub', id: 'tnt_6mF…3wB', sub: 'Aba, Nigeria', color: T.greenStrong, status: 'active', plan: 'Starter', contact: {name: 'Ifeoma Uche', email: 'ifeoma@kolacargo.ng'}, users: '8 / 10', created: '04 Feb 2026'}),
          tenantRow({name: 'Trident Shipping', id: 'tnt_7nB…2xT', sub: 'Port Harcourt', color: T.info, status: 'active', plan: 'Professional', contact: {name: 'Bayo Adekola', email: 'bayo@tridentship.co'}, users: '14 / 50', created: '22 Dec 2025'}),
          tenantRow({name: 'Aba Trade Lines', id: 'tnt_0rE…6vH', sub: 'Aba, Nigeria', color: T.copper, status: 'offboarded', plan: 'Starter', contact: {name: '—', email: '—'}, users: '0 / 10', created: '14 Aug 2025', suspended: true}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const tenantRow = ({name, id, sub, color, status, plan, contact, users, created, selected, suspended}) => {
  const statusBadge = {
    active: <Badge variant="success">Active</Badge>,
    suspended: <Badge variant="error">Suspended</Badge>,
    onboarding: <Badge variant="info">Onboarding</Badge>,
    offboarded: <Badge variant="neutral">Offboarded</Badge>,
  }[status];
  const planColor = {Starter: T.ink3, Professional: T.green, Enterprise: T.copper}[plan];
  return {
    selected, suspended,
    cells: [
      <TenantCell name={name} sub={sub} color={color} />,
      <Mono color={T.ink4}>{id}</Mono>,
      statusBadge,
      <span style={{fontSize: 12, fontWeight: 700, color: planColor}}>{plan}</span>,
      <div style={{fontSize: 12, lineHeight: 1.3}}>
        <div style={{color: T.ink, fontWeight: 500}}>{contact.name}</div>
        <div style={{color: T.ink4, fontSize: 11}}>{contact.email}</div>
      </div>,
      <Mono>{users}</Mono>,
      <span style={{fontSize: 12, color: T.ink3}}>{created}</span>,
      <button style={{background: 'transparent', border: 0, padding: 4, cursor: 'pointer', color: T.ink4, borderRadius: 4, display: 'flex'}}>
        <Icon name="dot3" size={16} />
      </button>,
    ],
  };
};

const TablePagination = () => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderTop: `1px solid ${T.line}`, fontSize: 13, color: T.ink3}}>
    <div>Showing <strong style={{color: T.ink}}>1–10</strong> of <strong style={{color: T.ink}}>13</strong> tenants</div>
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 12}}>
        <span>Rows:</span>
        <button style={{display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', background: '#fff', border: `1px solid ${T.line}`, borderRadius: 6, fontSize: 12, fontWeight: 600, color: T.ink2, cursor: 'pointer'}}>
          10 <Icon name="chevdown" size={11} color={T.ink4} />
        </button>
      </div>
      <div style={{display: 'flex', gap: 4}}>
        <button disabled style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, color: T.ink4, opacity: 0.4, cursor: 'not-allowed', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <Icon name="chevleft" size={14} />
        </button>
        <button style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, color: T.ink, fontWeight: 600, cursor: 'pointer', fontSize: 13}}>1</button>
        <button style={{width: 30, height: 30, border: `1px solid ${T.green}`, background: T.greenSoft, color: T.greenDeep, borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: 'pointer'}}>2</button>
        <button style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink}}>
          <Icon name="chevright" size={14} />
        </button>
      </div>
    </div>
  </div>
);

// ============================================================
// 2.3 — CREATE TENANT
// ============================================================
const CreateTenant = ({state = 'form'}) => {
  if (state === 'success') return <CreateTenantSuccess />;
  return (
    <PageShell
      sidebar={<Sidebar role="platform" items={platformSidebarItems('new-tenant')} user={platformUser} />}
      topbar={<TopBar role="platform" title="Onboard a new tenant" breadcrumb={['Platform', 'Tenants', 'New tenant']} user={platformUser} />}
    >
      <div style={{maxWidth: 1100, margin: '0 auto'}}>
        <PageHeader
          eyebrow="Tenant onboarding"
          title="Onboard a new tenant"
          subtitle="Provision a shipping-company account, set their CBM and FX rates, and invite the first Tenant Admin. You can revise everything later."
        />

        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24}}>
          {/* LEFT — Company details */}
          <Card padding={28}>
            <SectionHead title="Company details" sub="The legal entity and primary point of contact." />
            <div style={{height: 12}} />
            <Field label="Company name" required placeholder="e.g. Acme Logistics" value="Lion Freight Ltd" />
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
              <Field label="Primary contact name" required placeholder="Full name" value="Adaeze Eze" />
              <Field label="Primary contact email" required placeholder="admin@company.com" value="adaeze@lionfreight.ng" helper="The first Tenant Admin invite is sent here." />
            </div>
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
              <SelectField label="Origin country" value="China" required />
              <SelectField label="Destination country" value="Nigeria" required />
            </div>

            <div style={{marginTop: 8}}>
              <label style={{display: 'block', fontFamily: T.body, fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>Company logo</label>
              <div style={{
                border: `1.5px dashed ${T.lineStrong}`, borderRadius: 10, padding: '20px 16px',
                display: 'flex', alignItems: 'center', gap: 14, background: T.muted,
              }}>
                <div style={{
                  width: 56, height: 56, borderRadius: 8, background: T.copperSoft, color: T.copperDeep,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 18, fontFamily: T.display, flexShrink: 0,
                }}>LF</div>
                <div style={{flex: 1, minWidth: 0}}>
                  <div style={{fontWeight: 600, color: T.ink, fontSize: 14}}>lionfreight-logo.svg</div>
                  <div style={{fontSize: 12, color: T.ink4, marginTop: 2}}>SVG · 4.2 KB · uploaded just now</div>
                </div>
                <Button variant="secondary" size="sm" icon="upload">Replace</Button>
              </div>
            </div>
          </Card>

          {/* RIGHT — Subscription */}
          <Card padding={28}>
            <SectionHead title="Subscription & rates" sub="The plan determines feature flags and quotas." />
            <div style={{height: 12}} />
            <label style={{display: 'block', fontFamily: T.body, fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 8}}>Subscription plan</label>
            <PlanRadio name="Starter" price="₦180k/mo" features="10 users · 20 containers/mo · 5 GB storage" />
            <PlanRadio name="Professional" price="₦480k/mo" features="50 users · 200 containers/mo · 10 GB storage · API access" selected />
            <PlanRadio name="Enterprise" price="Custom" features="100+ users · 500+ containers/mo · 50 GB · SSO · white-glove support" />

            <div style={{height: 14}} />
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
              <Field label="USD → NGN rate" required prefix="₦" placeholder="1650.00" value="1650.00" helper="Used for new billing only." />
              <Field label="CBM rate (USD)" required prefix="$" placeholder="48.00" value="48.00" helper="Per cubic meter." />
            </div>
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
              <Field label="Max users" value="50" helper="Auto-set by plan." disabled />
              <Field label="Max containers / mo" value="200" helper="Auto-set by plan." disabled />
            </div>
          </Card>
        </div>

        {/* Footer */}
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 0'}}>
          <div style={{fontSize: 12, color: T.ink4}}>
            By onboarding, you agree this tenant accepts the Shipx <a style={{color: T.green, fontWeight: 600}}>platform terms</a>.
          </div>
          <div style={{display: 'flex', gap: 10}}>
            <Button variant="ghost">Cancel</Button>
            <Button variant="secondary">Save as draft</Button>
            <Button variant="accent" size="lg" icon="check">Onboard tenant</Button>
          </div>
        </div>
      </div>
    </PageShell>
  );
};

const SelectField = ({label, value, required}) => (
  <Field label={label} required={required}>
    <div style={{
      height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
      display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer',
    }}>
      <span style={{flex: 1, fontSize: 14, color: T.ink}}>{value}</span>
      <Icon name="chevdown" size={14} color={T.ink4} />
    </div>
  </Field>
);

const PlanRadio = ({name, price, features, selected}) => (
  <div style={{
    display: 'flex', alignItems: 'flex-start', gap: 12,
    border: `${selected ? 2 : 1}px solid ${selected ? T.green : T.line}`,
    borderRadius: 10, padding: '14px 16px', marginBottom: 10,
    background: selected ? T.greenTint : '#fff', cursor: 'pointer',
  }}>
    <div style={{
      width: 18, height: 18, borderRadius: '50%',
      border: `${selected ? 5 : 1.5}px solid ${selected ? T.green : T.lineStrong}`,
      background: '#fff', marginTop: 2, flexShrink: 0,
    }} />
    <div style={{flex: 1}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
        <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: T.ink}}>{name}</div>
        <div style={{fontFamily: T.mono, fontSize: 13, fontWeight: 600, color: selected ? T.green : T.ink2}}>{price}</div>
      </div>
      <div style={{fontSize: 12.5, color: T.ink3, marginTop: 3, lineHeight: 1.5}}>{features}</div>
    </div>
  </div>
);

const CreateTenantSuccess = () => (
  <PageShell
    sidebar={<Sidebar role="platform" items={platformSidebarItems('tenants')} user={platformUser} />}
    topbar={<TopBar role="platform" title="Onboard a new tenant" breadcrumb={['Platform', 'Tenants', 'New tenant']} user={platformUser} />}
  >
    <div style={{maxWidth: 600, margin: '64px auto 0'}}>
      <Card padding={48} style={{textAlign: 'center'}}>
        <div style={{width: 84, height: 84, borderRadius: '50%', background: T.successSoft, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 20}}>
          <Icon name="check" size={44} color={T.success} stroke={2.5} />
        </div>
        <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 24, margin: '0 0 6px', letterSpacing: '-0.015em'}}>Lion Freight Ltd is onboard.</h2>
        <p style={{fontSize: 14, color: T.ink3, margin: '0 0 24px'}}>
          A Tenant Admin invite has been emailed to <strong style={{color: T.ink}}>adaeze@lionfreight.ng</strong>. They'll set their password and land on their dashboard.
        </p>
        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16, textAlign: 'left', marginBottom: 24}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
            <span style={{fontSize: 11, fontWeight: 600, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Tenant ID</span>
            <Mono>tnt_4dG7zC9xB2nF5xC</Mono>
          </div>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
            <span style={{fontSize: 11, fontWeight: 600, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Plan</span>
            <Badge variant="primary">Professional</Badge>
          </div>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <span style={{fontSize: 11, fontWeight: 600, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Onboarded by</span>
            <span style={{fontSize: 13, color: T.ink, fontWeight: 600}}>Alex Ifesinachi · just now</span>
          </div>
        </div>
        <div style={{display: 'flex', gap: 12, justifyContent: 'center'}}>
          <Button variant="secondary">Onboard another</Button>
          <Button variant="primary" trailing="arrowright">View tenant</Button>
        </div>
      </Card>
    </div>
  </PageShell>
);

// ============================================================
// 2.4 — TENANT DETAIL
// ============================================================
const TenantDetail = ({tab = 'overview'}) => (
  <PageShell
    sidebar={<Sidebar role="platform" items={platformSidebarItems('tenants')} user={platformUser} />}
    topbar={<TopBar role="platform" breadcrumb={['Platform', 'Tenants', 'Acme Logistics']} user={platformUser} title="" search />}
  >
    {/* Tenant hero — clean row, no card chrome */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 56, height: 56, borderRadius: 12,
          background: T.copperSoft, color: T.copperDeep,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 800, fontSize: 22, fontFamily: T.display, flexShrink: 0,
        }}>AL</div>
        <div style={{minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Acme Logistics</h1>
            <Badge variant="success">Active</Badge>
            <Badge variant="primary">Professional</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8}}>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
              <span style={{display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: T.success, boxShadow: `0 0 0 3px ${T.success}22`}} />
              Online — last active 4 minutes ago
            </span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Tenant since 14 January 2026</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8, flexShrink: 0}}>
        <Button variant="secondary" icon="eye">View as Tenant Admin</Button>
        <Button variant="danger-outline" icon="suspend">Suspend</Button>
      </div>
    </div>

    <Tabs tabs={['Overview', 'Users', 'Usage & Billing', 'Configuration', 'Audit Log']} active={
      tab === 'overview' ? 'Overview' :
      tab === 'users' ? 'Users' :
      tab === 'usage' ? 'Usage & Billing' :
      tab === 'config' ? 'Configuration' :
      tab === 'audit' ? 'Audit Log' : 'Overview'
    } />

    {tab === 'overview' && <TenantOverview />}
    {tab === 'users' && <TenantUsers />}
    {tab === 'usage' && <TenantUsage />}
    {tab === 'config' && <TenantConfig />}
    {tab === 'audit' && <TenantAudit />}
  </PageShell>
);

const TenantOverview = () => (
  <>
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      <Card>
        <SectionHead title="Company info" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit →</a>} />
        <Kvp label="Legal name" value="Acme Logistics Ltd" />
        <Kvp label="Primary contact" value={<><strong>Amara Okafor</strong> · amara@acmelogistics.com</>} />
        <Kvp label="Phone" value={<Mono>+234 801 234 5678</Mono>} />
        <Kvp label="Origin → Destination" value="China → Nigeria" />
        <Kvp label="Subscription plan" value={<Badge variant="primary">Professional · ₦480k/mo</Badge>} />
        <Kvp label="Onboarded" value="14 Jan 2026 · by Alex Ifesinachi" />
        <Kvp label="Last active" value={<><span style={{color: T.success, fontWeight: 600}}>● Online</span> · 4 min ago</>} divider={false} />
      </Card>

      <Card>
        <SectionHead title="Key metrics · this month" />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16}}>
          <MetricBlock label="Active users" value="24" of="50" pct={48} />
          <MetricBlock label="Containers" value="87" of="200" pct={43} />
          <MetricBlock label="API calls" value="421k" of="1M" pct={42} />
          <MetricBlock label="Storage" value="2.4 GB" of="10 GB" pct={24} />
        </div>
        <Banner variant="info" title="On track for the month">All metrics well within Professional plan limits. Next billing on 14 May 2026.</Banner>
      </Card>
    </div>

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent containers" sub="Last 5 processed by this tenant" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <Table
          dense
          columns={[{title: 'Container'}, {title: 'Status'}, {title: 'Customers', align: 'right'}, {title: 'Created'}]}
          rows={[
            {cells: [<Mono>MSCU1234567</Mono>, <Badge variant="info">In transit</Badge>, <Mono>12</Mono>, <span style={{fontSize: 12, color: T.ink3}}>15 Apr 2026</span>]},
            {cells: [<Mono>HLBU9384712</Mono>, <Badge variant="warning">Customs</Badge>, <Mono>8</Mono>, <span style={{fontSize: 12, color: T.ink3}}>12 Apr 2026</span>]},
            {cells: [<Mono>COSU7194820</Mono>, <Badge variant="success">Cleared</Badge>, <Mono>15</Mono>, <span style={{fontSize: 12, color: T.ink3}}>08 Apr 2026</span>]},
            {cells: [<Mono>ONEU2847510</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>9</Mono>, <span style={{fontSize: 12, color: T.ink3}}>04 Apr 2026</span>]},
            {cells: [<Mono>MAEU4729183</Mono>, <Badge variant="accent">Discrepancy</Badge>, <Mono>11</Mono>, <span style={{fontSize: 12, color: T.ink3}}>02 Apr 2026</span>]},
          ]}
        />
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent staff users" sub="Last 5 to log in" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <Table
          dense
          columns={[{title: 'User'}, {title: 'Role'}, {title: 'Last login'}]}
          rows={[
            {cells: [<UserCell name="Amara Okafor" email="amara@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <span style={{fontSize: 12, color: T.ink3}}>4 min ago</span>]},
            {cells: [<UserCell name="Kwame Asante" email="kwame@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>1 hour ago</span>]},
            {cells: [<UserCell name="Ifeoma Uche" email="ifeoma@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>3 hours ago</span>]},
            {cells: [<UserCell name="Taiwo Adeyemi" email="taiwo@acmelogistics.com" />, <Badge variant="warning">Warehouse</Badge>, <span style={{fontSize: 12, color: T.ink3}}>Today, 09:42</span>]},
            {cells: [<UserCell name="Chinedu Obi" email="chinedu@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>Yesterday</span>]},
          ]}
        />
      </Card>
    </div>
  </>
);

const Kvp = ({label, value, divider = true}) => (
  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: divider ? `1px dashed ${T.line}` : 'none', gap: 16}}>
    <span style={{fontSize: 12, color: T.ink4, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.06em'}}>{label}</span>
    <span style={{fontSize: 13, color: T.ink2, textAlign: 'right'}}>{value}</span>
  </div>
);

const MetricBlock = ({label, value, of, pct}) => {
  const color = pct >= 90 ? T.error : pct >= 75 ? T.warning : T.green;
  return (
    <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8, padding: '12px 14px'}}>
      <div style={{fontSize: 11, color: T.ink3, fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase'}}>{label}</div>
      <div style={{display: 'flex', alignItems: 'baseline', gap: 6, margin: '6px 0 8px'}}>
        <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: T.ink, letterSpacing: '-0.01em'}}>{value}</span>
        <span style={{fontSize: 11, color: T.ink4}}>/ {of}</span>
      </div>
      <div style={{height: 4, background: T.line, borderRadius: 2, overflow: 'hidden'}}>
        <div style={{height: '100%', width: pct + '%', background: color, borderRadius: 2}} />
      </div>
    </div>
  );
};

const UserCell = ({name, email}) => (
  <div style={{display: 'flex', gap: 10, alignItems: 'center'}}>
    <Avatar size={28} name={name} />
    <div style={{minWidth: 0}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.2}}>{name}</div>
      <div style={{fontSize: 11, color: T.ink4, lineHeight: 1.3}}>{email}</div>
    </div>
  </div>
);

const TenantUsage = () => (
  <>
    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20}}>
      <SectionHead title="Usage · April 2026" sub="Reset on 1 May 2026 at 00:00 WAT" />
      <DateRangeButton />
    </div>

    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="API calls" value="421" suffix="k / 1M" trend="42% used" trendDir="up" sublabel="9 days left" />
      <StatCard label="Containers" value="87" suffix="/ 200" trend="43% used" trendDir="up" sublabel="rate steady" />
      <StatCard label="Active users" value="24" suffix="/ 50" sublabel="3 new this month" />
      <StatCard label="Storage" value="2.4" suffix="/ 10 GB" sublabel="docs + exports" />
    </div>

    {/* Quota bars */}
    <Card style={{marginBottom: 20}}>
      <SectionHead title="Quota status" sub="Live counters per metered dimension. Override available in extraordinary cases." />
      <div style={{height: 8}} />
      <QuotaBar label="API Calls" used={421000} limit={1000000} unit="" pct={42} />
      <QuotaBar label="SMS sent" used={420} limit={2000} pct={21} />
      <QuotaBar label="Containers" used={87} limit={200} pct={43} />
      <QuotaBar label="Active Users" used={24} limit={50} pct={48} />
      <QuotaBar label="Storage" used={2.4} limit={10} unit="GB" pct={24} />
      <div style={{display: 'flex', justifyContent: 'flex-end', marginTop: 14}}>
        <Button variant="secondary" size="sm">Override a limit</Button>
      </div>
    </Card>

    {/* Chart */}
    <Card>
      <SectionHead title="API calls by day" sub="Last 30 days · 421,038 total" />
      <UsageChart />
    </Card>
  </>
);

const QuotaBar = ({label, used, limit, unit = '', pct}) => {
  const color = pct >= 100 ? T.error : pct >= 80 ? T.warning : T.green;
  const fmt = (n) => n >= 1000 ? (n/1000).toFixed(0) + 'k' : n;
  return (
    <div className="sx-cols" style={{padding: '10px 0', borderBottom: `1px solid ${T.line}`, display: 'grid', gridTemplateColumns: '120px 1fr 140px 80px', gap: 16, alignItems: 'center'}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>{label}</div>
      <div style={{height: 8, background: T.line, borderRadius: 4, overflow: 'hidden'}}>
        <div style={{height: '100%', width: pct + '%', background: color, borderRadius: 4}} />
      </div>
      <Mono color={T.ink2}>{fmt(used)}{unit} / {fmt(limit)}{unit}</Mono>
      <div style={{textAlign: 'right'}}>
        {pct >= 100 ? <Badge variant="error" size="sm">At limit</Badge> :
         pct >= 80 ? <Badge variant="warning" size="sm">{pct}%</Badge> :
         <span style={{fontSize: 12, color: T.ink4, fontFamily: T.mono}}>{pct}%</span>}
      </div>
    </div>
  );
};

const UsageChart = () => {
  // Generate 30 bars with varying heights
  const data = [42, 38, 45, 52, 48, 22, 18, 50, 58, 62, 55, 48, 51, 25, 21, 60, 68, 72, 65, 58, 54, 32, 28, 70, 78, 82, 75, 68, 62, 38];
  const max = Math.max(...data);
  return (
    <div style={{display: 'flex', alignItems: 'flex-end', gap: 4, height: 180, padding: '20px 0 0', borderBottom: `1px solid ${T.line}`}}>
      {data.map((v, i) => (
        <div key={i} style={{
          flex: 1,
          height: `${(v / max) * 100}%`,
          background: i === 27 ? T.copper : i > 25 ? T.green : T.greenSoft,
          borderRadius: '3px 3px 0 0', minHeight: 4,
        }} />
      ))}
    </div>
  );
};

// ============================================================
// TENANT USERS TAB
// ============================================================
const TenantUsers = () => (
  <>
    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16}}>
      <SectionHead title="Staff users · Acme Logistics" sub="24 active users across 4 roles" />
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus">Invite user</Button>
      </div>
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
        <Chip active>All roles <span style={{opacity: 0.5}}>24</span></Chip>
        <Chip count={2}>Tenant Admin</Chip>
        <Chip count={8}>China Office</Chip>
        <Chip count={11}>Nigeria Office</Chip>
        <Chip count={3}>Warehouse</Chip>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'User'},
          {title: 'Role'},
          {title: 'Status'},
          {title: 'Last login'},
          {title: 'Created'},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [
            <UserCell name="Amara Okafor" email="amara@acmelogistics.com" />,
            <Badge variant="primary">Tenant Admin</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>4 min ago</span>,
            <span style={{fontSize: 12, color: T.ink3}}>14 Jan 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Kwame Asante" email="kwame@acmelogistics.com" />,
            <Badge variant="info">China Office</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>1 hour ago</span>,
            <span style={{fontSize: 12, color: T.ink3}}>22 Jan 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Ifeoma Uche" email="ifeoma@acmelogistics.com" />,
            <Badge variant="accent">Nigeria Office</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>3 hours ago</span>,
            <span style={{fontSize: 12, color: T.ink3}}>25 Jan 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Taiwo Adeyemi" email="taiwo@acmelogistics.com" />,
            <Badge variant="warning">Warehouse</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>Today, 09:42</span>,
            <span style={{fontSize: 12, color: T.ink3}}>02 Feb 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Chinedu Obi" email="chinedu@acmelogistics.com" />,
            <Badge variant="accent">Nigeria Office</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>Yesterday</span>,
            <span style={{fontSize: 12, color: T.ink3}}>08 Feb 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Mei Lin Zhang" email="mei@acmelogistics.com" />,
            <Badge variant="info">China Office</Badge>,
            <Badge variant="warning">Pending invite</Badge>,
            <span style={{fontSize: 12, color: T.ink4}}>—</span>,
            <span style={{fontSize: 12, color: T.ink3}}>12 Apr 2026</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Bola Adetunji" email="bola@acmelogistics.com" />,
            <Badge variant="accent">Nigeria Office</Badge>,
            <Badge variant="neutral">Suspended</Badge>,
            <span style={{fontSize: 12, color: T.ink3}}>14 days ago</span>,
            <span style={{fontSize: 12, color: T.ink3}}>04 Mar 2026</span>,
            <KebabBtn />,
          ], suspended: true},
          {cells: [
            <UserCell name="Adaeze Eze" email="adaeze@acmelogistics.com" />,
            <Badge variant="info">China Office</Badge>,
            <Badge variant="success">Active</Badge>,
            <span style={{fontSize: 12, color: T.ink2}}>2 days ago</span>,
            <span style={{fontSize: 12, color: T.ink3}}>18 Mar 2026</span>,
            <KebabBtn />,
          ]},
        ]}
      />
      <TablePagination />
    </Card>
  </>
);

const KebabBtn = () => (
  <button style={{background: 'transparent', border: 0, padding: 4, cursor: 'pointer', color: T.ink4, borderRadius: 4, display: 'flex'}}>
    <Icon name="dot3" size={16} />
  </button>
);

// ============================================================
// TENANT CONFIGURATION TAB
// ============================================================
const TenantConfig = () => (
  <>
    <Banner variant="info" title="Read-only view">
      Showing the tenant's current configuration. To edit, use "View as Tenant Admin" to enter the tenant's portal and modify their settings, or have the Tenant Admin update them directly.
    </Banner>
    <div style={{height: 24}} />

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Dollar rate */}
      <Card>
        <SectionHead title="Dollar exchange rate" sub="Used for new billing calculations" action={
          <a style={{color: T.green, fontWeight: 600, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 4}}>Edit as admin <Icon name="arrowright" size={12} /></a>
        } />
        <div style={{height: 16}} />
        <div style={{display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 12}}>
          <span style={{fontFamily: T.display, fontWeight: 800, fontSize: 36, letterSpacing: '-0.02em', color: T.ink}}>₦1,650</span>
          <span style={{fontSize: 14, color: T.ink3, fontWeight: 600}}>per $1 USD</span>
        </div>
        <div style={{fontSize: 12, color: T.ink4}}>Set by <strong style={{color: T.ink2}}>Amara Okafor</strong> on 14 Apr 2026, 18:30</div>
        <div style={{marginTop: 16, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
          <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Last 4 changes</div>
          <RateHistoryMini items={[
            {rate: '₦1,650', by: 'Amara Okafor', when: '14 Apr 2026', current: true},
            {rate: '₦1,620', by: 'Amara Okafor', when: '08 Apr 2026'},
            {rate: '₦1,580', by: 'Amara Okafor', when: '24 Mar 2026'},
            {rate: '₦1,550', by: 'Amara Okafor', when: '14 Jan 2026', note: 'Set at onboarding'},
          ]} />
        </div>
      </Card>

      {/* CBM rate */}
      <Card>
        <SectionHead title="CBM rate" sub="Base shipping cost per cubic meter" action={
          <a style={{color: T.green, fontWeight: 600, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 4}}>Edit as admin <Icon name="arrowright" size={12} /></a>
        } />
        <div style={{height: 16}} />
        <div style={{display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 12}}>
          <span style={{fontFamily: T.display, fontWeight: 800, fontSize: 36, letterSpacing: '-0.02em', color: T.ink}}>$48.00</span>
          <span style={{fontSize: 14, color: T.ink3, fontWeight: 600}}>per CBM</span>
        </div>
        <div style={{fontSize: 12, color: T.ink4}}>Set by <strong style={{color: T.ink2}}>Amara Okafor</strong> on 14 Jan 2026 — unchanged since onboarding</div>
        <div style={{marginTop: 16, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
          <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Equivalent at current FX</div>
          <div style={{fontFamily: T.mono, fontSize: 13, color: T.ink2}}>$48.00 × ₦1,650 = <strong style={{color: T.ink}}>₦79,200 per CBM</strong></div>
        </div>
      </Card>
    </div>

    {/* Branding & Storage policy */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      <Card>
        <SectionHead title="Branding" sub="Logo and company display name on customer-facing documents" action={
          <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit as admin →</a>
        } />
        <div style={{height: 16}} />
        <div style={{display: 'flex', gap: 16, alignItems: 'center', padding: 16, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10}}>
          <div style={{
            width: 64, height: 64, borderRadius: 12,
            background: T.copperSoft, color: T.copperDeep,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 800, fontSize: 22, fontFamily: T.display, flexShrink: 0,
          }}>AL</div>
          <div style={{flex: 1}}>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, color: T.ink}}>Acme Logistics</div>
            <div style={{fontSize: 12, color: T.ink4, marginTop: 2}}>acme-logo.svg · 6.4 KB · uploaded 14 Jan 2026</div>
          </div>
        </div>
        <Kvp label="Display name" value="Acme Logistics Ltd" />
        <Kvp label="Warehouse address" value={<span style={{textAlign: 'right'}}>12 Wharf Road, Apapa<br />Lagos 100242, Nigeria</span>} />
        <Kvp label="Support email" value={<Mono>support@acmelogistics.com</Mono>} divider={false} />
      </Card>

      <Card>
        <SectionHead title="Storage fee policy" sub="Applied after the free-storage window expires" action={
          <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit as admin →</a>
        } />
        <div style={{height: 16}} />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16}}>
          <div style={{padding: 16, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10}}>
            <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Free period</div>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, marginTop: 4}}>7<span style={{fontSize: 13, color: T.ink3, marginLeft: 4, fontWeight: 600}}>days</span></div>
          </div>
          <div style={{padding: 16, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10}}>
            <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Daily rate</div>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, marginTop: 4}}>₦500<span style={{fontSize: 13, color: T.ink3, marginLeft: 4, fontWeight: 600}}>/day</span></div>
          </div>
        </div>
        <Kvp label="Applies to" value="All customers" />
        <Kvp label="Currently accruing on" value={<><strong style={{color: T.ink}}>4 billing records</strong> · ₦14,000 total</>} divider={false} />
      </Card>
    </div>

    {/* Notification config */}
    <Card style={{marginBottom: 20}}>
      <SectionHead title="Notification channels" sub="Which channels this tenant uses for customer notifications" action={
        <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit as admin →</a>
      } />
      <div style={{height: 16}} />
      <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12}}>
        <ChannelChip channel="SMS" enabled count="247 sent · last 30d" provider="Termii · platform default" />
        <ChannelChip channel="WhatsApp" enabled count="412 sent · last 30d" provider="Meta Cloud API · platform default" />
        <ChannelChip channel="Email" enabled count="89 sent · last 30d" provider="Postmark · platform default" />
      </div>
    </Card>

    {/* Custom charge types */}
    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Custom charge types" sub="Tenant-defined miscellaneous charges available for billing" action={
          <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit as admin →</a>
        } />
      </div>
      <Table
        dense
        columns={[
          {title: 'Charge name'},
          {title: 'Description'},
          {title: 'Default amount', align: 'right'},
          {title: 'Status'},
        ]}
        rows={[
          {cells: [<span style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Customs Examination</span>, <span style={{fontSize: 12, color: T.ink3}}>Physical inspection at Tin Can</span>, <Mono>₦15,000</Mono>, <Badge variant="success" size="sm">Active</Badge>]},
          {cells: [<span style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Port Handling Surcharge</span>, <span style={{fontSize: 12, color: T.ink3}}>Apapa terminal handling fee</span>, <Mono>₦8,500</Mono>, <Badge variant="success" size="sm">Active</Badge>]},
          {cells: [<span style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Express Clearance</span>, <span style={{fontSize: 12, color: T.ink3}}>Priority customs processing</span>, <Mono>₦22,000</Mono>, <Badge variant="success" size="sm">Active</Badge>]},
          {cells: [<span style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Cold Chain Premium</span>, <span style={{fontSize: 12, color: T.ink3}}>Refrigerated container handling</span>, <Mono>₦45,000</Mono>, <Badge variant="neutral" size="sm">Inactive</Badge>]},
        ]}
      />
    </Card>
  </>
);

const RateHistoryMini = ({items}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 6}}>
    {items.map((it, i) => (
      <div key={i} style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', fontSize: 12}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
          <span style={{fontFamily: T.mono, fontWeight: 600, color: it.current ? T.green : T.ink}}>{it.rate}</span>
          {it.current && <Badge variant="primary" size="sm" dot={false}>Current</Badge>}
          {it.note && <span style={{color: T.ink4, fontSize: 11}}>{it.note}</span>}
        </div>
        <div style={{color: T.ink4}}>{it.by} · {it.when}</div>
      </div>
    ))}
  </div>
);

const ChannelChip = ({channel, enabled, count, provider}) => {
  const ic = channel === 'SMS' ? 'phone' : channel === 'WhatsApp' ? 'phone' : 'mail';
  return (
    <div style={{
      border: `1px solid ${enabled ? T.green + '55' : T.line}`,
      background: enabled ? T.greenTint : '#fff',
      borderRadius: 10, padding: 16,
    }}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
        <div style={{width: 32, height: 32, borderRadius: 8, background: enabled ? T.green : T.line, color: enabled ? '#fff' : T.ink4, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name={ic} size={15} stroke={2} />
        </div>
        <div style={{flex: 1}}>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink, lineHeight: 1.2}}>{channel}</div>
          <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{provider}</div>
        </div>
        <Badge variant={enabled ? 'success' : 'neutral'} size="sm">{enabled ? 'On' : 'Off'}</Badge>
      </div>
      <div style={{fontSize: 12, color: T.ink3}}>{count}</div>
    </div>
  );
};

const TenantAudit = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
      <SectionHead title="Audit log · Acme Logistics" sub="All entity-level events with diffs" />
      <Button variant="secondary" size="sm" icon="download">Export CSV</Button>
    </div>
    <Table
      dense
      columns={[
        {title: 'Timestamp'},
        {title: 'Entity'},
        {title: 'ID'},
        {title: 'Action'},
        {title: 'Actor'},
        {title: 'Before → After'},
        {title: '', width: 40},
      ]}
      rows={[
        {cells: [
          <Mono color={T.ink2}>15 Apr 14:32</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>billing</span>,
          <Mono color={T.ink4}>BL-001…</Mono>,
          <Badge variant="info" size="sm">STATUS_CHANGE</Badge>,
          <UserCell name="Amara Okafor" email="Nigeria Office" />,
          <span style={{fontSize: 12, color: T.ink3}}>status: <span style={{color: T.error, textDecoration: 'line-through'}}>unpaid</span> → <span style={{color: T.success, fontWeight: 600}}>paid</span></span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>15 Apr 14:21</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>container</span>,
          <Mono color={T.ink4}>MSCU1…</Mono>,
          <Badge variant="info" size="sm">STATUS_CHANGE</Badge>,
          <UserCell name="Amara Okafor" email="Nigeria Office" />,
          <span style={{fontSize: 12, color: T.ink3}}>status: <span style={{color: T.error, textDecoration: 'line-through'}}>customs</span> → <span style={{color: T.success, fontWeight: 600}}>cleared</span></span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>15 Apr 12:08</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>packing_list</span>,
          <Mono color={T.ink4}>PL-148…</Mono>,
          <Badge variant="success" size="sm">CREATE</Badge>,
          <UserCell name="Kwame Asante" email="China Office" />,
          <span style={{fontSize: 12, color: T.ink3}}>+ 14 cartons · 0.84 CBM</span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>15 Apr 10:44</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>customer</span>,
          <Mono color={T.ink4}>cus_8…</Mono>,
          <Badge variant="success" size="sm">CREATE</Badge>,
          <UserCell name="Amara Okafor" email="Nigeria Office" />,
          <span style={{fontSize: 12, color: T.ink3}}>Adaeze Nwosu · self-registered</span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>14 Apr 18:30</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>tenant</span>,
          <Mono color={T.ink4}>tnt_2bN…</Mono>,
          <Badge variant="warning" size="sm">UPDATE</Badge>,
          <UserCell name="Amara Okafor" email="Tenant Admin" />,
          <span style={{fontSize: 12, color: T.ink3}}>dollar_rate: <span style={{color: T.error, textDecoration: 'line-through'}}>1620</span> → <span style={{color: T.success, fontWeight: 600}}>1650</span></span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>14 Apr 16:12</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>tenant_user</span>,
          <Mono color={T.ink4}>usr_4f…</Mono>,
          <Badge variant="success" size="sm">CREATE</Badge>,
          <UserCell name="Amara Okafor" email="Tenant Admin" />,
          <span style={{fontSize: 12, color: T.ink3}}>+ chinedu@acmelogistics.com · Nigeria Office</span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
        {cells: [
          <Mono color={T.ink2}>14 Apr 09:08</Mono>,
          <span style={{fontSize: 12, color: T.ink2, textTransform: 'capitalize', fontWeight: 600}}>release_note</span>,
          <Mono color={T.ink4}>RN-029…</Mono>,
          <Badge variant="success" size="sm">CREATE</Badge>,
          <UserCell name="Amara Okafor" email="Nigeria Office" />,
          <span style={{fontSize: 12, color: T.ink3}}>4 cartons · ₦49,352 settled</span>,
          <Icon name="chevdown" size={14} color={T.ink4} />,
        ]},
      ]}
    />
    <TablePagination />
  </Card>
);

// ============================================================
// 2.5 — PLATFORM SETTINGS
// ============================================================
const PlatformSettings = ({active = 'general'}) => {
  const navItems = [
    {key: 'general', label: 'General', icon: 'settings'},
    {key: 'notifications', label: 'Notification Providers', icon: 'bell'},
    {key: 'maintenance', label: 'Maintenance', icon: 'pause'},
    {key: 'plans', label: 'Plans & Limits', icon: 'shield'},
    {key: 'security', label: 'Security', icon: 'shield'},
  ];
  return (
    <PageShell
      sidebar={<Sidebar role="platform" items={platformSidebarItems('settings')} user={platformUser} />}
      topbar={<TopBar role="platform" title="Platform Settings" breadcrumb={['Platform', 'Settings']} user={platformUser} search={false} />}
    >
      <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '240px 1fr', gap: 24}}>
        <Card padding={8}>
          {navItems.map((it, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '10px 12px', borderRadius: 8,
              background: it.key === active ? T.greenTint : 'transparent',
              color: it.key === active ? T.greenDeep : T.ink2,
              fontWeight: it.key === active ? 600 : 500, fontSize: 13.5,
              cursor: 'pointer',
            }}>
              <Icon name={it.icon} size={15} color={it.key === active ? T.green : T.ink3} />
              {it.label}
            </div>
          ))}
        </Card>

        <div>
          {active === 'general' && <PlatformGeneral />}
          {active === 'notifications' && <PlatformNotifications />}
          {active === 'plans' && <PlatformPlans />}
        </div>
      </div>
    </PageShell>
  );
};

const PlatformGeneral = () => (
  <Card padding={28}>
    <SectionHead title="General platform settings" sub="Branding, defaults, and platform-wide behavior" />
    <div style={{height: 12}} />
    <Field label="Platform name" value="Shipx" helper="Shown on auth screens and in system emails" />
    <Field label="Support email" type="email" value="support@shipx.co" icon="mail" />
    <Field label="Support phone" value="+234 1 234 5678" icon="phone" />
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
      <SelectField label="Default currency display" value="₦ Nigerian Naira (NGN)" />
      <SelectField label="Default timezone" value="WAT (UTC+1) · Lagos" />
    </div>
    <Field label="Public tracker URL" prefix="https://" value="track.shipx.co/{tracking_code}" helper="Customers paste tracking codes here." />
    <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 12, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
      <Button variant="ghost">Reset to defaults</Button>
      <Button variant="primary" icon="check">Save changes</Button>
    </div>
  </Card>
);

const PlatformNotifications = () => (
  <div>
    <Card style={{marginBottom: 16}}>
      <SectionHead title="SMS gateway" sub="Configured for outbound transactional SMS to all tenants" action={<Badge variant="success">Connected</Badge>} />
      <div style={{height: 12}} />
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <SelectField label="Provider" value="Termii (Nigeria)" />
        <Field label="From number / sender ID" value="ShipX" />
      </div>
      <Field label="API key" type="password" value="••••••••••••••••••••a9c2" trailing="eye" helper="Last rotated 12 Apr 2026 · by Joe Nnaemeka" />
      <div style={{display: 'flex', gap: 10}}>
        <Button variant="secondary" size="sm" icon="phone">Send test SMS</Button>
        <Button variant="ghost" size="sm">Rotate key</Button>
      </div>
    </Card>

    <Card style={{marginBottom: 16}}>
      <SectionHead title="WhatsApp Business" sub="Meta Cloud API · phone_number_id used for templated messages" action={<Badge variant="success">Connected</Badge>} />
      <div style={{height: 12}} />
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <Field label="Phone number ID" value="106842831024716" />
        <Field label="WhatsApp Business Account ID" value="184729104728501" />
      </div>
      <Field label="Permanent access token" type="password" value="EAAR••••••••••••••a8B2" trailing="eye" helper="Token doesn't expire. Rotate every 90 days." />
      <div style={{display: 'flex', gap: 10}}>
        <Button variant="secondary" size="sm">Send test WhatsApp</Button>
        <Button variant="ghost" size="sm">Manage templates →</Button>
      </div>
    </Card>

    <Card>
      <SectionHead title="Email (transactional)" sub="System emails — invites, password resets, receipts" action={<Badge variant="warning">Action needed</Badge>} />
      <div style={{height: 12}} />
      <Banner variant="warning" title="SPF / DKIM not verified for shipx.co">
        Outbound emails from no-reply@shipx.co may be marked as spam. <a style={{color: T.warningStrong, fontWeight: 700, textDecoration: 'underline'}}>View DNS records →</a>
      </Banner>
      <div style={{height: 14}} />
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <SelectField label="Provider" value="Postmark" />
        <Field label="From address" type="email" value="no-reply@shipx.co" />
      </div>
    </Card>
  </div>
);

const PlatformPlans = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px'}}>
      <SectionHead title="Subscription plans" sub="The plan ladder offered to new tenants" action={<Button variant="secondary" size="sm" icon="plus">Add plan</Button>} />
    </div>
    <Table
      columns={[
        {title: 'Plan'},
        {title: 'Max users', align: 'right'},
        {title: 'Max containers / mo', align: 'right'},
        {title: 'Storage', align: 'right'},
        {title: 'API calls / mo', align: 'right'},
        {title: 'Price / month', align: 'right'},
        {title: 'Tenants on plan', align: 'right'},
        {title: '', width: 50},
      ]}
      rows={[
        {cells: [
          <PlanCell name="Starter" color={T.ink3} desc="Solo operators getting started" />,
          <Mono>10</Mono>, <Mono>20</Mono>, <Mono>5 GB</Mono>, <Mono>5k</Mono>,
          <Mono>₦180,000</Mono>, <Mono>4</Mono>,
          <button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Edit</button>,
        ]},
        {cells: [
          <PlanCell name="Professional" color={T.green} desc="Established shipping operations" />,
          <Mono>50</Mono>, <Mono>200</Mono>, <Mono>10 GB</Mono>, <Mono>1M</Mono>,
          <Mono>₦480,000</Mono>, <Mono>6</Mono>,
          <button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Edit</button>,
        ]},
        {cells: [
          <PlanCell name="Enterprise" color={T.copper} desc="Large-volume freight forwarders" />,
          <Mono>100+</Mono>, <Mono>500+</Mono>, <Mono>50 GB+</Mono>, <Mono>5M+</Mono>,
          <Mono>Custom</Mono>, <Mono>2</Mono>,
          <button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Edit</button>,
        ]},
      ]}
    />
  </Card>
);

const PlanCell = ({name, color, desc}) => (
  <div>
    <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2}}>
      <div style={{width: 8, height: 8, borderRadius: 2, background: color}} />
      <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink}}>{name}</span>
    </div>
    <div style={{fontSize: 12, color: T.ink4, paddingLeft: 16}}>{desc}</div>
  </div>
);

Object.assign(window, {
  PlatformDashboard, TenantList, CreateTenant, TenantDetail, PlatformSettings,
  // Helpers reused by other portals
  DateRangeButton, UserCell, Kvp, ViewLink, KebabBtn, TenantCell, TablePagination,
  PlanRadio, SelectField, QuickActionCard, MetricBlock,
});
