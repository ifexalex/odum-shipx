// ============================================================
// Shipx — Nigeria Office Staff Screens (Section 6)
// 6.1 Operations Dashboard · 6.2 Manifest List
// 6.3 Manifest Detail · 6.4 Update Container Status
// ============================================================

const ngSidebarItems = (active) => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard', active: active === 'dashboard'},
  ]},
  {group: 'Operations', items: [
    {icon: 'container', label: 'Containers', active: active === 'containers'},
    {icon: 'refresh', label: 'Tracking updates', active: active === 'tracking', badge: {color: T.warning, count: '3'}},
    {icon: 'file', label: 'Manifests', active: active === 'manifests', badge: {color: T.warning, count: '3'}},
    {icon: 'package', label: 'Packing lists', active: active === 'pls'},
  ]},
  {group: 'Billing', items: [
    {icon: 'coin', label: 'Billing', active: active === 'billing'},
    {icon: 'refresh', label: 'Carryovers', active: active === 'carryovers'},
    {icon: 'warn', label: 'CBM disputes', active: active === 'disputes', badge: {color: T.error, count: '2'}},
  ]},
  {group: 'Customer service', items: [
    {icon: 'warn', label: 'Damage claims', active: active === 'damage'},
    {icon: 'package', label: 'Missing items', active: active === 'missing'},
    {icon: 'shield', label: 'Seized items', active: active === 'seized'},
    {icon: 'card', label: 'Release notes', active: active === 'release'},
    {icon: 'refresh', label: 'Refunds', active: active === 'refunds'},
  ]},
];

const ngUser = {name: 'Ifeoma Uche', role: 'Nigeria Office Staff'};

// ============================================================
// 6.1 — OPERATIONS DASHBOARD
// ============================================================
const NgOpsDashboard = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('dashboard')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" user={ngUser} actions={<DateRangeButton />} />}
  >
    {/* Greeting */}
    <div style={{marginBottom: 20}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.copper, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Operations dashboard</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Today, Mon 28 July 2026.</h2>
      <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>Lagos · Tin Can Port · 32°C · light rain expected · 14 containers active.</p>
    </div>

    {/* Urgent actions panel */}
    <Card padding={20} style={{marginBottom: 20, background: T.warningSoft, borderColor: T.warning + '55', borderLeft: `4px solid ${T.warning}`}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14}}>
        <Icon name="warn" size={18} color={T.warning} stroke={2.5} />
        <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, margin: 0, color: T.warningStrong, letterSpacing: '-0.005em'}}>
          Needs your attention now
        </h3>
        <Badge variant="warning" size="sm" dot={false}>3 actions</Badge>
      </div>
      <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12}}>
        <UrgentAction
          icon="file" count="3" title="Containers awaiting manifest verification"
          sub="HLBU9384712 arrived this morning. SUDU3819273 since yesterday."
          cta="Verify now"
        />
        <UrgentAction
          icon="package" count="5" title="Packing lists pending approval"
          sub="On 2 containers · oldest 4 hours ago"
          cta="Review queue"
        />
        <UrgentAction
          icon="warn" count="2" title="CBM disputes need response"
          sub="Ngozi Okonkwo · Adaeze Nwosu · both filed yesterday"
          cta="Open disputes"
          danger
        />
      </div>
    </Card>

    {/* Stat row */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Containers at customs" value="4" sublabel="2 delayed · 2 routine"
        accent={<Icon name="shield" size={15} stroke={2.2} />} />
      <StatCard label="Awaiting payment" value="₦4.2" suffix="M" trend="−18%" trendDir="down" sublabel="vs last week"
        accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Open claims" value="6" sublabel="2 damage · 3 missing · 1 seized"
        accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Ready for pickup" value="11" sublabel="oldest 2 days old"
        accent={<Icon name="card" size={15} stroke={2.2} />} />
    </div>

    {/* Pipeline kanban */}
    <Card style={{marginBottom: 24, overflow: 'hidden'}}>
      <SectionHead title="Container pipeline" sub="Live status across all Nigeria-side stages" action={
        <a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Open pipeline →</a>
      } />
      <div style={{height: 16}} />
      <PipelineKanban />
    </Card>

    {/* Two col bottom */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent payments" sub="Last 24 hours · all confirmed" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <Table
          dense
          columns={[
            {title: 'Customer'},
            {title: 'Amount', align: 'right'},
            {title: 'Container'},
            {title: 'When'},
          ]}
          rows={[
            {cells: [<UserCell name="Ngozi Okonkwo" email="BL-20260728-001" />, <Mono color={T.success}>₦49,352</Mono>, <Mono>MSCU1234567</Mono>, <span style={{fontSize: 12, color: T.ink3}}>2 min ago</span>]},
            {cells: [<UserCell name="Emeka Eze" email="BL-20260728-002" />, <Mono color={T.success}>₦187,400</Mono>, <Mono>MSCU1234567</Mono>, <span style={{fontSize: 12, color: T.ink3}}>14 min ago</span>]},
            {cells: [<UserCell name="Funmilayo Adeyemi" email="BL-20260728-003" />, <Mono color={T.success}>₦97,680</Mono>, <Mono>HLBU9384712</Mono>, <span style={{fontSize: 12, color: T.ink3}}>1 hr ago</span>]},
            {cells: [<UserCell name="Ibrahim Musa" email="BL-20260728-004" />, <Mono color={T.success}>₦42,200</Mono>, <Mono>COSU7194820</Mono>, <span style={{fontSize: 12, color: T.ink3}}>3 hr ago</span>]},
            {cells: [<UserCell name="Bola Adesina" email="BL-20260727-018" />, <Mono color={T.success}>₦24,000</Mono>, <Mono>ONEU2847510</Mono>, <span style={{fontSize: 12, color: T.ink3}}>Yesterday</span>]},
          ]}
        />
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Incoming containers" sub="Next 5 expected arrivals" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <div style={{padding: '0 20px 20px'}}>
          <IncomingRow num="HLBU9384712" vessel="Hapag Hamburg" cust="8" cbm="8.42" eta="Today" etaSub="docking · 16:00 WAT" priority />
          <IncomingRow num="ONEU2847510" vessel="ONE Aquila" cust="9" cbm="6.12" eta="3 days" etaSub="01 Aug · ETA 09:00" />
          <IncomingRow num="MSCU1234567" vessel="MSC Altair" cust="12" cbm="11.84" eta="2 wks" etaSub="14 Aug · ETA 08:00" />
          <IncomingRow num="YMLU6018937" vessel="Yang Ming" cust="13" cbm="9.82" eta="4 wks" etaSub="28 Aug · ETA 14:30" />
          <IncomingRow num="SUDU3819273" vessel="Hamburg Süd Rio" cust="10" cbm="12.04" eta="6 wks" etaSub="12 Sep · ETA 11:00" last />
        </div>
      </Card>
    </div>
  </PageShell>
);

const UrgentAction = ({icon, count, title, sub, cta, danger}) => (
  <div style={{background: '#fff', borderRadius: 10, padding: 16, border: `1px solid ${T.line}`}}>
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 12}}>
      <div style={{
        width: 40, height: 40, borderRadius: 10,
        background: danger ? T.errorSoft : T.warningSoft,
        color: danger ? T.error : T.warning,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <span style={{fontFamily: T.display, fontWeight: 800, fontSize: 17, letterSpacing: '-0.02em'}}>{count}</span>
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{fontSize: 13, fontWeight: 700, color: T.ink, lineHeight: 1.35}}>{title}</div>
        <div style={{fontSize: 12, color: T.ink3, marginTop: 4, lineHeight: 1.45}}>{sub}</div>
        <a style={{
          display: 'inline-flex', alignItems: 'center', gap: 4,
          color: danger ? T.error : T.warningStrong, fontWeight: 700, fontSize: 12,
          marginTop: 10, cursor: 'pointer',
        }}>{cta} <Icon name="arrowright" size={11} stroke={2.5} /></a>
      </div>
    </div>
  </div>
);

const PipelineKanban = () => {
  const cols = [
    {label: 'Arrived NG', side: 'ng', count: 3, items: [
      {num: 'HLBU9384712', cust: 8, cbm: '8.42', when: 'Arrived 09:08', urgent: true},
      {num: 'SUDU3819273', cust: 10, cbm: '12.04', when: 'Yesterday', urgent: true},
      {num: 'YMLU6018937', cust: 13, cbm: '9.82', when: '2 days ago'},
    ]},
    {label: 'Customs', side: 'ng', count: 4, items: [
      {num: 'COSU7194820', cust: 15, cbm: '14.20', when: 'In clearance · 2 days', urgent: true},
      {num: 'MAEU4729183', cust: 11, cbm: '5.80', when: 'In clearance · 1 day'},
      {num: 'EGHU8472019', cust: 4, cbm: '2.10', when: 'In clearance · today'},
    ]},
    {label: 'Cleared', side: 'ng', count: 6, items: [
      {num: 'ONEU2847510', cust: 9, cbm: '6.12', when: 'Cleared today'},
      {num: 'ZIMU8401923', cust: 7, cbm: '4.94', when: 'Cleared today'},
      {num: 'TGBU2940817', cust: 11, cbm: '7.32', when: 'Cleared yesterday'},
    ]},
    {label: 'Ready for pickup', side: 'ng', count: 11, items: [
      {num: 'OOLU7218304', cust: 6, cbm: '3.18', when: 'Ready · 2 days', urgent: true},
      {num: 'MEDU5184910', cust: 9, cbm: '6.04', when: 'Ready · today'},
      {num: 'APMU8019237', cust: 4, cbm: '1.92', when: 'Ready · today'},
    ]},
    {label: 'Completed (today)', side: 'done', count: 7, items: [
      {num: 'EVRG4812039', cust: 8, cbm: '5.40', when: 'Picked up 14:22'},
      {num: 'NYKU7390812', cust: 5, cbm: '2.84', when: 'Picked up 11:08'},
    ]},
  ];
  return (
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12}}>
      {cols.map((col, i) => {
        const accent = col.side === 'done' ? T.success : T.copper;
        return (
          <div key={i} style={{minWidth: 0}}>
            <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 4px 10px', borderBottom: `2px solid ${accent}`, marginBottom: 10}}>
              <div style={{fontSize: 11, fontWeight: 700, color: T.ink, textTransform: 'uppercase', letterSpacing: '0.06em'}}>{col.label}</div>
              <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, color: accent}}>{col.count}</div>
            </div>
            <div style={{display: 'flex', flexDirection: 'column', gap: 8}}>
              {col.items.map((it, j) => (
                <KanbanCard key={j} {...it} side={col.side} />
              ))}
              {col.count > col.items.length && (
                <div style={{textAlign: 'center', padding: '8px 0', fontSize: 11, color: T.ink4, fontWeight: 600}}>
                  + {col.count - col.items.length} more
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const KanbanCard = ({num, cust, cbm, when, urgent, side}) => (
  <div className="sx-kanban" style={{
    background: '#fff', border: `1px solid ${urgent ? T.warning + '55' : T.line}`,
    borderRadius: 10, padding: 10, cursor: 'pointer',
    boxShadow: T.shadowRest, position: 'relative',
  }}>
    {urgent && (
      <span style={{position: 'absolute', top: 8, right: 8, width: 6, height: 6, borderRadius: '50%', background: T.warning, boxShadow: `0 0 0 3px ${T.warning}33`}} />
    )}
    <div style={{fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: T.ink, marginBottom: 4}}>{num}</div>
    <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: T.ink3, marginBottom: 6}}>
      <Icon name="users" size={11} color={T.ink4} stroke={2} />
      <span>{cust} customers</span>
      <span style={{color: T.lineStrong}}>·</span>
      <Mono color={T.ink2}>{cbm} CBM</Mono>
    </div>
    <div style={{fontSize: 10, color: urgent ? T.warningStrong : T.ink4, fontWeight: urgent ? 700 : 500}}>{when}</div>
  </div>
);

const IncomingRow = ({num, vessel, cust, cbm, eta, etaSub, priority, last}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
    borderBottom: last ? 'none' : `1px dashed ${T.line}`,
  }}>
    <div style={{width: 36, height: 36, borderRadius: 8, background: priority ? T.warningSoft : T.muted, color: priority ? T.warning : T.ink3, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
      <Icon name="ship" size={16} stroke={2} />
    </div>
    <div style={{flex: 1, minWidth: 0}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <Mono color={T.ink}>{num}</Mono>
        {priority && <Badge variant="warning" size="sm">Today</Badge>}
      </div>
      <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{vessel} · {cust} customers · {cbm} CBM</div>
    </div>
    <div style={{textAlign: 'right', flexShrink: 0}}>
      <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: priority ? T.warning : T.ink}}>{eta}</div>
      <div style={{fontSize: 10, color: T.ink4, fontFamily: T.mono}}>{etaSub}</div>
    </div>
  </div>
);

// ============================================================
// 6.2 — MANIFEST LIST
// ============================================================
const ManifestList = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('manifests')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Manifests" breadcrumb={['Operations', 'Manifests']} user={ngUser} actions={
      <Button variant="secondary" icon="download">Export</Button>
    } />}
  >
    {/* Stats */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Awaiting verification" value="3" sublabel="oldest 2 days ago" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Verified" value="42" trend="+12%" trendDir="up" sublabel="this month" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="With discrepancies" value="2" sublabel="under investigation" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Resolved" value="48" sublabel="all time" accent={<Icon name="shield" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>50</span></Chip>
          <Chip count={3}>Pending</Chip>
          <Chip count={42}>Verified</Chip>
          <Chip count={2}>Discrepancies</Chip>
          <Chip count={3}>Resolved</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Manifest ID, container number…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="calendar">Last 30 days</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Manifest ID', sortable: true},
          {title: 'Container'},
          {title: 'Customers', align: 'right'},
          {title: 'Cartons', align: 'right'},
          {title: 'Total CBM', align: 'right'},
          {title: 'Status'},
          {title: 'Created', sortable: true},
          {title: '', width: 130},
        ]}
        rows={[
          mfRow({mf: 'MF-20260728-001', container: 'HLBU9384712', cust: 8, cartons: 64, cbm: '8.42', status: 'pending', created: 'Today, 09:12', age: 'arrived 4h ago', urgent: true}),
          mfRow({mf: 'MF-20260727-002', container: 'SUDU3819273', cust: 10, cartons: 78, cbm: '12.04', status: 'pending', created: 'Yesterday', age: '1 day overdue', urgent: true}),
          mfRow({mf: 'MF-20260726-003', container: 'YMLU6018937', cust: 13, cartons: 92, cbm: '9.82', status: 'pending', created: '26 Jul', age: '2 days overdue', urgent: true, danger: true}),
          mfRow({mf: 'MF-20260725-004', container: 'COSU7194820', cust: 15, cartons: 108, cbm: '14.20', status: 'discrepancy', created: '25 Jul', age: '2 cartons missing'}),
          mfRow({mf: 'MF-20260724-005', container: 'MAEU4729183', cust: 11, cartons: 76, cbm: '5.80', status: 'discrepancy', created: '24 Jul', age: 'CBM mismatch'}),
          mfRow({mf: 'MF-20260722-006', container: 'EGHU8472019', cust: 4, cartons: 28, cbm: '2.10', status: 'verified', created: '22 Jul', age: 'verified by Ifeoma'}),
          mfRow({mf: 'MF-20260720-007', container: 'ONEU2847510', cust: 9, cartons: 54, cbm: '6.12', status: 'verified', created: '20 Jul', age: 'verified by Chinedu'}),
          mfRow({mf: 'MF-20260718-008', container: 'ZIMU8401923', cust: 7, cartons: 42, cbm: '4.94', status: 'verified', created: '18 Jul', age: 'verified by Ifeoma'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const mfRow = ({mf, container, cust, cartons, cbm, status, created, age, urgent, danger}) => {
  const badge = {
    pending: <Badge variant="warning">Pending verification</Badge>,
    discrepancy: <Badge variant="accent">Discrepancy</Badge>,
    verified: <Badge variant="success">Verified</Badge>,
  }[status];
  return {
    suspended: danger,
    cells: [
      <Mono color={T.ink}>{mf}</Mono>,
      <Mono>{container}</Mono>,
      <Mono>{cust}</Mono>,
      <Mono>{cartons}</Mono>,
      <Mono>{cbm}</Mono>,
      badge,
      <div>
        <div style={{fontSize: 12, color: T.ink2}}>{created}</div>
        <div style={{fontSize: 11, color: urgent ? T.warning : T.ink4, fontWeight: urgent ? 600 : 400, marginTop: 1}}>{age}</div>
      </div>,
      <div style={{display: 'flex', justifyContent: 'flex-end', gap: 6}}>
        {status === 'pending' && <Button variant="accent" size="sm" icon="check">Verify</Button>}
        {status === 'discrepancy' && <Button variant="secondary" size="sm">Resolve</Button>}
        {status === 'verified' && <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

// ============================================================
// 6.3 — MANIFEST DETAIL
// ============================================================
const ManifestDetail = ({state = 'pending', withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('manifests')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Operations', 'Manifests', 'MF-20260728-001']} user={ngUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: state === 'pending' ? T.warningSoft : state === 'discrepancy' ? T.copperSoft : T.successSoft,
          color: state === 'pending' ? T.warning : state === 'discrepancy' ? T.copper : T.success,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="file" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>MF-20260728-001</h1>
            {state === 'pending' && <Badge variant="warning">Pending verification</Badge>}
            {state === 'discrepancy' && <Badge variant="accent">Discrepancy found</Badge>}
            {state === 'verified' && <Badge variant="success">Verified</Badge>}
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <span>Container <Mono color={T.ink}>HLBU9384712</Mono></span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>8 customers</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>64 cartons</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>8.42 CBM total</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="secondary" icon="upload">Print</Button>
        {state === 'pending' && <Button variant="accent" icon="check">Verify manifest</Button>}
        {state === 'discrepancy' && <Button variant="primary" icon="check">Resolve discrepancy</Button>}
      </div>
    </div>

    {state === 'pending' && (
      <Banner variant="warning" title="Verification required before customer billing can be generated">
        Container <Mono color={T.warningStrong}>HLBU9384712</Mono> arrived at Tin Can Port at 09:08 today. Walk the warehouse against this manifest, then mark as Verified (or log discrepancies if anything's missing or damaged).
      </Banner>
    )}
    {state === 'discrepancy' && (
      <Banner variant="error" title="2 discrepancies logged on 28 Jul at 11:42 by Ifeoma Uche">
        <strong>Ngozi Okonkwo</strong>: 1 carton missing (SHX-00003). <strong>Adaeze Nwosu</strong>: 1 carton water damage (SHX-00018). Both have been notified.
      </Banner>
    )}
    {state === 'verified' && (
      <Banner variant="success" title="Verified by Ifeoma Uche on 28 Jul at 12:30">
        All 64 cartons accounted for. Customer billing has been generated and notifications sent.
      </Banner>
    )}
    <div style={{height: 20}} />

    {/* Summary stats */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Total customers" value="8" sublabel="all packing lists approved" accent={<Icon name="users" size={15} stroke={2.2} />} />
      <StatCard label="Total cartons" value="64" sublabel="of 64 expected" accent={<Icon name="package" size={15} stroke={2.2} />} />
      <StatCard label="Total CBM" value="8.42" sublabel="of container capacity" accent={<Icon name="container" size={15} stroke={2.2} />} />
      <StatCard label="Total weight" value="412 kg" sublabel="across all cartons" accent={<Icon name="package" size={15} stroke={2.2} />} />
    </div>

    {/* Customer table */}
    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Customers on this manifest" sub="Verify each customer's cartons by tag against the warehouse intake" />
      </div>
      <Table
        columns={[
          {title: 'Customer'},
          {title: 'Cartons', align: 'right'},
          {title: 'CBM', align: 'right'},
          {title: 'Weight', align: 'right'},
          {title: 'Carton tags'},
          {title: 'Packing list'},
          {title: '', width: 130},
        ]}
        rows={[
          mfCustRow({name: 'Emeka Eze', cartons: 22, cbm: '2.14', weight: '148 kg', tags: ['SHX-00001', 'SHX-00002', 'SHX-00003', '+19 more'], pl: 'PL-20260728-001'}),
          mfCustRow({name: 'Ngozi Okonkwo', cartons: 18, cbm: '1.84', weight: '122 kg', tags: ['SHX-00023', 'SHX-00024', 'SHX-00025', '+15 more'], pl: 'PL-20260728-002', missing: state === 'discrepancy' ? ['SHX-00024'] : null}),
          mfCustRow({name: 'Funmilayo Adeyemi', cartons: 8, cbm: '0.72', weight: '48 kg', tags: ['SHX-00042', 'SHX-00043', '+6 more'], pl: 'PL-20260727-003'}),
          mfCustRow({name: 'Adaeze Nwosu', cartons: 6, cbm: '0.62', weight: '42 kg', tags: ['SHX-00050', 'SHX-00051', '+4 more'], pl: 'PL-20260727-004', damage: state === 'discrepancy' ? ['SHX-00051'] : null}),
          mfCustRow({name: 'Bola Adesina', cartons: 5, cbm: '0.48', weight: '32 kg', tags: ['SHX-00056', 'SHX-00057', '+3 more'], pl: 'PL-20260727-005'}),
          mfCustRow({name: 'Ibrahim Musa', cartons: 3, cbm: '0.34', weight: '20 kg', tags: ['SHX-00061', 'SHX-00062', 'SHX-00063'], pl: 'PL-20260727-006'}),
          mfCustRow({name: 'Chukwuemeka Nwogu', cartons: 2, cbm: '0.18', weight: '12 kg', tags: ['SHX-00064', 'SHX-00065'], pl: 'PL-20260727-007'}),
        ]}
      />
    </Card>

    {withModal && <VerifyManifestModal />}
  </PageShell>
);

const mfCustRow = ({name, cartons, cbm, weight, tags, pl, missing, damage}) => ({
  cells: [
    <UserCell name={name} email={`${cartons} cartons`} />,
    <Mono>{cartons}</Mono>,
    <Mono>{cbm}</Mono>,
    <Mono>{weight}</Mono>,
    <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
      {tags.map((t, i) => (
        <span key={i} style={{
          fontFamily: T.mono, fontSize: 10, padding: '2px 6px',
          background: t.startsWith('+') ? T.muted : T.greenSoft,
          color: t.startsWith('+') ? T.ink4 : T.greenDeep,
          borderRadius: 4, fontWeight: 600,
        }}>{t}</span>
      ))}
      {missing && missing.map((t, i) => (
        <span key={'m' + i} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700, textDecoration: 'line-through'}}>{t}</span>
      ))}
      {damage && damage.map((t, i) => (
        <span key={'d' + i} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.copperSoft, color: T.copperDeep, borderRadius: 4, fontWeight: 700}}>{t} ⚠</span>
      ))}
    </div>,
    <Mono color={T.ink3}>{pl}</Mono>,
    <div style={{display: 'flex', justifyContent: 'flex-end', gap: 6}}>
      <Button variant="ghost" size="sm">View PL</Button>
      <Button variant="secondary" size="sm" icon="upload">Print</Button>
    </div>,
  ],
});

// ============================================================
// 6.3a — VERIFY MANIFEST MODAL
// ============================================================
const VerifyManifestModal = () => (
  <ModalOverlay>
    <div style={{width: 640, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body, maxHeight: '85vh', display: 'flex', flexDirection: 'column'}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Verify manifest MF-20260728-001</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>Container HLBU9384712 · 8 customers · 64 cartons</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px', overflowY: 'auto', flex: 1}}>
        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 12}}>Verification outcome</label>

        {/* Option 1 — Verified */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          border: `1px solid ${T.line}`, borderRadius: 10, padding: '14px 16px', marginBottom: 10,
          background: '#fff', cursor: 'pointer',
        }}>
          <div style={{width: 18, height: 18, borderRadius: '50%', border: `1.5px solid ${T.lineStrong}`, background: '#fff', marginTop: 2, flexShrink: 0}} />
          <div style={{flex: 1}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
              <Icon name="check" size={14} color={T.success} stroke={2.5} />
              <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink}}>Verified — all items present</span>
            </div>
            <div style={{fontSize: 12, color: T.ink3, marginTop: 4}}>All 64 cartons match the manifest. Billing will be generated for all 8 customers and notifications sent.</div>
          </div>
        </div>

        {/* Option 2 — Discrepancies (selected) */}
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 12,
          border: `2px solid ${T.warning}`, borderRadius: 10, padding: '14px 16px', marginBottom: 14,
          background: T.warningSoft + '88', cursor: 'pointer',
        }}>
          <div style={{width: 18, height: 18, borderRadius: '50%', border: `5px solid ${T.warning}`, background: '#fff', marginTop: 2, flexShrink: 0}} />
          <div style={{flex: 1}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
              <Icon name="warn" size={14} color={T.warning} stroke={2.5} />
              <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.warningStrong}}>Discrepancies found</span>
            </div>
            <div style={{fontSize: 12, color: T.warningStrong, marginTop: 4}}>Log missing or damaged cartons below. Affected customers are auto-notified and shifted to dispute flow.</div>
          </div>
        </div>

        {/* Discrepancies form */}
        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16}}>
          <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12}}>
            <span style={{fontSize: 13, fontWeight: 700, color: T.ink}}>Logged discrepancies (2)</span>
            <Button variant="ghost" size="sm" icon="plus">Add another</Button>
          </div>

          {/* Discrepancy 1 */}
          <div style={{background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8, padding: 12, marginBottom: 10}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8}}>
              <Badge variant="error" size="sm">Missing</Badge>
              <span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Ngozi Okonkwo</span>
              <button style={{marginLeft: 'auto', background: 'transparent', border: 0, color: T.ink4, padding: 4, cursor: 'pointer', display: 'flex'}}>
                <Icon name="x" size={14} />
              </button>
            </div>
            <div style={{fontSize: 11, color: T.ink3, marginBottom: 6}}>Carton tags affected</div>
            <div style={{display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8}}>
              <span style={{fontFamily: T.mono, fontSize: 11, padding: '3px 8px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 4}}>
                SHX-00024 <Icon name="x" size={10} stroke={2.5} />
              </span>
            </div>
            <div style={{fontSize: 12, color: T.ink2, fontStyle: 'italic'}}>"Carton not found in warehouse intake. Checked all pallets twice."</div>
          </div>

          {/* Discrepancy 2 */}
          <div style={{background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8, padding: 12}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8}}>
              <Badge variant="accent" size="sm">Damaged</Badge>
              <span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Adaeze Nwosu</span>
              <button style={{marginLeft: 'auto', background: 'transparent', border: 0, color: T.ink4, padding: 4, cursor: 'pointer', display: 'flex'}}>
                <Icon name="x" size={14} />
              </button>
            </div>
            <div style={{display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8}}>
              <span style={{fontFamily: T.mono, fontSize: 11, padding: '3px 8px', background: T.copperSoft, color: T.copperDeep, borderRadius: 4, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 4}}>
                SHX-00051 <Icon name="x" size={10} stroke={2.5} />
              </span>
            </div>
            <Field multiline value="Water damage to bottom of carton — contents soaked. Photos uploaded below." />
            <div style={{display: 'flex', gap: 8, alignItems: 'center', marginTop: -8}}>
              <div style={{width: 48, height: 48, borderRadius: 6, background: T.line, border: `1px solid ${T.lineStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4}}>
                <Icon name="package" size={20} />
              </div>
              <div style={{width: 48, height: 48, borderRadius: 6, background: T.line, border: `1px solid ${T.lineStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4}}>
                <Icon name="package" size={20} />
              </div>
              <Button variant="ghost" size="sm" icon="upload">Add photo</Button>
            </div>
          </div>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <div style={{fontSize: 12, color: T.ink4}}>Verification is logged in audit history.</div>
        <div style={{display: 'flex', gap: 10}}>
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary" icon="check">Submit verification</Button>
        </div>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 6.4 — UPDATE CONTAINER STATUS
// ============================================================
const UpdateStatusModal = ({state = 'pick'} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('containers')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Operations', 'Containers', 'HLBU9384712']} user={ngUser} />}
  >
    {/* Page hero, dimmed in background */}
    <div style={{filter: 'blur(2px)', opacity: 0.4, pointerEvents: 'none'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24}}>
        <div style={{width: 64, height: 64, borderRadius: 14, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
          <Icon name="container" size={28} stroke={2} />
        </div>
        <div>
          <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0}}>HLBU9384712</h1>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>Hapag Hamburg · Voy 094W</div>
        </div>
      </div>
      <Card padding={20}><div style={{height: 120}} /></Card>
    </div>

    {state === 'pick' && <UpdateStatusPicker />}
    {state === 'confirm' && <UpdateStatusConfirm />}
  </PageShell>
);

const UpdateStatusPicker = () => (
  <ModalOverlay>
    <div style={{width: 580, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Update container status</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>HLBU9384712 · Hapag Hamburg · 8 customers</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        {/* Current status */}
        <div style={{padding: 14, background: T.warningSoft, borderRadius: 8, border: `1px solid ${T.warning}33`, marginBottom: 16}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.warningStrong, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4}}>Current status</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
            <Badge variant="warning">Arrived NG</Badge>
            <span style={{fontSize: 12, color: T.warningStrong}}>since 09:08 today</span>
          </div>
        </div>

        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 8}}>Move to next stage</label>
        <StagePick label="Customs clearance" sub="Submit to customs · triggers customs holding window" current />
        <StagePick label="Cleared" sub="Customs released the container · ready for next phase" disabled note="Can't skip stages" />
        <StagePick label="Ready for pickup" sub="Auto-set when first release note is generated" disabled note="Auto-set later" />
        <StagePick label="Completed" sub="Auto-set when all release notes are picked up" disabled note="Auto-set later" />

        <Field label="Notes" optional multiline value="" placeholder="Anything to flag for the team (e.g. customs officer name, special handling)…" />
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="arrowright">Continue</Button>
      </div>
    </div>
  </ModalOverlay>
);

const StagePick = ({label, sub, current, disabled, note}) => (
  <div style={{
    display: 'flex', alignItems: 'flex-start', gap: 12,
    border: `${current ? 2 : 1}px solid ${current ? T.green : T.line}`,
    borderRadius: 10, padding: '12px 14px', marginBottom: 8,
    background: current ? T.greenTint : disabled ? T.muted : '#fff',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.65 : 1,
  }}>
    <div style={{
      width: 18, height: 18, borderRadius: '50%',
      border: `${current ? 5 : 1.5}px solid ${current ? T.green : T.lineStrong}`,
      background: '#fff', marginTop: 2, flexShrink: 0,
    }} />
    <div style={{flex: 1}}>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: disabled ? T.ink3 : T.ink}}>{label}</span>
        {note && <span style={{fontSize: 11, color: T.ink4, fontStyle: 'italic'}}>{note}</span>}
      </div>
      <div style={{fontSize: 12, color: T.ink3, marginTop: 2, lineHeight: 1.4}}>{sub}</div>
    </div>
  </div>
);

const UpdateStatusConfirm = () => (
  <ModalOverlay>
    <div style={{width: 520, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: 24, textAlign: 'center'}}>
        <div style={{
          width: 72, height: 72, borderRadius: '50%',
          background: T.warningSoft, color: T.warning,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16,
        }}>
          <Icon name="bell" size={28} stroke={2} />
        </div>
        <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 20, margin: '0 0 6px', color: T.ink, letterSpacing: '-0.01em'}}>This will notify 8 customers</h3>
        <p style={{fontSize: 14, color: T.ink3, margin: 0, lineHeight: 1.55, maxWidth: 380, marginLeft: 'auto', marginRight: 'auto'}}>
          Updating to <strong style={{color: T.ink}}>"Customs Clearance"</strong> on HLBU9384712 will send SMS + WhatsApp + Email notifications to all 8 customers on this container.
        </p>
      </div>
      <div style={{margin: '0 24px', background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16}}>
        <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10}}>Notification preview</div>
        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '20px 1fr 36px', gap: 10, alignItems: 'center', marginBottom: 8}}>
          <Icon name="phone" size={14} color={T.info} />
          <div style={{fontSize: 12, color: T.ink2, fontStyle: 'italic'}}>"Your container HLBU9384712 has entered customs clearance at Tin Can Port…"</div>
          <Mono color={T.ink4}>SMS</Mono>
        </div>
        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '20px 1fr 36px', gap: 10, alignItems: 'center', marginBottom: 8}}>
          <Icon name="phone" size={14} color={T.success} />
          <div style={{fontSize: 12, color: T.ink2, fontStyle: 'italic'}}>"Hi Ngozi, your cargo has entered customs clearance…"</div>
          <Mono color={T.ink4}>WA</Mono>
        </div>
        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '20px 1fr 36px', gap: 10, alignItems: 'center'}}>
          <Icon name="mail" size={14} color={T.copper} />
          <div style={{fontSize: 12, color: T.ink2, fontStyle: 'italic'}}>"Container update: customs clearance in progress…"</div>
          <Mono color={T.ink4}>EM</Mono>
        </div>
      </div>
      <div style={{padding: 16, fontSize: 12, color: T.ink4, textAlign: 'center'}}>This action is logged and cannot be undone.</div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="accent" icon="check">Yes, update &amp; notify</Button>
      </div>
    </div>
  </ModalOverlay>
);

Object.assign(window, {
  NgOpsDashboard, ManifestList, ManifestDetail, UpdateStatusModal,
});
