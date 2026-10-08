// ============================================================
// Shipx — Claims & Refunds Screens (Section 8)
// 8.1 Damage Claims List · 8.2 Damage Claim Detail (3 states + modals)
// 8.3 Missing Items · 8.4 Seized Items
// 8.5 Refund Requests List · 8.6 Refund Detail (workflow + modals)
// ============================================================

// ============================================================
// 8.1 — DAMAGE CLAIMS LIST
// ============================================================
const DamageClaimsList = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('damage')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Damage claims" breadcrumb={['Customer service', 'Damage claims']} user={ngUser} actions={
      <Button variant="primary" icon="plus">Log claim</Button>
    } />}
  >
    {/* KPIs */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Open claims" value="6" sublabel="2 awaiting inspection" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Under inspection" value="3" sublabel="delegate visits scheduled" accent={<Icon name="search" size={15} stroke={2.2} />} />
      <StatCard label="Resolved (30d)" value="18" trend="+4" trendDir="up" sublabel="avg 3.2d to resolve" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Total compensated" value="₦842k" sublabel="last 30 days" accent={<Icon name="coin" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>32</span></Chip>
          <Chip count={2}>Filed</Chip>
          <Chip count={3}>Under inspection</Chip>
          <Chip count={1}>Pending resolution</Chip>
          <Chip count={24}>Resolved</Chip>
          <Chip count={2}>Closed</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Claim ID, customer, container…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="calendar">Last 30 days</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Claim ID', sortable: true},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Cartons affected'},
          {title: 'Description'},
          {title: 'Inspection'},
          {title: 'Status'},
          {title: 'Filed', sortable: true},
          {title: '', width: 120},
        ]}
        rows={[
          dcRow({id: 'DC-20260728-001', cust: 'Adaeze Nwosu', container: 'HLBU9384712', cartons: ['SHX-00051'], desc: 'Water damage to bottom of carton', method: 'delegate', status: 'filed', filed: '12 min ago', urgent: true}),
          dcRow({id: 'DC-20260727-002', cust: 'Ngozi Okonkwo', container: 'MSCU1234567', cartons: ['SHX-00024'], desc: 'Carton crushed in transit', method: 'evidence', status: 'filed', filed: '4 hr ago'}),
          dcRow({id: 'DC-20260726-003', cust: 'Emeka Eze', container: 'COSU7194820', cartons: ['SHX-00088', 'SHX-00089'], desc: 'Glass items shattered', method: 'delegate', status: 'inspection', filed: 'Yesterday'}),
          dcRow({id: 'DC-20260724-004', cust: 'Funmilayo Adeyemi', container: 'COSU7194820', cartons: ['SHX-00092'], desc: 'Box tampered with', method: 'delegate', status: 'inspection', filed: '24 Jul'}),
          dcRow({id: 'DC-20260722-005', cust: 'Bola Adesina', container: 'ONEU2847510', cartons: ['SHX-00102'], desc: 'Mold from moisture', method: 'evidence', status: 'pending', filed: '22 Jul'}),
          dcRow({id: 'DC-20260718-006', cust: 'Ibrahim Musa', container: 'MAEU4729183', cartons: ['SHX-00121'], desc: 'Liquid spillage', method: 'delegate', status: 'resolved', filed: '18 Jul'}),
          dcRow({id: 'DC-20260715-007', cust: 'Aisha Lawal', container: 'HLBU9384712', cartons: ['SHX-00154'], desc: 'Cosmetic dent on carton', method: 'evidence', status: 'resolved', filed: '15 Jul'}),
          dcRow({id: 'DC-20260710-008', cust: 'Olufemi Adetunji', container: 'COSU7194820', cartons: ['SHX-00188', 'SHX-00189'], desc: 'Stolen items', method: 'delegate', status: 'closed', filed: '10 Jul'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const dcRow = ({id, cust, container, cartons, desc, method, status, filed, urgent}) => {
  const badge = {
    filed: <Badge variant="error">Filed</Badge>,
    inspection: <Badge variant="warning">Under inspection</Badge>,
    pending: <Badge variant="info">Pending resolution</Badge>,
    resolved: <Badge variant="success">Resolved</Badge>,
    closed: <Badge variant="neutral">Closed</Badge>,
  }[status];
  const methodBadge = method === 'delegate' ?
    <Badge variant="info" size="sm">Delegate visit</Badge> :
    <Badge variant="neutral" size="sm">Customer evidence</Badge>;
  const action = {
    filed: <Button variant="accent" size="sm">Start inspection</Button>,
    inspection: <Button variant="primary" size="sm">Complete</Button>,
    pending: <Button variant="accent" size="sm">Resolve</Button>,
    resolved: <Button variant="ghost" size="sm">View</Button>,
    closed: <Button variant="ghost" size="sm">View</Button>,
  }[status];
  return {
    suspended: urgent && status === 'filed',
    cells: [
      <Mono color={T.ink}>{id}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
        {cartons.map(c => (
          <span key={c} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>{c}</span>
        ))}
      </div>,
      <span style={{fontSize: 12, color: T.ink2, maxWidth: 220, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{desc}</span>,
      methodBadge,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{filed}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>{action}</div>,
    ],
  };
};

// ============================================================
// 8.2 — DAMAGE CLAIM DETAIL
// ============================================================
const DamageClaimDetail = ({state = 'filed', withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('damage')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Customer service', 'Damage claims', 'DC-20260728-001']} user={ngUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: T.errorSoft, color: T.error,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="warn" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>DC-20260728-001</h1>
            {state === 'filed' && <Badge variant="error">Filed · awaiting inspection</Badge>}
            {state === 'inspection' && <Badge variant="warning">Under inspection</Badge>}
            {state === 'resolved' && <Badge variant="success">Resolved · ₦42,000 compensated</Badge>}
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <a style={{color: T.green, fontWeight: 600}}>Adaeze Nwosu</a>
            <span style={{color: T.lineStrong}}>·</span>
            <Mono>HLBU9384712</Mono>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Filed 28 Jul 2026 by customer</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="mail">Message customer</Button>
        {state === 'filed' && <Button variant="accent" icon="search">Start inspection</Button>}
        {state === 'inspection' && <Button variant="accent" icon="check">Complete inspection</Button>}
        {state === 'resolved' && <Button variant="secondary" icon="download">Export resolution</Button>}
      </div>
    </div>

    {state === 'filed' && (
      <Banner variant="error" title="Customer reported damage — needs inspection">
        Filed 28 Jul at 12:14. Customer requested <strong>delegate visit</strong> for inspection. Photos attached below. Start inspection within 24 hours to meet SLA.
      </Banner>
    )}
    {state === 'inspection' && (
      <Banner variant="warning" title="Inspection in progress · Delegate visit · 28 Jul">
        Started by Ifeoma Uche at 14:30. Delegate Adesoji Akinyemi assigned · field notes due by EOD tomorrow.
      </Banner>
    )}
    {state === 'resolved' && (
      <Banner variant="success" title="Resolved on 30 Jul by Ifeoma Uche">
        Resolution: <strong>Refund</strong> of <strong>₦42,000</strong> ($25 USD equivalent). Reason: Water damage confirmed from container leak. Customer notified via SMS + WhatsApp.
      </Banner>
    )}
    <div style={{height: 20}} />

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Left: Claim details + Evidence */}
      <div>
        <Card style={{marginBottom: 16}}>
          <SectionHead title="Claim details" />
          <div style={{height: 8}} />
          <Kvp label="Container" value={<Mono color={T.ink}>HLBU9384712</Mono>} />
          <Kvp label="Affected cartons" value={
            <div style={{display: 'inline-flex', gap: 4}}>
              <span style={{fontFamily: T.mono, fontSize: 11, padding: '2px 8px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>SHX-00051</span>
            </div>
          } />
          <Kvp label="Description" value={<span style={{fontStyle: 'italic'}}>"Water damage to bottom of carton — contents soaked through. Damage discovered upon unpacking."</span>} />
          <Kvp label="Filed by" value="Adaeze Nwosu (customer)" />
          <Kvp label="Filed at" value="28 Jul 2026, 12:14 WAT" />
          <Kvp label="Declared value" value={<Mono>$84.00 USD</Mono>} divider={false} />
        </Card>

        <Card padding={20}>
          <SectionHead title="Evidence" sub="4 photos uploaded by customer" action={
            state === 'inspection' && <Button variant="ghost" size="sm" icon="upload">Add evidence</Button>
          } />
          <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginTop: 12}}>
            {[1,2,3,4].map(i => (
              <div key={i} style={{
                aspectRatio: '1', borderRadius: 8,
                background: `linear-gradient(135deg, ${T.line}, ${T.lineStrong})`,
                border: `1px solid ${T.lineStrong}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4,
                position: 'relative', cursor: 'pointer',
              }}>
                <Icon name="package" size={28} stroke={1.5} />
                <span style={{position: 'absolute', bottom: 4, right: 6, fontSize: 9, color: T.ink4, fontFamily: T.mono, background: 'rgba(255,255,255,0.85)', padding: '2px 5px', borderRadius: 3}}>{i}.jpg</span>
              </div>
            ))}
          </div>
          {state === 'inspection' && (
            <div style={{marginTop: 14, padding: 14, background: T.warningSoft, border: `1px solid ${T.warning}33`, borderRadius: 8}}>
              <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.warningStrong, fontWeight: 600}}>
                <Icon name="upload" size={14} stroke={2.5} />
                Delegate Adesoji Akinyemi: 6 inspection photos pending upload
              </div>
            </div>
          )}
        </Card>
      </div>

      {/* Right: Customer + Inspection */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <Card>
          <SectionHead title="Customer" />
          <div style={{height: 8}} />
          <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px dashed ${T.line}`}}>
            <Avatar size={44} name="Adaeze Nwosu" color={T.copper} />
            <div style={{flex: 1}}>
              <div style={{fontWeight: 700, fontSize: 14, color: T.ink}}>Adaeze Nwosu</div>
              <div style={{fontSize: 12, color: T.ink3, fontFamily: T.mono}}>+234 802 415 0922</div>
            </div>
          </div>
          <Kvp label="Lifetime shipments" value="3" />
          <Kvp label="Prior damage claims" value="0" />
          <Kvp label="WhatsApp consent" value={<Badge variant="success" size="sm">Yes</Badge>} divider={false} />
        </Card>

        {state !== 'filed' && (
          <Card>
            <SectionHead title="Inspection" />
            <div style={{height: 8}} />
            <Kvp label="Method" value={<Badge variant="info" size="sm">Delegate visit</Badge>} />
            <Kvp label="Delegate" value="Adesoji Akinyemi" />
            <Kvp label="Started" value="28 Jul, 14:30 by Ifeoma" />
            {state === 'resolved' ? (
              <Kvp label="Completed" value="30 Jul, 11:14 by Ifeoma" divider={false} />
            ) : (
              <Kvp label="Field notes due" value={<span style={{color: T.warning, fontWeight: 600}}>EOD tomorrow</span>} divider={false} />
            )}
          </Card>
        )}

        {state === 'resolved' && (
          <Card style={{background: T.successSoft + '66', borderColor: T.success + '33'}}>
            <SectionHead title="Resolution" />
            <div style={{height: 8}} />
            <Kvp label="Type" value={<Badge variant="success" size="sm">Refund</Badge>} />
            <Kvp label="Amount" value={<Mono color={T.successStrong} style={{fontSize: 16, fontWeight: 700}}>₦42,000</Mono>} />
            <Kvp label="USD equivalent" value={<Mono>$25.00</Mono>} />
            <Kvp label="Reason" value={<span style={{fontStyle: 'italic'}}>"Water damage confirmed — container leak from corner seal."</span>} divider={false} />
            <div style={{paddingTop: 12, marginTop: 8, borderTop: `1px solid ${T.line}`}}>
              <Button variant="secondary" size="sm" full icon="arrowright">View refund record · RF-20260730-014</Button>
            </div>
          </Card>
        )}
      </div>
    </div>

    {/* Activity timeline */}
    <Card>
      <SectionHead title="Activity timeline" sub="All status changes and actions on this claim" />
      <div style={{height: 16}} />
      {state === 'resolved' && <DispEvent icon="check" color={T.success} title="Resolved with refund · ₦42,000" sub="By Ifeoma Uche · refund record RF-20260730-014 created" when="30 Jul, 11:14" />}
      {(state === 'resolved' || state === 'inspection') && <DispEvent icon="search" color={T.warning} title="Inspection started" sub={`Delegate ${state === 'resolved' ? 'completed visit on 29 Jul' : 'Adesoji Akinyemi assigned'}`} when={state === 'resolved' ? '28 Jul, 14:30' : '28 Jul, 14:30'} current={state === 'inspection'} />}
      <DispEvent icon="warn" color={T.error} title="Claim filed" sub="By Adaeze Nwosu · 4 photos attached · delegate visit requested" when="28 Jul, 12:14" current={state === 'filed'} last />
    </Card>

    {withModal === 'inspection' && <StartInspectionModal />}
    {withModal === 'resolve' && <ResolveClaimModal />}
  </PageShell>
);

const StartInspectionModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Start inspection</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>DC-20260728-001 · Adaeze Nwosu</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 12}}>Inspection method</label>

        <StagePick label="Delegate visit (recommended)" sub="Send field staff to inspect the cartons in person. Allows photo + condition documentation." current />
        <StagePick label="Customer-supplied evidence only" sub="Use customer-uploaded photos. Faster but limited verification — best for cosmetic damage." />

        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginTop: 8}}>
          <Field label="Assign delegate" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{flex: 1, fontSize: 14, color: T.ink}}>Adesoji Akinyemi</span>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
          <Field label="Field notes due" required icon="calendar" value="29 Jul 2026, 18:00" />
        </div>

        <Field label="Internal notes" optional multiline value="" placeholder="Anything to flag for the delegate or your team…" />
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="search">Start inspection</Button>
      </div>
    </div>
  </ModalOverlay>
);

const ResolveClaimModal = () => (
  <ModalOverlay>
    <div style={{width: 600, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body, maxHeight: '85vh', display: 'flex', flexDirection: 'column'}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Resolve claim</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>DC-20260728-001 · Adaeze Nwosu · 1 carton</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px', overflowY: 'auto', flex: 1}}>
        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 12}}>Resolution type</label>

        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginBottom: 16}}>
          <ResolutionPick icon="coin" title="Refund" sub="Cash refund to customer" current />
          <ResolutionPick icon="card" title="Discount" sub="Reduce next billing" />
          <ResolutionPick icon="package" title="Compensation" sub="Goods replacement" />
          <ResolutionPick icon="x" title="No action" sub="Claim not actionable" />
        </div>

        <div style={{padding: 16, background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 10, marginBottom: 16}}>
          <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
            <Field label="Amount USD" required prefix="$" value="25.00" helper="Original declared value: $84.00" />
            <Field label="Amount NGN (auto)" disabled prefix="₦" value="41,250" helper="$25 × ₦1,650 current FX" />
          </div>
        </div>

        <Field label="Reason" required multiline value="Water damage confirmed from container leak. Customer's photos + delegate report match. Compensating 30% of declared value." helper="Visible to customer and in audit log." />
        <Field label="Internal notes" optional multiline value="" placeholder="Notes for your team only" />

        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8, padding: 14}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8}}>
            <Check checked />
            <span style={{fontSize: 13, color: T.ink, fontWeight: 600}}>Generate refund record automatically</span>
          </div>
          <div style={{fontSize: 12, color: T.ink3, paddingLeft: 26}}>Creates a refund of ₦41,250 in <Mono color={T.green}>Pending Accounts Review</Mono> status.</div>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="accent" icon="check">Confirm resolution</Button>
      </div>
    </div>
  </ModalOverlay>
);

const ResolutionPick = ({icon, title, sub, current}) => (
  <div style={{
    display: 'flex', alignItems: 'flex-start', gap: 10,
    border: `${current ? 2 : 1}px solid ${current ? T.green : T.line}`,
    borderRadius: 10, padding: 12,
    background: current ? T.greenTint : '#fff', cursor: 'pointer',
  }}>
    <div style={{
      width: 18, height: 18, borderRadius: '50%',
      border: `${current ? 5 : 1.5}px solid ${current ? T.green : T.lineStrong}`,
      background: '#fff', marginTop: 1, flexShrink: 0,
    }} />
    <div style={{flex: 1}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
        <Icon name={icon} size={13} color={current ? T.green : T.ink3} />
        <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 13, color: T.ink}}>{title}</span>
      </div>
      <div style={{fontSize: 11, color: T.ink3, marginTop: 2}}>{sub}</div>
    </div>
  </div>
);

// ============================================================
// 8.3 — MISSING ITEMS
// ============================================================
const MissingItems = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('missing')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Missing items" breadcrumb={['Customer service', 'Missing items']} user={ngUser} actions={
      <Button variant="primary" icon="plus">Log missing item</Button>
    } />}
  >
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Reported" value="3" sublabel="awaiting investigation" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Investigating" value="4" sublabel="across 3 containers" accent={<Icon name="search" size={15} stroke={2.2} />} />
      <StatCard label="Found & shipping" value="2" sublabel="next vessel" accent={<Icon name="ship" size={15} stroke={2.2} />} />
      <StatCard label="Confirmed lost" value="1" sublabel="refund issued" accent={<Icon name="x" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>18</span></Chip>
          <Chip count={3}>Reported</Chip>
          <Chip count={4}>Investigating</Chip>
          <Chip count={2}>Found & shipping</Chip>
          <Chip count={1}>Confirmed lost</Chip>
          <Chip count={8}>Resolved</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Item ID, customer, container…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Item ID', sortable: true},
          {title: 'Customer'},
          {title: 'Container · manifest'},
          {title: 'Missing cartons'},
          {title: 'Description'},
          {title: 'Status'},
          {title: 'Reported', sortable: true},
          {title: '', width: 110},
        ]}
        rows={[
          miRow({id: 'MI-20260728-001', cust: 'Ngozi Okonkwo', container: 'HLBU9384712', mf: 'MF-20260728-001', cartons: ['SHX-00024'], desc: 'Not found in warehouse intake', status: 'reported', when: '4 hr ago'}),
          miRow({id: 'MI-20260728-002', cust: 'Emeka Eze', container: 'HLBU9384712', mf: 'MF-20260728-001', cartons: ['SHX-00081'], desc: 'Missing from manifest verification', status: 'reported', when: '6 hr ago'}),
          miRow({id: 'MI-20260727-003', cust: 'Adaeze Nwosu', container: 'COSU7194820', mf: 'MF-20260725-004', cartons: ['SHX-00094', 'SHX-00095'], desc: 'Two cartons unaccounted', status: 'investigating', when: 'Yesterday'}),
          miRow({id: 'MI-20260725-004', cust: 'Bola Adesina', container: 'COSU7194820', mf: 'MF-20260725-004', cartons: ['SHX-00102'], desc: 'Possibly mis-routed', status: 'investigating', when: '25 Jul'}),
          miRow({id: 'MI-20260722-005', cust: 'Funmilayo Adeyemi', container: 'MAEU4729183', mf: 'MF-20260722-006', cartons: ['SHX-00128'], desc: 'Found in adjacent container — shipping next vessel', status: 'found', when: '22 Jul'}),
          miRow({id: 'MI-20260718-006', cust: 'Ibrahim Musa', container: 'MAEU4729183', mf: 'MF-20260722-006', cartons: ['SHX-00142'], desc: 'Found in China warehouse — re-shipping', status: 'found', when: '18 Jul'}),
          miRow({id: 'MI-20260712-007', cust: 'Aisha Lawal', container: 'ONEU2847510', mf: 'MF-20260712-009', cartons: ['SHX-00164'], desc: 'No trace — likely lost in transit', status: 'lost', when: '12 Jul', urgent: true}),
        ]}
      />
      <TablePagination />
    </Card>

    {withModal && <LogMissingItemModal />}
  </PageShell>
);

const miRow = ({id, cust, container, mf, cartons, desc, status, when, urgent}) => {
  const badge = {
    reported: <Badge variant="warning">Reported</Badge>,
    investigating: <Badge variant="info">Investigating</Badge>,
    found: <Badge variant="success">Found & shipping</Badge>,
    lost: <Badge variant="error">Confirmed lost</Badge>,
    resolved: <Badge variant="success">Resolved</Badge>,
  }[status];
  return {
    suspended: urgent,
    cells: [
      <Mono color={T.ink}>{id}</Mono>,
      <UserCell name={cust} email={''} />,
      <div>
        <Mono color={T.ink}>{container}</Mono>
        <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono, marginTop: 1}}>{mf}</div>
      </div>,
      <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
        {cartons.map(c => (
          <span key={c} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700, textDecoration: 'line-through'}}>{c}</span>
        ))}
      </div>,
      <span style={{fontSize: 12, color: T.ink3, maxWidth: 220, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{desc}</span>,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{when}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        {status === 'reported' && <Button variant="primary" size="sm">Investigate</Button>}
        {status === 'investigating' && <Button variant="primary" size="sm">Update</Button>}
        {(status === 'found' || status === 'lost') && <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

const LogMissingItemModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Log missing item</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>Cartons unaccounted for at intake</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Field label="Manifest" required>
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, cursor: 'pointer'}}>
            <Icon name="file" size={14} color={T.copper} />
            <Mono color={T.ink}>MF-20260728-001</Mono>
            <span style={{flex: 1, fontSize: 13, color: T.ink3}}>· HLBU9384712 · 64 cartons</span>
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <Field label="Customer" required>
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, cursor: 'pointer'}}>
            <Avatar size={22} name="Ngozi Okonkwo" color={T.copper} />
            <span style={{fontSize: 14, color: T.ink}}>Ngozi Okonkwo</span>
            <span style={{fontFamily: T.mono, fontSize: 11, color: T.ink4}}>· 18 cartons on manifest</span>
            <span style={{flex: 1}} />
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>

        <Field label="Missing carton tags" required helper="Type to add — comma or Enter to confirm each tag.">
          <div style={{
            minHeight: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8,
            padding: 6, display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap',
          }}>
            <span style={{fontFamily: T.mono, fontSize: 11, padding: '4px 8px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 4}}>
              SHX-00024 <Icon name="x" size={11} stroke={2.5} />
            </span>
            <input style={{border: 0, outline: 0, flex: 1, minWidth: 80, padding: '4px 6px', fontFamily: T.mono, fontSize: 12, color: T.ink}} placeholder="Add tag…" />
          </div>
        </Field>

        <Field label="Description" required multiline value="Not found in warehouse intake. Checked all pallets and manifest reconciliation pass — carton SHX-00024 is missing." helper="Be specific about where and when you searched." />
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="plus">Log missing item</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 8.4 — SEIZED ITEMS
// ============================================================
const SeizedItems = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('seized')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Seized items (customs)" breadcrumb={['Customer service', 'Seized items']} user={ngUser} actions={
      <Button variant="primary" icon="plus">Log seizure</Button>
    } />}
  >
    <Banner variant="warning" title="Active seizures require immediate response">
      Customs holds cargo for tax disputes, prohibited goods, or documentation issues. Recovery often takes 5-15 business days. Keep customers informed via the linked claim.
    </Banner>
    <div style={{height: 20}} />

    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Active seizures" value="2" sublabel="awaiting customs response" accent={<Icon name="shield" size={15} stroke={2.2} />} />
      <StatCard label="Recovery in progress" value="3" sublabel="paperwork submitted" accent={<Icon name="refresh" size={15} stroke={2.2} />} />
      <StatCard label="Recovered (30d)" value="6" trend="+2" trendDir="up" sublabel="released back to customer" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Permanently lost" value="1" sublabel="₦248k refunded" accent={<Icon name="x" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>12</span></Chip>
          <Chip count={2}>Seized</Chip>
          <Chip count={3}>Recovery in progress</Chip>
          <Chip count={6}>Recovered</Chip>
          <Chip count={1}>Permanently lost</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Customer, container, reason…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Item ID'},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Cartons'},
          {title: 'Seizure reason'},
          {title: 'Recovery'},
          {title: 'Reported', sortable: true},
          {title: '', width: 110},
        ]}
        rows={[
          seRow({id: 'SE-20260728-001', cust: 'Olufemi Adetunji', container: 'COSU7194820', cartons: ['SHX-00076'], reason: 'Undeclared cosmetics — NAFDAC review', status: 'seized', when: 'Today', urgent: true}),
          seRow({id: 'SE-20260725-002', cust: 'Emeka Eze', container: 'COSU7194820', cartons: ['SHX-00088', 'SHX-00089'], reason: 'Pending duty payment — over-declared value', status: 'seized', when: '25 Jul', urgent: true}),
          seRow({id: 'SE-20260720-003', cust: 'Aisha Lawal', container: 'MAEU4729183', cartons: ['SHX-00118'], reason: 'Documentation incomplete', status: 'recovery', when: '20 Jul'}),
          seRow({id: 'SE-20260715-004', cust: 'Ibrahim Musa', container: 'MAEU4729183', cartons: ['SHX-00134'], reason: 'Random inspection', status: 'recovery', when: '15 Jul'}),
          seRow({id: 'SE-20260710-005', cust: 'Yusuf Garba', container: 'ONEU2847510', cartons: ['SHX-00154'], reason: 'Random inspection', status: 'recovery', when: '10 Jul'}),
          seRow({id: 'SE-20260622-006', cust: 'Bola Adesina', container: 'ZIMU8401923', cartons: ['SHX-00172'], reason: 'Mis-declared item — pharmaceutical', status: 'recovered', when: '22 Jun'}),
          seRow({id: 'SE-20260605-007', cust: 'Chukwuemeka Nwogu', container: 'YMLU6018937', cartons: ['SHX-00198'], reason: 'Contraband — permanent confiscation', status: 'lost', when: '05 Jun'}),
        ]}
      />
    </Card>
  </PageShell>
);

const seRow = ({id, cust, container, cartons, reason, status, when, urgent}) => {
  const badge = {
    seized: <Badge variant="error">Seized · awaiting response</Badge>,
    recovery: <Badge variant="warning">Recovery in progress</Badge>,
    recovered: <Badge variant="success">Recovered</Badge>,
    lost: <Badge variant="neutral">Permanently lost</Badge>,
  }[status];
  return {
    suspended: urgent,
    cells: [
      <Mono color={T.ink}>{id}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
        {cartons.map(c => (
          <span key={c} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>{c}</span>
        ))}
      </div>,
      <span style={{fontSize: 12, color: T.ink2, maxWidth: 220, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{reason}</span>,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{when}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        {(status === 'seized' || status === 'recovery') && <Button variant="primary" size="sm">Update</Button>}
        {(status === 'recovered' || status === 'lost') && <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

// ============================================================
// 8.5 — REFUND REQUESTS LIST
// ============================================================
const RefundRequestsList = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('refunds')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Refund requests" breadcrumb={['Customer service', 'Refunds']} user={ngUser} actions={
      <Button variant="secondary" icon="download">Export</Button>
    } />}
  >
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Pending review" value="4" sublabel="awaiting accounts" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Pending approval" value="3" sublabel="awaiting head of finance" accent={<Icon name="clock" size={15} stroke={2.2} />} />
      <StatCard label="Approved (this month)" value="₦842k" trend="+12%" trendDir="up" sublabel="18 refunds" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Avg time to approval" value="2.1" suffix="days" trend="−0.4d" trendDir="down" sublabel="vs last month" accent={<Icon name="refresh" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>54</span></Chip>
          <Chip count={4}>Pending review</Chip>
          <Chip count={2}>Accounts reviewed</Chip>
          <Chip count={3}>Pending approval</Chip>
          <Chip count={32}>Approved</Chip>
          <Chip count={5}>Rejected</Chip>
          <Chip count={8}>Applied as credit</Chip>
        </div>
        <div style={{flex: 1, minWidth: 200}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Ref ID, customer, billing…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" trailing="chevdown">Type: All</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Ref ID', sortable: true},
          {title: 'Customer'},
          {title: 'Type'},
          {title: 'Source'},
          {title: 'Requested', align: 'right'},
          {title: 'Approved', align: 'right'},
          {title: 'Choice'},
          {title: 'Status'},
          {title: 'Filed', sortable: true},
          {title: '', width: 110},
        ]}
        rows={[
          rfRow({id: 'RF-20260730-014', cust: 'Adaeze Nwosu', type: 'damage', src: 'DC-20260728-001', req: 42000, approved: null, choice: 'refund', status: 'pending_review', filed: 'Today'}),
          rfRow({id: 'RF-20260729-013', cust: 'Ngozi Okonkwo', type: 'cbm', src: 'CBM-20260728-001', req: 5648, approved: null, choice: 'credit', status: 'pending_review', filed: 'Yesterday', selected: true}),
          rfRow({id: 'RF-20260728-012', cust: 'Aisha Lawal', type: 'overpayment', src: 'BL-20260615-042', req: 6440, approved: 6440, choice: 'credit', status: 'reviewed', filed: '28 Jul'}),
          rfRow({id: 'RF-20260727-011', cust: 'Emeka Eze', type: 'damage', src: 'DC-20260722-003', req: 28000, approved: 28000, choice: 'refund', status: 'pending_approval', filed: '27 Jul'}),
          rfRow({id: 'RF-20260725-010', cust: 'Funmilayo Adeyemi', type: 'cbm', src: 'CBM-20260722-006', req: 3168, approved: 3168, choice: 'credit', status: 'pending_approval', filed: '25 Jul'}),
          rfRow({id: 'RF-20260722-009', cust: 'Bola Adesina', type: 'damage', src: 'DC-20260718-006', req: 18500, approved: 15000, choice: 'refund', status: 'approved', filed: '22 Jul'}),
          rfRow({id: 'RF-20260718-008', cust: 'Ibrahim Musa', type: 'overpayment', src: 'BL-20260612-051', req: 8200, approved: 0, choice: 'refund', status: 'rejected', filed: '18 Jul'}),
          rfRow({id: 'RF-20260712-007', cust: 'Yusuf Garba', type: 'damage', src: 'DC-20260710-008', req: 22000, approved: 22000, choice: 'credit', status: 'applied', filed: '12 Jul'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const rfRow = ({id, cust, type, src, req, approved, choice, status, filed, selected}) => {
  const typeBadge = {
    overpayment: <Badge variant="info" size="sm">Overpayment</Badge>,
    cbm: <Badge variant="purple" size="sm">CBM correction</Badge>,
    damage: <Badge variant="error" size="sm">Damage / loss</Badge>,
  }[type];
  const statusBadge = {
    pending_review: <Badge variant="warning">Pending review</Badge>,
    reviewed: <Badge variant="info">Accounts reviewed</Badge>,
    pending_approval: <Badge variant="info">Pending approval</Badge>,
    approved: <Badge variant="success">Approved</Badge>,
    applied: <Badge variant="purple">Applied as credit</Badge>,
    rejected: <Badge variant="error">Rejected</Badge>,
  }[status];
  const action = {
    pending_review: <Button variant="primary" size="sm">Review</Button>,
    reviewed: <Button variant="accent" size="sm">Approve</Button>,
    pending_approval: <Button variant="ghost" size="sm">Pending</Button>,
    approved: <Button variant="ghost" size="sm">View</Button>,
    applied: <Button variant="ghost" size="sm">View</Button>,
    rejected: <Button variant="ghost" size="sm">View</Button>,
  }[status];
  return {
    selected,
    cells: [
      <Mono color={T.ink}>{id}</Mono>,
      <UserCell name={cust} email={''} />,
      typeBadge,
      <Mono color={T.ink3}>{src}</Mono>,
      <Mono>₦{req.toLocaleString()}</Mono>,
      approved !== null ?
        <Mono color={approved === 0 ? T.error : approved < req ? T.warning : T.success}>{approved === 0 ? 'Rejected' : `₦${approved.toLocaleString()}`}</Mono> :
        <Mono color={T.ink4}>—</Mono>,
      <div style={{display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.ink2}}>
        <Icon name={choice === 'refund' ? 'coin' : 'card'} size={12} color={choice === 'refund' ? T.success : T.copper} />
        {choice === 'refund' ? 'Bank refund' : 'Apply as credit'}
      </div>,
      statusBadge,
      <span style={{fontSize: 12, color: T.ink3}}>{filed}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>{action}</div>,
    ],
  };
};

// ============================================================
// 8.6 — REFUND DETAIL
// ============================================================
const RefundDetail = ({state = 'pending_review', withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('refunds')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Customer service', 'Refunds', 'RF-20260730-014']} user={ngUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: T.copperSoft, color: T.copperDeep,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="refresh" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>RF-20260730-014</h1>
            {state === 'pending_review' && <Badge variant="warning">Pending accounts review</Badge>}
            {state === 'reviewed' && <Badge variant="info">Accounts reviewed · awaiting approval</Badge>}
            {state === 'approved' && <Badge variant="success">Approved · ₦42,000</Badge>}
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <a style={{color: T.green, fontWeight: 600}}>Adaeze Nwosu</a>
            <span style={{color: T.lineStrong}}>·</span>
            <Badge variant="error" size="sm">Damage / loss</Badge>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Filed 30 Jul 2026 by Ifeoma Uche</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        {state === 'pending_review' && <Button variant="primary" icon="check">Perform accounts review</Button>}
        {state === 'reviewed' && <><Button variant="danger-outline" icon="x">Reject</Button><Button variant="success" icon="check">Approve refund</Button></>}
        {state === 'approved' && <Button variant="secondary" icon="download">Export receipt</Button>}
      </div>
    </div>

    {/* Workflow stepper */}
    <Card style={{marginBottom: 20}}>
      <SectionHead title="Approval workflow" sub="4 stages from filed to approved" />
      <div style={{height: 20}} />
      <RefundStepper state={state} />
    </Card>

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Refund info */}
      <Card>
        <SectionHead title="Refund details" />
        <div style={{height: 8}} />
        <Kvp label="Type" value={<Badge variant="error" size="sm">Damage / loss</Badge>} />
        <Kvp label="Source claim" value={<><Mono color={T.green}>DC-20260728-001</Mono> <span style={{fontSize: 11, color: T.ink4}}>(Damage resolved with refund)</span></>} />
        <Kvp label="Customer" value="Adaeze Nwosu · +234 802 415 0922" />
        <Kvp label="Amount requested" value={<Mono color={T.ink} style={{fontSize: 16, fontWeight: 700}}>₦42,000</Mono>} />
        {state === 'reviewed' || state === 'approved' ? (
          <Kvp label="Amount approved" value={<Mono color={T.success} style={{fontSize: 16, fontWeight: 700}}>₦42,000</Mono>} />
        ) : null}
        <Kvp label="Customer choice" value={<div style={{display: 'inline-flex', alignItems: 'center', gap: 6}}><Icon name="coin" size={13} color={T.success} /><span>Bank refund</span></div>} />
        {(state === 'reviewed' || state === 'approved') && (
          <Kvp label="Bank account" value={<Mono>GTBank · ***1234</Mono>} />
        )}
        <Kvp label="Filed by" value="Ifeoma Uche · auto-generated from claim resolution" divider={false} />
      </Card>

      {/* Accounts review section */}
      <Card>
        {state === 'pending_review' && (
          <>
            <SectionHead title="Accounts review needed" sub="Confirm the customer has no outstanding debts before approval" />
            <div style={{height: 14}} />
            <Banner variant="info" title="Debt check protocol">
              Before approving any refund, verify the customer has no overdue billings or active disputes that should offset this refund.
            </Banner>
            <div style={{height: 14}} />
            <Button variant="primary" icon="check" full>Perform accounts review</Button>
          </>
        )}
        {(state === 'reviewed' || state === 'approved') && (
          <>
            <SectionHead title="Accounts review" />
            <div style={{height: 8}} />
            <Kvp label="Reviewed by" value="Chinedu Obi · Accounts" />
            <Kvp label="Reviewed at" value="30 Jul 2026, 14:08" />
            <Kvp label="Debt check" value={<Badge variant="success" size="sm">Passed · no outstanding debts</Badge>} />
            <Kvp label="Notes" value={<span style={{fontSize: 13, fontStyle: 'italic'}}>"Customer has 3 prior shipments, all paid in full. No active disputes. Refund cleared for approval."</span>} divider={false} />
          </>
        )}
        {state === 'approved' && (
          <>
            <div style={{paddingTop: 14, marginTop: 14, borderTop: `1px solid ${T.line}`}}>
              <SectionHead title="Approval" />
              <div style={{height: 8}} />
              <Kvp label="Approved by" value="Olumide Bello · Head of Finance" />
              <Kvp label="Approval level" value={<Badge variant="success" size="sm">head_of_finance</Badge>} />
              <Kvp label="Approved at" value="30 Jul 2026, 16:42" divider={false} />
            </div>
          </>
        )}
      </Card>
    </div>

    {/* Activity timeline */}
    <Card>
      <SectionHead title="Activity timeline" />
      <div style={{height: 16}} />
      {state === 'approved' && <DispEvent icon="coin" color={T.success} title="Bank transfer initiated · ₦42,000 → GTBank ***1234" sub="By Olumide Bello · 2-3 business days" when="30 Jul, 16:42" />}
      {state === 'approved' && <DispEvent icon="check" color={T.success} title="Refund approved · ₦42,000" sub="By Olumide Bello · approval_level: head_of_finance" when="30 Jul, 16:42" />}
      {(state === 'reviewed' || state === 'approved') && <DispEvent icon="search" color={T.info} title="Accounts review passed" sub="By Chinedu Obi · no outstanding debts" when="30 Jul, 14:08" />}
      <DispEvent icon="plus" color={T.copper} title="Refund record created" sub="Auto-generated from DC-20260728-001 resolution" when="30 Jul, 11:14" current={state === 'pending_review'} last />
    </Card>

    {withModal === 'review' && <AccountsReviewModal />}
    {withModal === 'approve' && <ApproveRefundModal />}
  </PageShell>
);

const RefundStepper = ({state}) => {
  const order = ['filed', 'pending_review', 'reviewed', 'approved', 'paid'];
  const stateIdx = state === 'pending_review' ? 1 : state === 'reviewed' ? 2 : state === 'approved' ? 4 : 0;
  const steps = [
    {label: 'Filed', sub: 'Refund created'},
    {label: 'Accounts review', sub: 'Debt check'},
    {label: 'Reviewed', sub: 'Ready for approval'},
    {label: 'Approved', sub: 'By head of finance'},
    {label: 'Paid', sub: 'Bank transfer · 2–3d'},
  ];
  return (
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 4, position: 'relative'}}>
      {steps.map((s, i) => {
        const done = i < stateIdx;
        const isCurrent = i === stateIdx;
        const color = done ? T.success : isCurrent ? T.copper : T.lineStrong;
        return (
          <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative'}}>
            {i > 0 && <div style={{position: 'absolute', top: 14, right: '50%', width: '100%', height: 2, background: done ? T.success : T.line, zIndex: 0}} />}
            <div style={{
              width: 30, height: 30, borderRadius: '50%',
              background: done ? T.success : isCurrent ? '#fff' : T.muted,
              border: `${isCurrent ? 3 : 2}px solid ${color}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', position: 'relative', zIndex: 1,
              boxShadow: isCurrent ? `0 0 0 6px ${color}22` : 'none',
            }}>
              {done ? <Icon name="check" size={14} color="#fff" stroke={3} /> :
               isCurrent ? <div style={{width: 8, height: 8, borderRadius: '50%', background: color}} /> : null}
            </div>
            <div style={{marginTop: 8, textAlign: 'center'}}>
              <div style={{fontSize: 11, fontWeight: 700, color: done || isCurrent ? T.ink : T.ink4, letterSpacing: '0.02em'}}>{s.label}</div>
              <div style={{fontSize: 10, color: T.ink4, marginTop: 1}}>{s.sub}</div>
              {isCurrent && (
                <div style={{
                  marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 4,
                  background: color, color: '#fff', padding: '2px 8px', borderRadius: 9999,
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                }}>Current</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const AccountsReviewModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Perform accounts review</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>RF-20260730-014 · Adaeze Nwosu · ₦42,000</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        {/* Auto-check results */}
        <div style={{padding: 14, background: T.successSoft, border: `1px solid ${T.success}33`, borderRadius: 10, marginBottom: 16}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.successStrong, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Automated debt check</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, marginBottom: 4}}>
            <Icon name="check" size={14} color={T.success} stroke={2.5} />
            <span style={{color: T.ink}}>No outstanding billings</span>
          </div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, marginBottom: 4}}>
            <Icon name="check" size={14} color={T.success} stroke={2.5} />
            <span style={{color: T.ink}}>No active CBM disputes</span>
          </div>
          <div style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 13}}>
            <Icon name="check" size={14} color={T.success} stroke={2.5} />
            <span style={{color: T.ink}}>No active carryovers</span>
          </div>
        </div>

        <Field label="Debt check passed?" required>
          <div style={{display: 'flex', gap: 8}}>
            <button style={{flex: 1, padding: '14px', borderRadius: 8, border: `2px solid ${T.success}`, background: T.successSoft + '88', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, fontFamily: T.body, fontSize: 14, fontWeight: 700, color: T.successStrong, cursor: 'pointer'}}>
              <Icon name="check" size={14} stroke={2.5} /> Yes — proceed
            </button>
            <button style={{flex: 1, padding: '14px', borderRadius: 8, border: `1px solid ${T.line}`, background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, fontFamily: T.body, fontSize: 14, fontWeight: 600, color: T.ink3, cursor: 'pointer'}}>
              <Icon name="x" size={14} /> No — hold
            </button>
          </div>
        </Field>

        <Field label="Notes" required multiline value="Customer has 3 prior shipments, all paid in full. No active disputes or carryovers. Refund cleared for head-of-finance approval." />
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="check">Submit review</Button>
      </div>
    </div>
  </ModalOverlay>
);

const ApproveRefundModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Approve refund</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>RF-20260730-014 · Adaeze Nwosu</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <div style={{padding: 16, background: T.successSoft + '88', border: `1px solid ${T.success}33`, borderRadius: 10, marginBottom: 20, textAlign: 'center'}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.successStrong, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>Bank refund to</div>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, color: T.ink}}>Adaeze Nwosu · GTBank ***1234</div>
        </div>

        <Field label="Amount to approve (NGN)" required prefix="₦" value="42,000" focused helper="Pre-filled with requested amount. Editable — staff may approve a lower amount with justification." />
        <Field label="Approval level" required>
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, cursor: 'pointer'}}>
            <span style={{fontSize: 14, color: T.ink, fontWeight: 500}}>Head of Finance</span>
            <span style={{fontSize: 11, color: T.ink4}}>· up to ₦500k single approval</span>
            <span style={{flex: 1}} />
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <Field label="Approval notes" optional multiline value="" placeholder="Additional context or conditions (visible in audit log)" />

        <Banner variant="info" title="What happens next">
          Bank transfer of ₦42,000 is initiated to <strong>GTBank ***1234</strong>. Customer is notified via SMS + WhatsApp. Funds typically arrive in 2–3 business days.
        </Banner>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="success" icon="check">Confirm approval</Button>
      </div>
    </div>
  </ModalOverlay>
);

Object.assign(window, {
  DamageClaimsList, DamageClaimDetail, MissingItems, SeizedItems,
  RefundRequestsList, RefundDetail,
});
