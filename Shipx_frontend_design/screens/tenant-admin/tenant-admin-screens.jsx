// ============================================================
// Shipx — Tenant Admin Portal Screens (Section 3)
// 3.1 Dashboard · 3.2 Staff User List · 3.3 Invite Modal
// 3.4 Staff Profile · 3.5 Customer List · 3.6 Customer Profile
// ============================================================

const tenantSidebarItems = (active = 'dashboard') => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard', active: active === 'dashboard'},
    {icon: 'chart', label: 'Reports', active: active === 'reports'},
  ]},
  {group: 'Operations', items: [
    {icon: 'users', label: 'Customers', active: active === 'customers', count: '142'},
    {icon: 'user', label: 'Staff users', active: active === 'users', count: '24'},
  ]},
  {group: 'Configuration', items: [
    {icon: 'settings', label: 'Company settings', active: active === 'settings'},
    {icon: 'coin', label: 'Dollar rate', active: active === 'fx'},
    {icon: 'package', label: 'CBM rate', active: active === 'cbm'},
    {icon: 'file', label: 'Charge types', active: active === 'charges'},
    {icon: 'bell', label: 'Notification templates', active: active === 'templates'},
  ]},
];

const tenantBrand = <TenantBrand name="Acme Logistics" logo="AL" />;
const tenantUser = {name: 'Amara Okafor', role: 'Tenant Admin'};

// ============================================================
// 3.1 — TENANT ADMIN DASHBOARD
// ============================================================
const TenantAdminDashboard = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('dashboard')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" user={tenantUser} actions={<DateRangeButton />} notifications={5} />}
  >
    {/* Greeting */}
    <div style={{marginBottom: 20}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.green, letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6}}>Saturday, 16 May 2026</div>
      <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em'}}>Good morning, Amara.</h1>
      <p style={{fontSize: 14, color: T.ink3, margin: '4px 0 0'}}>3 containers arrive this week. <a style={{color: T.green, fontWeight: 600}}>2 packing lists need your approval →</a></p>
    </div>

    {/* Stat row */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Active customers" value="142" trend="+12" trendDir="up" sublabel="this month"
        accent={<Icon name="users" size={15} />} />
      <StatCard label="Containers this month" value="14" trend="3 in transit" trendDir="up" sublabel=""
        accent={<Icon name="container" size={15} />} />
      <StatCard label="Outstanding billing" value="₦4.2" suffix="M" trend="8 customers" trendDir="up" sublabel=""
        accent={<Icon name="coin" size={15} />} />
      <StatCard label="Open claims" value="3" sublabel="2 damage, 1 missing"
        accent={<Icon name="alert" size={15} />} />
    </div>

    {/* Two columns */}
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 360px', gap: 24, marginBottom: 24}}>
      {/* Recent containers */}
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent containers" sub="Latest 6 containers · all customers" action={
            <a style={{color: T.green, fontSize: 13, fontWeight: 600}}>View all →</a>
          } />
        </div>
        <Table
          dense
          columns={[
            {title: 'Container'},
            {title: 'Status'},
            {title: 'Customers', align: 'right'},
            {title: 'Packing lists', align: 'right'},
            {title: 'Billing'},
            {title: '', width: 40},
          ]}
          rows={[
            {cells: [
              <ContainerCell num="MSCU1234567" sub="GZG → LOS · MSC Altair" />,
              <Badge variant="info">In transit</Badge>,
              <Mono>12</Mono>, <Mono>10 / 12</Mono>,
              <Badge variant="warning" size="sm">3 unpaid</Badge>,
              <KebabBtn />,
            ]},
            {cells: [
              <ContainerCell num="HLBU9384712" sub="SHA → LOS · Hapag Tokyo" />,
              <Badge variant="warning">Customs</Badge>,
              <Mono>8</Mono>, <Mono>8 / 8</Mono>,
              <Badge variant="success" size="sm">All paid</Badge>,
              <KebabBtn />,
            ]},
            {cells: [
              <ContainerCell num="COSU7194820" sub="GZG → LOS · COSCO Star" />,
              <Badge variant="success">Cleared</Badge>,
              <Mono>15</Mono>, <Mono>15 / 15</Mono>,
              <Badge variant="warning" size="sm">5 unpaid</Badge>,
              <KebabBtn />,
            ]},
            {cells: [
              <ContainerCell num="ONEU2847510" sub="SHA → LOS · One Apus" />,
              <Badge variant="success">Delivered</Badge>,
              <Mono>9</Mono>, <Mono>9 / 9</Mono>,
              <Badge variant="success" size="sm">All paid</Badge>,
              <KebabBtn />,
            ]},
            {cells: [
              <ContainerCell num="MAEU4729183" sub="NGB → LOS · Maersk Edmonton" />,
              <Badge variant="accent">Discrepancy</Badge>,
              <Mono>11</Mono>, <Mono>11 / 11</Mono>,
              <Badge variant="warning" size="sm">2 unpaid</Badge>,
              <KebabBtn />,
            ]},
            {cells: [
              <ContainerCell num="EVNU8217305" sub="SHA → LOS · Ever Given" />,
              <Badge variant="info">Acknowledged</Badge>,
              <Mono>6</Mono>, <Mono>2 / 6</Mono>,
              <Badge variant="neutral" size="sm">Not billed</Badge>,
              <KebabBtn />,
            ]},
          ]}
        />
      </Card>

      {/* Activity */}
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent activity" sub="Customer & operational events" />
        </div>
        <ActivityFeedTenant />
      </Card>
    </div>

    {/* Bottom row — quick actions */}
    <SectionHead title="Quick actions" />
    <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16}}>
      <QuickActionCard icon="plus" title="Add customer" sub="Manually onboard a customer and capture their notification consent." cta="Add customer" />
      <QuickActionCard icon="container" title="Create container" sub="Register a new container and start adding packing lists for your customers." cta="Create container" accent />
      <QuickActionCard icon="file" title="Generate billing" sub="Generate billing for a cleared container. CBM × rate, plus any extras." cta="Generate billing" />
    </div>
  </PageShell>
);

const ContainerCell = ({num, sub}) => (
  <div>
    <Mono color={T.ink}><strong>{num}</strong></Mono>
    <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{sub}</div>
  </div>
);

const ActivityFeedTenant = () => {
  const events = [
    {icon: 'user', color: T.green, title: 'New customer registered', meta: 'Ngozi Okonkwo · self-signup', when: '4 min ago'},
    {icon: 'container', color: T.success, title: 'Container cleared customs', meta: 'COSU7194820 · 15 customers notified', when: '1h ago'},
    {icon: 'coin', color: T.green, title: 'Payment confirmed', meta: '₦49,352 · Ngozi Okonkwo · TRF reference', when: '2h ago'},
    {icon: 'file', color: T.info, title: 'Billing generated', meta: 'COSU7194820 · 15 customers · ₦8.2M total', when: '3h ago'},
    {icon: 'alert', color: T.warning, title: 'CBM dispute filed', meta: 'Adaeze Nwosu · SHX-04781 · 0.28 → 0.56', when: '5h ago'},
    {icon: 'package', color: T.copper, title: 'Release note issued', meta: 'RN-029-MSCU · 4 cartons · Ngozi Okonkwo', when: 'Today, 09:08'},
    {icon: 'truck', color: T.success, title: 'Pickup completed', meta: '3 cartons · Emeka Eze · Taiwo Adeyemi', when: 'Yesterday'},
    {icon: 'log', color: T.info, title: 'New staff member', meta: 'Mei Lin Zhang · China Office · invite sent', when: 'Yesterday'},
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
            <div style={{fontSize: 11, color: T.ink4, marginTop: 4}}>{e.when}</div>
          </div>
        </div>
      ))}
      <div style={{padding: '12px 20px', borderTop: `1px solid ${T.line}`, textAlign: 'center'}}>
        <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View full activity log →</a>
      </div>
    </div>
  );
};

// ============================================================
// 3.2 — STAFF USER LIST
// ============================================================
const StaffUserList = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('users')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Staff users" breadcrumb={['Operations', 'Staff users']} user={tenantUser} actions={
      <Button variant="primary" icon="plus">Invite staff member</Button>
    } />}
  >
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>24</span></Chip>
          <Chip count={2}>Tenant Admin</Chip>
          <Chip count={8}>China Office</Chip>
          <Chip count={11}>Nigeria Office</Chip>
          <Chip count={3}>Warehouse</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <Field>
            <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
              <Icon name="search" size={14} color={T.ink4} />
              <input placeholder="Search by name or email…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
            </div>
          </Field>
        </div>
        <Button variant="secondary" trailing="chevdown">Status: All</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'User', sortable: true},
          {title: 'Role'},
          {title: 'Status'},
          {title: 'Last login', sortable: true},
          {title: 'Created'},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [<UserCell name="Amara Okafor" email="amara@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>4 min ago</span>, <span style={{fontSize: 12, color: T.ink3}}>14 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Olu Bello" email="olu@acmelogistics.com" />, <Badge variant="primary">Tenant Admin</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>1 hour ago</span>, <span style={{fontSize: 12, color: T.ink3}}>18 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Kwame Asante" email="kwame@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>1 hour ago</span>, <span style={{fontSize: 12, color: T.ink3}}>22 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Mei Lin Zhang" email="mei@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="warning">Pending invite</Badge>, <span style={{fontSize: 12, color: T.ink4}}>—</span>, <span style={{fontSize: 12, color: T.ink3}}>12 Apr 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Adaeze Eze" email="adaeze@acmelogistics.com" />, <Badge variant="info">China Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>2 days ago</span>, <span style={{fontSize: 12, color: T.ink3}}>18 Mar 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Ifeoma Uche" email="ifeoma@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>3 hours ago</span>, <span style={{fontSize: 12, color: T.ink3}}>25 Jan 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Chinedu Obi" email="chinedu@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>Yesterday</span>, <span style={{fontSize: 12, color: T.ink3}}>08 Feb 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Bola Adetunji" email="bola@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="neutral">Suspended</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 days ago</span>, <span style={{fontSize: 12, color: T.ink3}}>04 Mar 2026</span>, <KebabBtn />], suspended: true},
          {cells: [<UserCell name="Tunde Akande" email="tunde@acmelogistics.com" />, <Badge variant="accent">Nigeria Office</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>30 min ago</span>, <span style={{fontSize: 12, color: T.ink3}}>11 Feb 2026</span>, <KebabBtn />]},
          {cells: [<UserCell name="Taiwo Adeyemi" email="taiwo@acmelogistics.com" />, <Badge variant="warning">Warehouse</Badge>, <Badge variant="success">Active</Badge>, <span style={{fontSize: 12, color: T.ink2}}>Today, 09:42</span>, <span style={{fontSize: 12, color: T.ink3}}>02 Feb 2026</span>, <KebabBtn />]},
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

// ============================================================
// 3.3 — INVITE STAFF MODAL
// ============================================================
const InviteStaffModal = ({state = 'form'}) => {
  return (
    <PageShell
      sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('users')} user={tenantUser} />}
      topbar={<TopBar role="admin" title="Staff users" breadcrumb={['Operations', 'Staff users']} user={tenantUser} />}
    >
      {/* Backdrop with table behind */}
      <div style={{position: 'relative'}}>
        <div style={{filter: 'blur(0.5px)', opacity: 0.6, pointerEvents: 'none'}}>
          <Card padding={16} style={{marginBottom: 16}}>
            <div style={{height: 36, background: T.page, borderRadius: 8}} />
          </Card>
          <Card padding={0}>
            <div style={{height: 400, background: '#fff'}} />
          </Card>
        </div>
        {/* Scrim */}
        <div style={{position: 'absolute', inset: -40, background: 'rgba(11,47,13,0.55)', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: 60}}>
          <div style={{
            width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal,
            fontFamily: T.body,
          }}>
            {state === 'success' ? <InviteSuccess /> : <InviteForm />}
          </div>
        </div>
      </div>
    </PageShell>
  );
};

const InviteForm = () => (
  <>
    <div style={{padding: '24px 28px 18px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, borderBottom: `1px solid ${T.line}`}}>
      <div>
        <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: T.ink, margin: 0, letterSpacing: '-0.015em'}}>Invite a staff member</h2>
        <p style={{fontSize: 13, color: T.ink3, margin: '4px 0 0'}}>They'll receive an email invite to set their password and log in.</p>
      </div>
      <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink3, borderRadius: 8, display: 'flex'}}><Icon name="x" size={18} /></button>
    </div>
    <div style={{padding: '20px 28px 4px'}}>
      <Field label="Full name" required placeholder="e.g. Chiamaka Igwe" value="Mei Lin Zhang" />
      <Field label="Email address" type="email" required placeholder="email@company.com" icon="mail" value="mei.lin@acmelogistics.com" helper="An invite email will be sent here. Email cannot be changed later." />
      <Field label="Role" required>
        <div style={{position: 'relative'}}>
          <div style={{
            height: 42, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
            display: 'flex', alignItems: 'center', padding: '0 14px', gap: 8, cursor: 'pointer',
          }}>
            <Badge variant="info">China Office</Badge>
            <span style={{flex: 1, fontSize: 13, color: T.ink}}>Staff member · China Office</span>
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </div>
      </Field>
      <div style={{background: T.infoSoft, border: `1px solid ${T.info}33`, borderLeft: `4px solid ${T.info}`, borderRadius: 8, padding: '12px 14px', fontSize: 13, color: T.infoStrong, lineHeight: 1.5, marginBottom: 16}}>
        <div style={{fontWeight: 700, marginBottom: 2}}>About this role</div>
        Create packing lists for customer cargo, register containers, manage manifests, and handle China-side documentation. Can not view financial billing.
      </div>
    </div>
    <div style={{padding: '16px 28px 24px', display: 'flex', justifyContent: 'flex-end', gap: 10, borderTop: `1px solid ${T.line}`, background: T.muted, borderRadius: '0 0 14px 14px'}}>
      <Button variant="ghost">Cancel</Button>
      <Button variant="primary" icon="mail">Send invite</Button>
    </div>
  </>
);

const InviteSuccess = () => (
  <div style={{padding: '44px 28px', textAlign: 'center'}}>
    <div style={{width: 72, height: 72, borderRadius: '50%', background: T.successSoft, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 18}}>
      <Icon name="check" size={36} color={T.success} stroke={2.5} />
    </div>
    <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: T.ink, margin: '0 0 6px', letterSpacing: '-0.015em'}}>Invite sent!</h3>
    <p style={{fontSize: 14, color: T.ink3, margin: 0, lineHeight: 1.5}}>
      An email invite has been sent to <strong style={{color: T.ink}}>mei.lin@acmelogistics.com</strong>. They'll set their password and join Acme Logistics as a China Office staff member.
    </p>
    <div style={{display: 'flex', gap: 10, justifyContent: 'center', marginTop: 24}}>
      <Button variant="secondary">Invite another</Button>
      <Button variant="primary">Done</Button>
    </div>
  </div>
);

// ============================================================
// 3.4 — STAFF USER PROFILE
// ============================================================
const StaffUserProfile = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('users')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" breadcrumb={['Operations', 'Staff users', 'Ifeoma Uche']} user={tenantUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <Avatar size={72} name="Ifeoma Uche" role="nigeria" />
        <div style={{minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.02em'}}>Ifeoma Uche</h1>
            <Badge variant="accent">Nigeria Office</Badge>
            <Badge variant="success">Active</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8}}>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
              <span style={{display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: T.success, boxShadow: `0 0 0 3px ${T.success}22`}} />
              Online — active 3 hours ago
            </span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>ifeoma@acmelogistics.com</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Joined 25 Jan 2026</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8, flexShrink: 0}}>
        <Button variant="secondary" icon="mail">Reset password</Button>
        <Button variant="primary" icon="edit">Edit role</Button>
      </div>
    </div>

    <Tabs tabs={['Profile', 'Activity', 'Permissions']} active="Profile" />

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
      <Card>
        <SectionHead title="Profile information" />
        <div style={{height: 12}} />
        <Field label="Full name" value="Ifeoma Uche" />
        <Field label="Email address" type="email" value="ifeoma@acmelogistics.com" icon="mail" disabled helper="Email cannot be changed after account creation. To update, deactivate and re-invite." />
        <Field label="Role" >
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 8, cursor: 'pointer'}}>
            <Badge variant="accent">Nigeria Office</Badge>
            <span style={{flex: 1, fontSize: 13, color: T.ink}}>Nigeria Office Staff</span>
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <Field label="Phone (for 2FA · optional)" icon="phone" value="+234 802 415 0922" optional />

        <div style={{display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 12, borderTop: `1px solid ${T.line}`, marginTop: 8}}>
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary">Save changes</Button>
        </div>
      </Card>

      <div>
        <Card style={{marginBottom: 20}}>
          <SectionHead title="Account summary" />
          <Kvp label="User ID" value={<Mono color={T.ink}>usr_8nM3xK2pQ</Mono>} />
          <Kvp label="Created by" value="Amara Okafor · 25 Jan 2026" />
          <Kvp label="Last login" value="3 hours ago · 192.168.4.42" />
          <Kvp label="Login sessions" value={<><strong>2 active</strong> · Lagos & Apapa</>} />
          <Kvp label="2FA enabled" value={<Badge variant="success" size="sm">Yes · SMS</Badge>} divider={false} />
        </Card>

        <Card style={{borderColor: T.error + '55'}}>
          <SectionHead title="Danger zone" sub="Irreversible & destructive actions" />
          <div style={{height: 12}} />
          <DangerRow
            title="Reset password"
            sub="Send a password reset email. The current session continues."
            cta="Send reset email"
            variant="secondary"
          />
          <DangerRow
            title="Deactivate user"
            sub="They lose access immediately. Their packing lists and audit history are retained."
            cta="Deactivate user"
            variant="danger-outline"
          />
        </Card>
      </div>
    </div>
  </PageShell>
);

const DangerRow = ({title, sub, cta, variant}) => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '14px 0', borderTop: `1px solid ${T.line}`}}>
    <div style={{flex: 1}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>{title}</div>
      <div style={{fontSize: 12, color: T.ink3, marginTop: 2}}>{sub}</div>
    </div>
    <Button variant={variant} size="sm">{cta}</Button>
  </div>
);

// ============================================================
// 3.5 — CUSTOMER LIST
// ============================================================
const CustomerList = ({hasGDPR = true}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('customers')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Customers" breadcrumb={['Operations', 'Customers']} user={tenantUser} actions={
      <>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus">Add customer</Button>
      </>
    } />}
  >
    {hasGDPR && (
      <div style={{marginBottom: 16}}>
        <Banner variant="info" title="3 customers have been anonymised" dismissible>
          Their billing and shipment records are retained for compliance, but personally identifiable information has been removed per GDPR Article 17 requests. <a style={{color: T.info, fontWeight: 700, textDecoration: 'underline'}}>View policy →</a>
        </Banner>
      </div>
    )}

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>142</span></Chip>
          <Chip count={139}>Active</Chip>
          <Chip count={3}>Anonymised</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <Field>
            <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
              <Icon name="search" size={14} color={T.ink4} />
              <input placeholder="Search by name, email, or phone…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
            </div>
          </Field>
        </div>
        <Button variant="secondary" icon="filter">Filters</Button>
        <Button variant="secondary" trailing="chevdown">Sort: Recent</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Customer', sortable: true},
          {title: 'Phone'},
          {title: 'Channels'},
          {title: 'Shipments', align: 'right'},
          {title: 'Last shipment'},
          {title: 'Registered'},
          {title: '', width: 40},
        ]}
        rows={[
          customerRow({name: 'Ngozi Okonkwo', email: 'ngozi.okonkwo@gmail.com', phone: '+234 801 234 5678', channels: ['SMS', 'WhatsApp', 'Email'], shipments: 12, lastShipment: '2 days ago', registered: '14 Jan 2026'}),
          customerRow({name: 'Adaeze Nwosu', email: 'adaeze.n@yahoo.com', phone: '+234 802 415 0922', channels: ['WhatsApp', 'Email'], shipments: 8, lastShipment: 'Today', registered: '22 Jan 2026'}),
          customerRow({name: 'Chukwuemeka Nwogu', email: 'emeka@nwogu.ng', phone: '+234 803 671 4400', channels: ['SMS'], shipments: 5, lastShipment: '4 days ago', registered: '08 Feb 2026'}),
          customerRow({name: 'Emeka Eze', email: 'emeka.eze@protonmail.com', phone: '+234 805 920 1144', channels: ['SMS', 'WhatsApp'], shipments: 18, lastShipment: 'Today', registered: '03 Nov 2025'}),
          customerRow({name: 'Funmi Adesanya', email: 'funmi@adesanyaltd.com', phone: '+234 807 224 6611', channels: ['Email'], shipments: 24, lastShipment: 'Yesterday', registered: '14 Sep 2025'}),
          customerRow({name: '[ANONYMISED]', email: '[redacted]', phone: '[redacted]', channels: ['—'], shipments: 4, lastShipment: '6 months ago', registered: '12 Apr 2025', anonymised: true}),
          customerRow({name: 'Ifeoma Eze-Onuora', email: 'ifeoma.ezeo@gmail.com', phone: '+234 809 117 4452', channels: ['SMS', 'WhatsApp', 'Email'], shipments: 6, lastShipment: '1 week ago', registered: '02 Feb 2026'}),
          customerRow({name: 'Babatunde Akinwale', email: 'tunde@akinwale.co', phone: '+234 810 422 7892', channels: ['SMS', 'WhatsApp'], shipments: 11, lastShipment: '3 days ago', registered: '11 Dec 2025'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const customerRow = ({name, email, phone, channels, shipments, lastShipment, registered, anonymised}) => ({
  suspended: anonymised,
  cells: [
    <div style={{display: 'flex', gap: 10, alignItems: 'center'}}>
      <Avatar size={32} name={anonymised ? '?' : name} color={anonymised ? T.line : T.green} />
      <div style={{minWidth: 0}}>
        <div style={{fontSize: 13, fontWeight: 600, color: anonymised ? T.ink4 : T.ink, lineHeight: 1.2, fontStyle: anonymised ? 'italic' : 'normal'}}>{name}</div>
        <div style={{fontSize: 11, color: T.ink4, lineHeight: 1.3, fontStyle: anonymised ? 'italic' : 'normal'}}>{email}</div>
      </div>
    </div>,
    <Mono color={anonymised ? T.ink4 : T.ink2}>{phone}</Mono>,
    <ChannelDots channels={channels} />,
    <Mono>{shipments}</Mono>,
    <span style={{fontSize: 12, color: T.ink3}}>{lastShipment}</span>,
    <span style={{fontSize: 12, color: T.ink3}}>{registered}</span>,
    <KebabBtn />,
  ],
});

const ChannelDots = ({channels}) => {
  const map = {SMS: T.info, WhatsApp: T.success, Email: T.copper};
  if (channels[0] === '—') return <span style={{color: T.ink4, fontFamily: T.mono, fontSize: 12}}>—</span>;
  return (
    <div style={{display: 'flex', gap: 4}}>
      {channels.map((c, i) => (
        <span key={i} title={c} style={{
          padding: '2px 8px', fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
          background: map[c] + '22', color: map[c],
          borderRadius: 4, textTransform: 'uppercase',
        }}>{c === 'WhatsApp' ? 'WA' : c === 'Email' ? 'EM' : c}</span>
      ))}
    </div>
  );
};

// ============================================================
// 3.6 — CUSTOMER PROFILE
// ============================================================
const CustomerProfile = ({tab = 'profile'}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={tenantSidebarItems('customers')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="" breadcrumb={['Operations', 'Customers', 'Ngozi Okonkwo']} user={tenantUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <Avatar size={72} name="Ngozi Okonkwo" color={T.green} />
        <div style={{minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.02em'}}>Ngozi Okonkwo</h1>
            <Badge variant="success">Verified</Badge>
            <Badge variant="primary" dot={false}>★ 12 shipments</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>
            ngozi.okonkwo@gmail.com · +234 801 234 5678 · Joined 14 January 2026
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8, flexShrink: 0}}>
        <Button variant="secondary" icon="mail">Send notification</Button>
        <Button variant="secondary" icon="download">Export data</Button>
        <Button variant="primary" icon="edit">Edit</Button>
      </div>
    </div>

    <Tabs tabs={['Profile', 'Shipments', 'Billing', 'Claims', 'Data export (GDPR)']} active={
      tab === 'profile' ? 'Profile' :
      tab === 'shipments' ? 'Shipments' :
      tab === 'billing' ? 'Billing' :
      tab === 'claims' ? 'Claims' :
      tab === 'gdpr' ? 'Data export (GDPR)' : 'Profile'
    } />

    {tab === 'profile' && <CustomerProfileTab />}
    {tab === 'shipments' && <CustomerShipmentsTab />}
    {tab === 'gdpr' && <CustomerGDPRTab />}
  </PageShell>
);

const CustomerProfileTab = () => (
  <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
    <Card>
      <SectionHead title="Contact information" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit →</a>} />
      <Kvp label="Full name" value="Ngozi Chinyere Okonkwo" />
      <Kvp label="Email" value={<Mono>ngozi.okonkwo@gmail.com</Mono>} />
      <Kvp label="Primary phone" value={<Mono>+234 801 234 5678</Mono>} />
      <Kvp label="WhatsApp" value={<Mono>+234 801 234 5678</Mono>} />
      <Kvp label="Address" value={<span style={{textAlign: 'right'}}>14 Adeniran Ogunsanya St<br />Surulere, Lagos 101241</span>} />
      <Kvp label="Contract details" value={<span style={{color: T.ink4, fontStyle: 'italic'}}>None on file</span>} divider={false} />
    </Card>

    <Card>
      <SectionHead title="Consent & GDPR" />
      <Kvp label="Consent given at" value="14 Jan 2026 · self-registered" />
      <Kvp label="Notification channels" value={<ChannelDots channels={['SMS', 'WhatsApp', 'Email']} />} />
      <Kvp label="Marketing opt-in" value={<Badge variant="neutral" size="sm">No</Badge>} />
      <Kvp label="Data retention" value={<span>Indefinite (active customer)</span>} />
      <Kvp label="Anonymised at" value={<span style={{color: T.ink4}}>—</span>} divider={false} />
      <div style={{marginTop: 16, padding: '12px 14px', background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 8, fontSize: 12, color: T.greenDeep, display: 'flex', gap: 10, alignItems: 'center'}}>
        <Icon name="check" size={16} color={T.green} stroke={2.5} />
        Fully compliant — all required consents captured at registration.
      </div>
    </Card>

    <Card>
      <SectionHead title="Notification preferences" sub="Channels the customer agreed to receive" />
      <div style={{height: 12}} />
      <NotificationPrefRow channel="SMS" enabled allow="All transactional updates" />
      <NotificationPrefRow channel="WhatsApp" enabled allow="All transactional updates" />
      <NotificationPrefRow channel="Email" enabled allow="Receipts and statements only" />
    </Card>

    <Card>
      <SectionHead title="Lifetime stats" />
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12}}>
        <MiniStat label="Total shipments" value="12" />
        <MiniStat label="Total spend" value="₦642k" />
        <MiniStat label="Avg. transit time" value="19d" />
        <MiniStat label="Open claims" value="0" />
      </div>
      <div style={{marginTop: 16, padding: '12px 14px', background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8, fontSize: 12, color: T.ink3}}>
        First shipment: <strong style={{color: T.ink}}>16 Jan 2026</strong> — Most recent: <strong style={{color: T.ink}}>2 days ago</strong>
      </div>
    </Card>
  </div>
);

const NotificationPrefRow = ({channel, enabled, allow}) => (
  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderTop: `1px solid ${T.line}`}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
      <Icon name={channel === 'Email' ? 'mail' : 'phone'} size={15} color={T.ink3} />
      <span style={{fontSize: 14, fontWeight: 600, color: T.ink}}>{channel}</span>
    </div>
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      <span style={{fontSize: 12, color: T.ink3}}>{allow}</span>
      <ToggleSwitch on={enabled} />
    </div>
  </div>
);

const ToggleSwitch = ({on}) => (
  <div style={{
    width: 36, height: 20, borderRadius: 999,
    background: on ? T.green : T.line,
    position: 'relative', cursor: 'pointer',
    transition: 'background .15s',
  }}>
    <div style={{
      position: 'absolute', top: 2, left: on ? 18 : 2,
      width: 16, height: 16, borderRadius: '50%', background: '#fff',
      boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      transition: 'left .15s',
    }} />
  </div>
);

const MiniStat = ({label, value}) => (
  <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8}}>
    <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em'}}>{label}</div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: T.ink, marginTop: 4, letterSpacing: '-0.01em'}}>{value}</div>
  </div>
);

const CustomerShipmentsTab = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px'}}>
      <SectionHead title="Shipment history" sub="12 total shipments" />
    </div>
    <Table
      columns={[
        {title: 'Tracking code'},
        {title: 'Container'},
        {title: 'Status'},
        {title: 'Cartons', align: 'right'},
        {title: 'CBM', align: 'right'},
        {title: 'Last updated'},
        {title: '', width: 40},
      ]}
      rows={[
        {cells: [<Mono>SHX-2026-NG-0042</Mono>, <Mono>MSCU1234567</Mono>, <Badge variant="info">In transit</Badge>, <Mono>4</Mono>, <Mono>0.56</Mono>, <span style={{fontSize: 12, color: T.ink3}}>4 hours ago</span>, <KebabBtn />]},
        {cells: [<Mono>SHX-2026-NG-0039</Mono>, <Mono>COSU7194820</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>2</Mono>, <Mono>0.18</Mono>, <span style={{fontSize: 12, color: T.ink3}}>2 days ago</span>, <KebabBtn />]},
        {cells: [<Mono>SHX-2026-NG-0034</Mono>, <Mono>HLBU9384712</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>6</Mono>, <Mono>0.84</Mono>, <span style={{fontSize: 12, color: T.ink3}}>8 Apr 2026</span>, <KebabBtn />]},
        {cells: [<Mono>SHX-2026-NG-0028</Mono>, <Mono>ONEU2847510</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>3</Mono>, <Mono>0.42</Mono>, <span style={{fontSize: 12, color: T.ink3}}>22 Mar 2026</span>, <KebabBtn />]},
        {cells: [<Mono>SHX-2026-NG-0019</Mono>, <Mono>MAEU4729183</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>5</Mono>, <Mono>0.62</Mono>, <span style={{fontSize: 12, color: T.ink3}}>04 Mar 2026</span>, <KebabBtn />]},
        {cells: [<Mono>SHX-2026-NG-0014</Mono>, <Mono>EVNU8217305</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>2</Mono>, <Mono>0.24</Mono>, <span style={{fontSize: 12, color: T.ink3}}>18 Feb 2026</span>, <KebabBtn />]},
      ]}
    />
    <TablePagination />
  </Card>
);

const CustomerGDPRTab = () => (
  <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
    <Card>
      <div style={{display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 16}}>
        <div style={{width: 40, height: 40, borderRadius: 10, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="download" size={18} />
        </div>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, margin: 0, color: T.ink}}>Right to portability</h3>
          <p style={{fontSize: 13, color: T.ink3, margin: '4px 0 0', lineHeight: 1.5}}>Download all data held for this customer in a machine-readable JSON bundle, per GDPR Article 20.</p>
        </div>
      </div>
      <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8, padding: 14, marginBottom: 16}}>
        <div style={{fontSize: 12, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Bundle includes</div>
        <BundleLine icon="user" label="Profile & contact info" detail="Name, email, phone, address" />
        <BundleLine icon="package" label="All shipments" detail="12 shipments · 36 packing lists" />
        <BundleLine icon="coin" label="Billing records" detail="11 billing records · 11 payment receipts" />
        <BundleLine icon="alert" label="Claims & disputes" detail="0 records" />
        <BundleLine icon="bell" label="Consent history" detail="3 events captured" />
      </div>
      <div style={{fontSize: 12, color: T.ink4, marginBottom: 12}}>Last export: 14 Mar 2026 (by Amara Okafor)</div>
      <Button variant="primary" icon="download" full>Generate data export</Button>
    </Card>

    <Card style={{borderColor: T.error + '55'}}>
      <div style={{display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 16}}>
        <div style={{width: 40, height: 40, borderRadius: 10, background: T.errorSoft, color: T.error, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="user" size={18} />
        </div>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, margin: 0, color: T.ink}}>Right to erasure</h3>
          <p style={{fontSize: 13, color: T.ink3, margin: '4px 0 0', lineHeight: 1.5}}>Anonymise the customer record per GDPR Article 17. Shipment & billing records are retained for legal compliance but PII is irreversibly removed.</p>
        </div>
      </div>
      <Banner variant="error" title="This action is irreversible">
        Once anonymised, the customer's name, email, phone, and address are permanently overwritten. They can no longer log in. Billing and shipping data persist for the statutory 7-year retention window.
      </Banner>
      <div style={{height: 16}} />
      <Field label="Type 'ANONYMISE' to confirm" placeholder="ANONYMISE" />
      <Field label="Reason (logged for audit)" multiline placeholder="Customer email request — ref #SUP-2026-0421" />
      <Button variant="danger-outline" icon="alert" full>Anonymise customer record</Button>
    </Card>
  </div>
);

const BundleLine = ({icon, label, detail}) => (
  <div style={{display: 'flex', gap: 10, alignItems: 'center', padding: '6px 0'}}>
    <Icon name={icon} size={14} color={T.ink4} />
    <div style={{flex: 1, fontSize: 13, color: T.ink2, fontWeight: 500}}>{label}</div>
    <div style={{fontSize: 12, color: T.ink4}}>{detail}</div>
  </div>
);

Object.assign(window, {
  TenantAdminDashboard,
  StaffUserList,
  InviteStaffModal,
  StaffUserProfile,
  CustomerList,
  CustomerProfile,
});
