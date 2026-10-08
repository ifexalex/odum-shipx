// ============================================================
// Shipx — Tenant Admin Portal Screens (Section 3)
// 3.1 Dashboard · 3.2 Staff List · 3.3 Invite Modal
// 3.4 Staff Profile · 3.5 Customer List · 3.6 Customer Profile
// ============================================================

const tenantSidebarItems = (active = 'dashboard') => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard', active: active === 'dashboard'},
    {icon: 'chart', label: 'Reports', active: active === 'reports'},
  ]},
  {group: 'Operations', items: [
    {icon: 'users', label: 'Customers', active: active === 'customers', count: '142'},
    {icon: 'user', label: 'Staff users', active: active === 'staff', count: '24'},
  ]},
  {group: 'Configuration', items: [
    {icon: 'settings', label: 'Company settings', active: active === 'settings'},
    {icon: 'coin', label: 'Dollar rate', active: active === 'dollar'},
    {icon: 'package', label: 'CBM rate', active: active === 'cbm'},
    {icon: 'card', label: 'Charge types', active: active === 'charges'},
    {icon: 'bell', label: 'Notifications', active: active === 'notif'},
  ]},
];

const tenantBrand = <TenantBrand name="Acme Logistics" logo="AL" />;
const tenantUser = {name: 'Amara Okafor', role: 'Tenant Admin'};

// ============================================================
// 3.1 — TENANT ADMIN DASHBOARD
// ============================================================
const TenantDashboard = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('dashboard')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" user={tenantUser} actions={<DateRangeButton />} />}
  >
    {/* Greeting hero */}
    <div style={{marginBottom: 24}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.green, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Good morning</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Lead every shipment, Amara.</h2>
      <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>14 containers in transit · 3 awaiting customs · 2 ready for pickup today</p>
    </div>

    {/* Stat row */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Active customers" value="142" trend="+12" trendDir="up" sublabel="new this month"
        accent={<Icon name="users" size={15} stroke={2.2} />} />
      <StatCard label="Containers this month" value="87" sublabel="14 in transit"
        accent={<Icon name="container" size={15} stroke={2.2} />} />
      <StatCard label="Outstanding billing" value="₦4.2" suffix="M" trend="−18%" trendDir="down" sublabel="vs last month"
        accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Pending claims" value="6" sublabel="2 damage · 4 missing"
        accent={<Icon name="warn" size={15} stroke={2.2} />} />
    </div>

    {/* Two-column main */}
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 360px', gap: 24, marginBottom: 24}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent containers" sub="Last 6 containers across all stages" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <Table
          columns={[
            {title: 'Container'},
            {title: 'Status'},
            {title: 'Customers', align: 'right'},
            {title: 'Packing lists', align: 'right'},
            {title: 'Billing'},
            {title: '', width: 50},
          ]}
          rows={[
            {cells: [
              <div><Mono>MSCU1234567</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>MSC Altair · 11.8 CBM</div></div>,
              <Badge variant="info">In transit</Badge>,
              <Mono>12</Mono>, <Mono>12</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.warning}} /><span style={{fontSize: 12, color: T.ink2}}>Partial</span></div>,
              <ViewLink />,
            ]},
            {cells: [
              <div><Mono>HLBU9384712</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>Hapag-Lloyd · 8.4 CBM</div></div>,
              <Badge variant="warning">Customs</Badge>,
              <Mono>8</Mono>, <Mono>8</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.error}} /><span style={{fontSize: 12, color: T.ink2}}>Unpaid</span></div>,
              <ViewLink />,
            ]},
            {cells: [
              <div><Mono>COSU7194820</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>Cosco · 14.2 CBM</div></div>,
              <Badge variant="primary">Cleared</Badge>,
              <Mono>15</Mono>, <Mono>15</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.success}} /><span style={{fontSize: 12, color: T.ink2}}>Paid</span></div>,
              <ViewLink />,
            ]},
            {cells: [
              <div><Mono>ONEU2847510</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>ONE Line · 6.1 CBM</div></div>,
              <Badge variant="success">Delivered</Badge>,
              <Mono>9</Mono>, <Mono>9</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.success}} /><span style={{fontSize: 12, color: T.ink2}}>Paid</span></div>,
              <ViewLink />,
            ]},
            {cells: [
              <div><Mono>MAEU4729183</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>Maersk · 9.6 CBM</div></div>,
              <Badge variant="accent">Discrepancy</Badge>,
              <Mono>11</Mono>, <Mono>10</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.warning}} /><span style={{fontSize: 12, color: T.ink2}}>Partial</span></div>,
              <ViewLink />,
            ]},
            {cells: [
              <div><Mono>SUDU3819273</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>Hamburg Süd · 12.0 CBM</div></div>,
              <Badge variant="info">In transit</Badge>,
              <Mono>10</Mono>, <Mono>9</Mono>,
              <div style={{display: 'flex', alignItems: 'center', gap: 6}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.ink4}} /><span style={{fontSize: 12, color: T.ink3}}>Draft</span></div>,
              <ViewLink />,
            ]},
          ]}
        />
      </Card>

      {/* Activity feed */}
      <Card padding={0}>
        <div style={{padding: '18px 20px', borderBottom: `1px solid ${T.line}`}}>
          <SectionHead title="Activity" sub="Recent across your tenant" />
        </div>
        <TenantActivityFeed />
      </Card>
    </div>

    {/* Bottom row */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent staff logins" sub="Last 5 staff to sign in" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Manage users →</a>} />
        </div>
        <Table
          dense
          columns={[
            {title: 'User'},
            {title: 'Role'},
            {title: 'Last login'},
          ]}
          rows={[
            {cells: [<UserCell name="Amara Okafor" email="amara@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <span style={{fontSize: 12, color: T.ink3}}>Just now</span>]},
            {cells: [<UserCell name="Kwame Asante" email="kwame@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>1 hr ago</span>]},
            {cells: [<UserCell name="Ifeoma Uche" email="ifeoma@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>3 hr ago</span>]},
            {cells: [<UserCell name="Taiwo Adeyemi" email="taiwo@acmelogistics.com" />, <Badge variant="warning">Warehouse</Badge>, <span style={{fontSize: 12, color: T.ink3}}>Today, 09:42</span>]},
            {cells: [<UserCell name="Chinedu Obi" email="chinedu@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <span style={{fontSize: 12, color: T.ink3}}>Yesterday</span>]},
          ]}
        />
      </Card>

      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <SectionHead title="Quick actions" />
        <QuickActionCard icon="plus" title="Add customer" sub="Onboard a new shipping customer" cta="Add customer" />
        <QuickActionCard icon="container" title="Create container" sub="Start a new shipment manifest" cta="New container" accent />
        <QuickActionCard icon="coin" title="Generate billing" sub="Build a billing record from a packing list" cta="Generate billing" />
      </div>
    </div>
  </PageShell>
);

const TenantActivityFeed = () => {
  const events = [
    {icon: 'user', color: T.success, title: 'Customer self-registered', meta: 'Adaeze Nwosu · +234 802 415 0922', when: '12 min ago'},
    {icon: 'truck', color: T.info, title: 'Container arrived Tin Can Port', meta: 'MSCU1234567 · Bay 4 · awaiting customs', when: '1 hr ago'},
    {icon: 'coin', color: T.success, title: 'Payment confirmed', meta: 'Ngozi Okonkwo · ₦49,352 · Zenith Bank TRF', when: '2 hr ago'},
    {icon: 'card', color: T.copper, title: 'Release note generated', meta: 'RN-20260415-001 · 4 cartons for Ngozi Okonkwo', when: '2 hr ago'},
    {icon: 'warn', color: T.error, title: 'Damage claim filed', meta: '2 cartons in COSU7194820 · by Emeka Eze', when: '4 hr ago'},
    {icon: 'package', color: T.info, title: 'Packing list approved', meta: 'PL-20260415-012 · 18 cartons · 0.94 CBM', when: '6 hr ago'},
    {icon: 'coin', color: T.warning, title: 'CBM dispute opened', meta: 'CBM-014 · Mei Lin · claimed 0.28 vs 0.56', when: 'Yesterday'},
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
            <div style={{fontSize: 12, color: T.ink3, marginTop: 2, lineHeight: 1.4}}>{e.meta}</div>
            <div style={{fontSize: 11, color: T.ink4, marginTop: 4}}>{e.when}</div>
          </div>
        </div>
      ))}
      <div style={{padding: '12px 20px', borderTop: `1px solid ${T.line}`, textAlign: 'center'}}>
        <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View full audit log →</a>
      </div>
    </div>
  );
};

// ============================================================
// 3.2 — STAFF USER LIST
// ============================================================
const StaffList = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('staff')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Staff users" breadcrumb={['Admin', 'Staff users']} user={tenantUser} actions={
      <Button variant="primary" icon="plus">Invite staff member</Button>
    } />}
  >
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>24</span></Chip>
          <Chip count={2}>Tenant Admin</Chip>
          <Chip count={8}>China Office</Chip>
          <Chip count={11}>Nigeria Office</Chip>
          <Chip count={3}>Warehouse</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Search by name or email…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" trailing="chevdown">Status: All</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'User', sortable: true},
          {title: 'Role'},
          {title: 'Status'},
          {title: 'Last login'},
          {title: 'Created', sortable: true},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [<UserCell name="Amara Okafor" email="amara@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>4 min ago</span>, <span style={{fontSize: 12, color: T.ink3}}>14 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Olumide Bello" email="olumide@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>2 hours ago</span>, <span style={{fontSize: 12, color: T.ink3}}>14 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Kwame Asante" email="kwame@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>1 hour ago</span>, <span style={{fontSize: 12, color: T.ink3}}>22 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Mei Lin Zhang" email="mei@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="warning">Pending invite</Badge>, <span style={{fontSize: 12, color: T.ink4}}>—</span>, <span style={{fontSize: 12, color: T.ink3}}>12 Apr 2026</span>, <KebabBtn />], selected: true},
          {cells: [<UserCell name="Adaeze Eze" email="adaeze@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>2 days ago</span>, <span style={{fontSize: 12, color: T.ink3}}>18 Mar 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Ifeoma Uche" email="ifeoma@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>3 hours ago</span>, <span style={{fontSize: 12, color: T.ink3}}>25 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Chinedu Obi" email="chinedu@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>Yesterday</span>, <span style={{fontSize: 12, color: T.ink3}}>08 Feb 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Bola Adetunji" email="bola@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="neutral">Suspended</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 days ago</span>, <span style={{fontSize: 12, color: T.ink3}}>04 Mar 2026</span>, <KebabBtn />], suspended: true},
          {cells: [<UserCell name="Funmi Adesina" email="funmi@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>Today, 11:08</span>, <span style={{fontSize: 12, color: T.ink3}}>14 Feb 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Taiwo Adeyemi" email="taiwo@acmelogistics.com" />, <Badge variant="warning">Warehouse</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>Today, 09:42</span>, <span style={{fontSize: 12, color: T.ink3}}>02 Feb 2026</span>, <KebabBtn />]},
        ]}
      />
      <TablePagination />
    </Card>

    {withModal && <InviteStaffModal />}
  </PageShell>
);

// ============================================================
// 3.3 — INVITE STAFF MODAL
// ============================================================
const InviteStaffModal = () => (
  <ModalOverlay>
    <div style={{
      width: 560, background: '#fff', borderRadius: 14,
      boxShadow: T.shadowModal, fontFamily: T.body,
    }}>
      {/* Header */}
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Invite a staff member</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>They'll receive an email to set their password and access their portal.</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      {/* Body */}
      <div style={{padding: '20px 24px'}}>
        <Field label="Full name" required value="Mei Lin Zhang" />
        <Field label="Email address" required value="mei@acmelogistics.com" type="email" icon="mail" helper="Used to sign in. Cannot be changed later." />
        <Field label="Role" required>
          <div style={{
            height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
            display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer',
          }}>
            <Badge variant="info" size="sm">China Office Staff</Badge>
            <span style={{flex: 1}} />
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderLeft: `3px solid ${T.info}`, borderRadius: 8, padding: '12px 14px', marginTop: -8, marginBottom: 16}}>
          <div style={{fontSize: 12, fontWeight: 700, color: T.ink2, marginBottom: 4}}>What China Office Staff can do</div>
          <div style={{fontSize: 12, color: T.ink3, lineHeight: 1.5}}>Create packing lists, manage containers in China, submit for approval, and update China-side tracking stages (received → packed → in transit).</div>
        </div>
      </div>
      {/* Footer */}
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="mail">Send invite</Button>
      </div>
    </div>
  </ModalOverlay>
);

const ModalOverlay = ({children}) => (
  <div style={{
    position: 'absolute', inset: 0,
    background: 'rgba(11,47,13,0.55)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 100, padding: 32,
  }}>{children}</div>
);

// ============================================================
// 3.4 — STAFF USER PROFILE
// ============================================================
const StaffProfile = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('staff')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" breadcrumb={['Admin', 'Staff users', 'Kwame Asante']} user={tenantUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <Avatar size={64} name="Kwame Asante" color={T.info} />
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Kwame Asante</h1>
            <Badge variant="info">China Office</Badge>
            <Badge variant="success">Active</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8}}>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
              <span style={{display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: T.success, boxShadow: `0 0 0 3px ${T.success}22`}} />
              Online — last active 1 hour ago
            </span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Joined 22 January 2026</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="mail">Send password reset</Button>
        <Button variant="primary" icon="edit">Edit profile</Button>
      </div>
    </div>

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Profile card */}
      <Card>
        <SectionHead title="Profile" sub="Account and contact information" />
        <div style={{height: 8}} />
        <Kvp label="Full name" value="Kwame Asante" />
        <Kvp label="Email" value={<><Mono>kwame@acmelogistics.com</Mono> <Badge variant="neutral" size="sm" dot={false}>Verified</Badge></>} />
        <Kvp label="Phone" value={<Mono>+86 138 9420 8841</Mono>} />
        <Kvp label="Role" value={<Badge variant="info">China Office Staff</Badge>} />
        <Kvp label="Reports to" value="Amara Okafor (Tenant Admin)" />
        <Kvp label="Created" value="22 January 2026 · invited by Amara Okafor" />
        <Kvp label="Last password reset" value="14 February 2026" divider={false} />
      </Card>

      {/* Permissions card */}
      <Card>
        <SectionHead title="Permissions" sub="What this role can do in Shipx" />
        <div style={{height: 12}} />
        <PermItem icon="package" allowed label="Packing lists" sub="Create, edit, submit for approval" />
        <PermItem icon="container" allowed label="Containers (China-side)" sub="Create, update status: received → packed → in transit" />
        <PermItem icon="file" allowed label="Container documents" sub="Upload Bill of Lading, customs forms" />
        <PermItem icon="users" denied label="Customer management" sub="View only · cannot edit or anonymise" />
        <PermItem icon="coin" denied label="Billing & payments" sub="No access" />
        <PermItem icon="card" denied label="Release notes" sub="Nigeria Office only" />
      </Card>
    </div>

    {/* Activity */}
    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Recent activity" sub="Last 7 days · 48 actions" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View full log →</a>} />
      </div>
      <Table
        dense
        columns={[
          {title: 'When'},
          {title: 'Action'},
          {title: 'Entity'},
          {title: 'Details'},
        ]}
        rows={[
          {cells: [<Mono color={T.ink2}>Today 12:08</Mono>, <Badge variant="success" size="sm">CREATE</Badge>, <span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>packing_list</span>, <span style={{fontSize: 12, color: T.ink3}}>PL-20260415-012 · 14 cartons</span>]},
          {cells: [<Mono color={T.ink2}>Today 09:41</Mono>, <Badge variant="info" size="sm">UPDATE</Badge>, <span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>container</span>, <span style={{fontSize: 12, color: T.ink3}}>MSCU1234567 · in_transit</span>]},
          {cells: [<Mono color={T.ink2}>Yesterday 16:22</Mono>, <Badge variant="success" size="sm">CREATE</Badge>, <span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>packing_list</span>, <span style={{fontSize: 12, color: T.ink3}}>PL-20260414-008 · 22 cartons</span>]},
          {cells: [<Mono color={T.ink2}>Yesterday 11:14</Mono>, <Badge variant="info" size="sm">UPDATE</Badge>, <span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>packing_list</span>, <span style={{fontSize: 12, color: T.ink3}}>PL-20260413-005 · submitted</span>]},
          {cells: [<Mono color={T.ink2}>13 Apr 14:30</Mono>, <Badge variant="success" size="sm">CREATE</Badge>, <span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>container</span>, <span style={{fontSize: 12, color: T.ink3}}>HLBU9384712 · Hapag-Lloyd</span>]},
        ]}
      />
    </Card>

    {/* Danger zone */}
    <Card style={{marginTop: 20, border: `1px solid ${T.error}55`, background: '#fffafa'}}>
      <SectionHead title={<span style={{color: T.error}}>Danger zone</span>} sub="Irreversible or high-impact actions on this user" />
      <div style={{height: 12}} />
      <DangerRow title="Reset password" sub="Send a password reset email. They'll be signed out of all sessions." btn="Reset password" variant="danger-outline" />
      <DangerRow title="Deactivate user" sub="Suspends sign-in. They can be reactivated later. All actions are preserved in audit log." btn="Deactivate" variant="danger-outline" />
      <DangerRow title="Delete user" sub="Permanently removes the account. Audit history is retained. Irreversible." btn="Delete user" variant="danger" last />
    </Card>
  </PageShell>
);

const PermItem = ({icon, label, sub, allowed, denied}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px dashed ${T.line}`}}>
    <div style={{
      width: 32, height: 32, borderRadius: 8,
      background: allowed ? T.greenSoft : T.line,
      color: allowed ? T.green : T.ink4,
      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
    }}>
      <Icon name={icon} size={14} />
    </div>
    <div style={{flex: 1, minWidth: 0}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.3}}>{label}</div>
      <div style={{fontSize: 12, color: T.ink4, lineHeight: 1.35}}>{sub}</div>
    </div>
    {allowed && <Icon name="check" size={16} color={T.success} stroke={2.5} />}
    {denied && <Icon name="x" size={16} color={T.ink4} stroke={2.5} />}
  </div>
);

const DangerRow = ({title, sub, btn, variant, last}) => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: last ? 'none' : `1px dashed ${T.line}`, gap: 16}}>
    <div style={{flex: 1}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.3}}>{title}</div>
      <div style={{fontSize: 12, color: T.ink3, marginTop: 2, lineHeight: 1.4}}>{sub}</div>
    </div>
    <Button variant={variant} size="sm">{btn}</Button>
  </div>
);

// ============================================================
// 3.5 — CUSTOMER LIST
// ============================================================
const CustomerList = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('customers')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Customers" breadcrumb={['Admin', 'Customers']} user={tenantUser} actions={
      <>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus">Add customer</Button>
      </>
    } />}
  >
    {/* GDPR banner */}
    <Banner variant="info" title="3 customers have been anonymised per GDPR requests">
      Anonymised records retain billing and shipment data for legal compliance, but personal information has been redacted.
    </Banner>
    <div style={{height: 16}} />

    {/* Stats summary */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Total customers" value="142" sublabel="139 active · 3 anonymised" accent={<Icon name="users" size={15} stroke={2.2} />} />
      <StatCard label="New this month" value="12" trend="+8" trendDir="up" sublabel="vs last month" accent={<Icon name="plus" size={15} stroke={2.2} />} />
      <StatCard label="Shipping this month" value="48" sublabel="of 142 active" accent={<Icon name="package" size={15} stroke={2.2} />} />
      <StatCard label="WhatsApp consented" value="124" sublabel="87% of active" accent={<Icon name="phone" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>142</span></Chip>
          <Chip count={139}>Active</Chip>
          <Chip count={3}>Anonymised</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Search by name, phone, or email…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="filter">Filters</Button>
        <Button variant="secondary" size="md" trailing="chevdown">Sort: Last shipment</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Customer', sortable: true},
          {title: 'Phone'},
          {title: 'Consent'},
          {title: 'Shipments', align: 'right'},
          {title: 'Outstanding', align: 'right'},
          {title: 'Last shipment'},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [
            <UserCell name="Ngozi Okonkwo" email="ngozi.okonkwo@gmail.com" />,
            <Mono>+234 801 234 5678</Mono>,
            <ConsentBlock channels={['sms', 'whatsapp', 'email']} />,
            <Mono>14</Mono>,
            <Mono color={T.warning}>₦24,352</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>2 days ago</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Adaeze Nwosu" email="adaeze.n@gmail.com" />,
            <Mono>+234 802 415 0922</Mono>,
            <ConsentBlock channels={['whatsapp']} />,
            <Mono>3</Mono>,
            <Mono color={T.ink3}>—</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>5 days ago</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Emeka Eze" email="emeka@ezeholdings.ng" />,
            <Mono>+234 803 762 4419</Mono>,
            <ConsentBlock channels={['sms', 'email']} />,
            <Mono>42</Mono>,
            <Mono color={T.error}>₦187,400</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>Today</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Chukwuemeka Nwogu" email="cnw@gmail.com" />,
            <Mono>+234 805 219 3382</Mono>,
            <ConsentBlock channels={['whatsapp', 'email']} />,
            <Mono>8</Mono>,
            <Mono color={T.success}>₦0</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>1 week ago</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Funmilayo Adeyemi" email="funmi.a@outlook.com" />,
            <Mono>+234 807 481 5510</Mono>,
            <ConsentBlock channels={['sms', 'whatsapp', 'email']} />,
            <Mono>21</Mono>,
            <Mono color={T.warning}>₦8,500</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>3 days ago</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="[ANONYMISED]" email="[anonymised per GDPR]" />,
            <Mono color={T.ink4}>+234 *** *** ****</Mono>,
            <span style={{fontSize: 11, color: T.ink4, fontStyle: 'italic'}}>Withdrawn</span>,
            <Mono>6</Mono>,
            <Mono color={T.ink3}>—</Mono>,
            <span style={{fontSize: 12, color: T.ink4, fontStyle: 'italic'}}>Anonymised 14 Mar</span>,
            <KebabBtn />,
          ], suspended: true},
          {cells: [
            <UserCell name="Bola Adesina" email="bola.a@gmail.com" />,
            <Mono>+234 809 124 7765</Mono>,
            <ConsentBlock channels={['whatsapp']} />,
            <Mono>11</Mono>,
            <Mono color={T.success}>₦0</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>4 days ago</span>,
            <KebabBtn />,
          ]},
          {cells: [
            <UserCell name="Ibrahim Musa" email="ibrahim@musatrade.co" />,
            <Mono>+234 813 442 8198</Mono>,
            <ConsentBlock channels={['sms', 'email']} />,
            <Mono>28</Mono>,
            <Mono color={T.warning}>₦12,800</Mono>,
            <span style={{fontSize: 12, color: T.ink3}}>Yesterday</span>,
            <KebabBtn />,
          ]},
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const ConsentBlock = ({channels}) => {
  const ic = {sms: 'phone', whatsapp: 'phone', email: 'mail'};
  const lbl = {sms: 'SMS', whatsapp: 'WA', email: 'EM'};
  return (
    <div style={{display: 'flex', gap: 4}}>
      {['sms', 'whatsapp', 'email'].map(c => {
        const on = channels.includes(c);
        return (
          <span key={c} title={c} style={{
            display: 'inline-flex', alignItems: 'center', gap: 3,
            padding: '2px 6px', borderRadius: 4,
            background: on ? T.greenSoft : T.line,
            color: on ? T.green : T.ink4,
            fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
          }}>{lbl[c]}</span>
        );
      })}
    </div>
  );
};

// ============================================================
// 3.6 — CUSTOMER PROFILE
// ============================================================
const CustomerProfile = ({tab = 'profile'}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('customers')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" breadcrumb={['Admin', 'Customers', 'Ngozi Okonkwo']} user={tenantUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <Avatar size={64} name="Ngozi Okonkwo" color={T.copper} />
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Ngozi Okonkwo</h1>
            <Badge variant="success">Active</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <Mono>+234 801 234 5678</Mono>
            <span style={{color: T.lineStrong}}>·</span>
            <span>ngozi.okonkwo@gmail.com</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Customer since 14 Feb 2026</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="mail">Message</Button>
        <Button variant="secondary" icon="edit">Edit</Button>
        <Button variant="danger-outline" icon="dot3">Actions</Button>
      </div>
    </div>

    <Tabs tabs={['Profile', 'Shipments', 'Billing', 'Claims', 'Data export']} active={
      tab === 'profile' ? 'Profile' :
      tab === 'shipments' ? 'Shipments' :
      tab === 'billing' ? 'Billing' :
      tab === 'claims' ? 'Claims' : 'Data export'
    } />

    {tab === 'profile' && <CustomerProfileTab />}
    {tab === 'shipments' && <CustomerShipmentsTab />}
    {tab === 'billing' && <CustomerBillingTab />}
  </PageShell>
);

const CustomerProfileTab = () => (
  <>
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      <Card>
        <SectionHead title="Contact" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit →</a>} />
        <div style={{height: 8}} />
        <Kvp label="Full name" value="Ngozi Okonkwo" />
        <Kvp label="Email" value={<Mono>ngozi.okonkwo@gmail.com</Mono>} />
        <Kvp label="Phone" value={<Mono>+234 801 234 5678</Mono>} />
        <Kvp label="WhatsApp" value={<Mono>+234 801 234 5678</Mono>} />
        <Kvp label="Address" value={<span style={{textAlign: 'right'}}>14 Adeniran Ogunsanya St<br />Surulere, Lagos 101241</span>} />
        <Kvp label="Contract notes" value={<span style={{fontSize: 12, color: T.ink3, fontStyle: 'italic'}}>Net-30 terms · 5% volume discount</span>} divider={false} />
      </Card>

      <Card>
        <SectionHead title="Consent & GDPR" sub="Per Article 6 — lawful processing basis" />
        <div style={{height: 12}} />
        <Kvp label="Consent given" value="14 Feb 2026 · self-registered" />
        <Kvp label="Lawful basis" value={<Badge variant="success" size="sm">Consent (Art. 6(1)(a))</Badge>} />
        <div style={{padding: '10px 0', borderBottom: `1px dashed ${T.line}`}}>
          <div style={{fontSize: 12, color: T.ink4, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6}}>Notification channels</div>
          <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
            <Badge variant="success">SMS</Badge>
            <Badge variant="success">WhatsApp</Badge>
            <Badge variant="success">Email</Badge>
          </div>
        </div>
        <Kvp label="Marketing consent" value={<Badge variant="neutral" size="sm">Not granted</Badge>} />
        <Kvp label="Anonymised at" value={<span style={{fontSize: 12, color: T.ink4}}>—</span>} divider={false} />
      </Card>
    </div>

    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Total shipments" value="14" sublabel="all time" accent={<Icon name="package" size={15} stroke={2.2} />} />
      <StatCard label="Total billed" value="₦1.84" suffix="M" sublabel="all time" accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Outstanding" value="₦24,352" trendDir="down" sublabel="1 billing record" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Open claims" value="0" sublabel="no active disputes" accent={<Icon name="check" size={15} stroke={2.2} />} />
    </div>

    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Recent activity" sub="Last 7 events for this customer" />
      </div>
      <Table
        dense
        columns={[{title: 'When'}, {title: 'Event'}, {title: 'Reference'}, {title: 'Details'}]}
        rows={[
          {cells: [<Mono color={T.ink2}>Today 14:32</Mono>, <Badge variant="success" size="sm">PAYMENT</Badge>, <Mono color={T.ink4}>BL-20260415-001</Mono>, <span style={{fontSize: 12, color: T.ink3}}>₦49,352 confirmed · Zenith Bank</span>]},
          {cells: [<Mono color={T.ink2}>Today 09:08</Mono>, <Badge variant="info" size="sm">STATUS</Badge>, <Mono color={T.ink4}>MSCU1234567</Mono>, <span style={{fontSize: 12, color: T.ink3}}>Container cleared customs</span>]},
          {cells: [<Mono color={T.ink2}>14 Apr 16:20</Mono>, <Badge variant="info" size="sm">STATUS</Badge>, <Mono color={T.ink4}>MSCU1234567</Mono>, <span style={{fontSize: 12, color: T.ink3}}>Arrived Tin Can Port · Bay 4</span>]},
          {cells: [<Mono color={T.ink2}>10 Apr 11:42</Mono>, <Badge variant="success" size="sm">CREATE</Badge>, <Mono color={T.ink4}>PL-20260410-008</Mono>, <span style={{fontSize: 12, color: T.ink3}}>Packing list · 4 cartons · 0.56 CBM</span>]},
          {cells: [<Mono color={T.ink2}>08 Apr 14:15</Mono>, <Badge variant="warning" size="sm">CONSENT</Badge>, <span style={{fontSize: 12, color: T.ink4}}>—</span>, <span style={{fontSize: 12, color: T.ink3}}>Updated WhatsApp consent to "Yes"</span>]},
        ]}
      />
    </Card>
  </>
);

const CustomerShipmentsTab = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px'}}>
      <SectionHead title="Shipments · Ngozi Okonkwo" sub="14 total · 1 in transit" />
    </div>
    <Table
      columns={[
        {title: 'Tracking code'},
        {title: 'Container'},
        {title: 'Status'},
        {title: 'Cartons', align: 'right'},
        {title: 'CBM', align: 'right'},
        {title: 'Last update'},
        {title: '', width: 40},
      ]}
      rows={[
        {cells: [<Mono>SHX-2026-NGOZI-014</Mono>, <Mono>MSCU1234567</Mono>, <Badge variant="info">In transit</Badge>, <Mono>4</Mono>, <Mono>0.56</Mono>, <span style={{fontSize: 12, color: T.ink3}}>Today 09:08</span>, <ViewLink />]},
        {cells: [<Mono>SHX-2026-NGOZI-013</Mono>, <Mono>COSU7194820</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>6</Mono>, <Mono>0.84</Mono>, <span style={{fontSize: 12, color: T.ink3}}>02 Apr 2026</span>, <ViewLink />]},
        {cells: [<Mono>SHX-2026-NGOZI-012</Mono>, <Mono>ONEU2847510</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>3</Mono>, <Mono>0.32</Mono>, <span style={{fontSize: 12, color: T.ink3}}>14 Mar 2026</span>, <ViewLink />]},
        {cells: [<Mono>SHX-2026-NGOZI-011</Mono>, <Mono>MAEU4729183</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>8</Mono>, <Mono>1.12</Mono>, <span style={{fontSize: 12, color: T.ink3}}>28 Feb 2026</span>, <ViewLink />]},
        {cells: [<Mono>SHX-2026-NGOZI-010</Mono>, <Mono>HLBU8473892</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>5</Mono>, <Mono>0.74</Mono>, <span style={{fontSize: 12, color: T.ink3}}>14 Feb 2026</span>, <ViewLink />]},
      ]}
    />
  </Card>
);

const CustomerBillingTab = () => (
  <>
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Total billed" value="₦1.84" suffix="M" sublabel="across 14 shipments" accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Total paid" value="₦1.81" suffix="M" sublabel="98.3% collected" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Outstanding" value="₦24,352" sublabel="1 record" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Carryovers" value="₦0" sublabel="no credit balance" accent={<Icon name="refresh" size={15} stroke={2.2} />} />
    </div>

    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Billing records" action={<Button variant="secondary" size="sm" icon="download">Export</Button>} />
      </div>
      <Table
        columns={[
          {title: 'Reference'},
          {title: 'Container'},
          {title: 'Total NGN', align: 'right'},
          {title: 'Paid', align: 'right'},
          {title: 'Outstanding', align: 'right'},
          {title: 'Status'},
          {title: 'Billed', sortable: true},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [<Mono>BL-20260415-001</Mono>, <Mono>MSCU1234567</Mono>, <Mono>₦73,704</Mono>, <Mono color={T.success}>₦49,352</Mono>, <Mono color={T.warning}>₦24,352</Mono>, <Badge variant="warning">Partial</Badge>, <span style={{fontSize: 12, color: T.ink3}}>15 Apr</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260402-018</Mono>, <Mono>COSU7194820</Mono>, <Mono>₦110,880</Mono>, <Mono color={T.success}>₦110,880</Mono>, <Mono color={T.ink3}>—</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>02 Apr</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260314-008</Mono>, <Mono>ONEU2847510</Mono>, <Mono>₦42,240</Mono>, <Mono color={T.success}>₦42,240</Mono>, <Mono color={T.ink3}>—</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 Mar</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260228-022</Mono>, <Mono>MAEU4729183</Mono>, <Mono>₦147,840</Mono>, <Mono color={T.success}>₦147,840</Mono>, <Mono color={T.ink3}>—</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>28 Feb</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260214-031</Mono>, <Mono>HLBU8473892</Mono>, <Mono>₦97,680</Mono>, <Mono color={T.success}>₦97,680</Mono>, <Mono color={T.ink3}>—</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 Feb</span>, <ViewLink />]},
        ]}
      />
    </Card>
  </>
);

Object.assign(window, {
  TenantDashboard, StaffList, InviteStaffModal, StaffProfile, CustomerList, CustomerProfile,
});
