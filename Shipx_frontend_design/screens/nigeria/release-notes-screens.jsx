// ============================================================
// Shipx — Payment & Release Notes Screens (Section 9)
// 9.1 Release Notes List · 9.2 Release Note Detail
// 9.2a Split Modal · 9.2b Record Pickup Modal
// 9.3 Warehouse Attendant View
// ============================================================

// ============================================================
// 9.1 — RELEASE NOTES LIST
// ============================================================
const ReleaseNotesList = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('release')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Release notes" breadcrumb={['Operations', 'Release notes']} user={ngUser} actions={
      <Button variant="secondary" icon="download">Export</Button>
    } />}
  >
    {/* KPIs */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Active · awaiting pickup" value="11" sublabel="2 older than 48h" accent={<Icon name="card" size={15} stroke={2.2} />} />
      <StatCard label="Picked up today" value="14" trend="+4" trendDir="up" sublabel="vs yesterday" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Partial pickups" value="3" sublabel="awaiting follow-up" accent={<Icon name="package" size={15} stroke={2.2} />} />
      <StatCard label="Expired (30d)" value="1" sublabel="contact customer" accent={<Icon name="warn" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>148</span></Chip>
          <Chip count={11}>Active</Chip>
          <Chip count={132}>Picked up</Chip>
          <Chip count={3}>Partial</Chip>
          <Chip count={1}>Expired</Chip>
          <Chip count={1}>Cancelled</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Reference, customer, container…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="calendar">Last 30 days</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Reference', sortable: true},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Cartons', align: 'right'},
          {title: 'Payment'},
          {title: 'Release status'},
          {title: 'Type'},
          {title: 'Authorized', sortable: true},
          {title: '', width: 110},
        ]}
        rows={[
          rnRow({ref: 'RN-20260728-ABC123', cust: 'Ngozi Okonkwo', container: 'MSCU1234567', cartons: '4 / 4', pay: 'paid', status: 'active', partial: false, when: '2 hr ago', urgent: false}),
          rnRow({ref: 'RN-20260728-DEF456', cust: 'Emeka Eze', container: 'MSCU1234567', cartons: '22 / 22', pay: 'paid', status: 'active', partial: false, when: '4 hr ago'}),
          rnRow({ref: 'RN-20260727-GHI789', cust: 'Funmilayo Adeyemi', container: 'MSCU1234567', cartons: '14 / 14', pay: 'paid', status: 'active', partial: false, when: 'Yesterday', urgent: true}),
          rnRow({ref: 'RN-20260727-JKL012', cust: 'Bola Adesina', container: 'HLBU9384712', cartons: '6 / 8', pay: 'paid', status: 'active', partial: true, when: 'Yesterday'}),
          rnRow({ref: 'RN-20260726-MNO345', cust: 'Ibrahim Musa', container: 'HLBU9384712', cartons: '12 / 12', pay: 'paid', status: 'picked_up', partial: false, when: '26 Jul'}),
          rnRow({ref: 'RN-20260725-PQR678', cust: 'Adaeze Nwosu', container: 'COSU7194820', cartons: '10 / 10', pay: 'paid', status: 'picked_up', partial: false, when: '25 Jul'}),
          rnRow({ref: 'RN-20260724-STU901', cust: 'Olufemi Adetunji', container: 'COSU7194820', cartons: '4 / 4', pay: 'released_outstanding', status: 'picked_up', partial: false, when: '24 Jul'}),
          rnRow({ref: 'RN-20260720-VWX234', cust: 'Aisha Lawal', container: 'ONEU2847510', cartons: '0 / 6', pay: 'paid', status: 'expired', partial: false, when: '20 Jul'}),
          rnRow({ref: 'RN-20260718-YZA567', cust: 'Yusuf Garba', container: 'MAEU4729183', cartons: '8 / 8', pay: 'paid', status: 'picked_up', partial: false, when: '18 Jul'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const rnRow = ({ref, cust, container, cartons, pay, status, partial, when, urgent}) => {
  const payBadge = {
    paid: <Badge variant="success" size="sm">Paid</Badge>,
    partial: <Badge variant="warning" size="sm">Partial paid</Badge>,
    released_outstanding: <Badge variant="purple" size="sm">Released w/ outstanding</Badge>,
  }[pay];
  const statusBadge = {
    active: <Badge variant="warning">Active · awaiting pickup</Badge>,
    picked_up: <Badge variant="success">Picked up</Badge>,
    expired: <Badge variant="error">Expired</Badge>,
    cancelled: <Badge variant="neutral">Cancelled</Badge>,
  }[status];
  const action = status === 'active' ?
    <Button variant="accent" size="sm" icon="check">Record pickup</Button> :
    <Button variant="ghost" size="sm">View</Button>;
  return {
    suspended: urgent || status === 'expired',
    cells: [
      <Mono color={T.ink}>{ref}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <Mono color={partial ? T.warning : T.ink}>{cartons}</Mono>,
      payBadge,
      statusBadge,
      partial ? <Badge variant="info" size="sm" dot={false}>Partial</Badge> : <span style={{fontSize: 12, color: T.ink4}}>Full</span>,
      <span style={{fontSize: 12, color: T.ink3}}>{when}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>{action}</div>,
    ],
  };
};

// ============================================================
// 9.2 — RELEASE NOTE DETAIL
// ============================================================
const ReleaseNoteDetail = ({state = 'active', withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('release')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Operations', 'Release notes', 'RN-20260728-ABC123']} user={ngUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: state === 'active' ? T.warningSoft : state === 'picked_up' ? T.successSoft : T.errorSoft,
          color: state === 'active' ? T.warning : state === 'picked_up' ? T.success : T.error,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="card" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>RN-20260728-ABC123</h1>
            {state === 'active' && <Badge variant="warning">Active · awaiting pickup</Badge>}
            {state === 'picked_up' && <Badge variant="success">Picked up</Badge>}
            {state === 'partial' && <Badge variant="warning">Partial · 2 of 4 collected</Badge>}
            <Badge variant="success" size="sm">Paid in full</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <a style={{color: T.green, fontWeight: 600}}>Ngozi Okonkwo</a>
            <span style={{color: T.lineStrong}}>·</span>
            <Mono>MSCU1234567</Mono>
            <span style={{color: T.lineStrong}}>·</span>
            <span>4 cartons · 0.093 CBM</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Authorized 28 Jul 2026 by Ifeoma Uche</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="upload">Print</Button>
        <Button variant="secondary" icon="download">Export PDF</Button>
        {state === 'active' && <Button variant="secondary" icon="package">Split release</Button>}
        {state === 'active' && <Button variant="accent" icon="check">Record pickup</Button>}
        {state === 'picked_up' && <Button variant="ghost">View pickup record</Button>}
      </div>
    </div>

    {state === 'picked_up' && (
      <Banner variant="success" title="Picked up on 28 Jul at 14:32 by Adesoji Okonkwo (delegate)">
        Delegate name: Adesoji Okonkwo · ID: NIN-89472018349 · Phone: +234 805 124 7765. All 4 cartons released. Customer notified.
      </Banner>
    )}
    {state === 'active' && (
      <Banner variant="warning" title="Awaiting customer pickup — 2 hours since authorization">
        Customer has been notified via SMS + WhatsApp with QR code reference. Goods are held in Bay 4, Tin Can Port. Valid until <strong>04 Aug 2026</strong> (7 days).
      </Banner>
    )}
    <div style={{height: 20}} />

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Printable preview card */}
      <Card padding={0}>
        <div style={{padding: '14px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid ${T.line}`}}>
          <SectionHead title="Printable release note" sub="A4 portrait · what the warehouse staff scans" />
          <Button variant="ghost" size="sm" icon="upload">Print</Button>
        </div>
        <div style={{padding: 24, background: T.muted}}>
          <ReleaseNotePrint />
        </div>
      </Card>

      {/* Right column — pickup status + meta */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <Card>
          <SectionHead title="Pickup window" />
          <div style={{height: 12}} />
          <div style={{padding: 14, background: T.warningSoft, border: `1px solid ${T.warning}33`, borderRadius: 10, marginBottom: 12}}>
            <div style={{fontSize: 11, fontWeight: 700, color: T.warningStrong, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Valid until</div>
            <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 22, color: T.warningStrong, letterSpacing: '-0.01em', marginTop: 4}}>04 Aug 2026</div>
            <div style={{fontSize: 11, color: T.ink3, marginTop: 4}}>6 days remaining · expires automatically</div>
          </div>
          <Kvp label="Authorized at" value="28 Jul 2026, 12:08" />
          <Kvp label="By" value="Ifeoma Uche · Nigeria Office" />
          <Kvp label="Pickup location" value={<span style={{textAlign: 'right'}}>12 Wharf Road, Apapa<br />Lagos 100242 · Bay 4</span>} divider={false} />
        </Card>

        <Card>
          <SectionHead title="Customer" />
          <div style={{height: 8}} />
          <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px dashed ${T.line}`}}>
            <Avatar size={44} name="Ngozi Okonkwo" color={T.copper} />
            <div style={{flex: 1}}>
              <div style={{fontWeight: 700, fontSize: 14, color: T.ink}}>Ngozi Okonkwo</div>
              <div style={{fontSize: 12, color: T.ink3, fontFamily: T.mono}}>+234 801 234 5678</div>
            </div>
          </div>
          <Kvp label="WhatsApp delivered" value={<><span style={{color: T.success, fontWeight: 600}}>✓ 28 Jul, 12:09</span></>} />
          <Kvp label="SMS delivered" value={<><span style={{color: T.success, fontWeight: 600}}>✓ 28 Jul, 12:09</span></>} />
          <Kvp label="QR code scanned" value={<span style={{color: T.ink4, fontWeight: 500}}>Not yet</span>} divider={false} />
        </Card>

        <Card>
          <SectionHead title="Payment" />
          <div style={{height: 8}} />
          <Kvp label="Total billed" value={<Mono>₦100,008</Mono>} />
          <Kvp label="Total paid" value={<Mono color={T.success}>₦100,008</Mono>} />
          <Kvp label="Status" value={<Badge variant="success" size="sm">Paid in full</Badge>} />
          <Kvp label="Billing ref" value={<><Mono color={T.green}>BL-20260728-001</Mono></>} divider={false} />
        </Card>
      </div>
    </div>

    {/* Cartons table */}
    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Cartons on this release note" sub="4 cartons authorized · 0.093 CBM" />
      </div>
      <Table
        dense
        columns={[
          {title: 'Tag'},
          {title: 'Description'},
          {title: 'Weight', align: 'right'},
          {title: 'CBM', align: 'right'},
          {title: 'Declared', align: 'right'},
          {title: 'Status'},
        ]}
        rows={[
          {cells: [<Mono>SHX-00001</Mono>, <span style={{fontSize: 13, color: T.ink}}>Electronics (mixed)</span>, <Mono>12.8 kg</Mono>, <Mono color={T.green}>0.030</Mono>, <Mono>$380</Mono>, state === 'picked_up' ? <Badge variant="success" size="sm">Collected</Badge> : <Badge variant="warning" size="sm">Authorized</Badge>]},
          {cells: [<Mono>SHX-00002</Mono>, <span style={{fontSize: 13, color: T.ink}}>Clothing (assorted)</span>, <Mono>8.5 kg</Mono>, <Mono color={T.green}>0.021</Mono>, <Mono>$240</Mono>, state === 'picked_up' ? <Badge variant="success" size="sm">Collected</Badge> : <Badge variant="warning" size="sm">Authorized</Badge>]},
          {cells: [<Mono>SHX-00003</Mono>, <span style={{fontSize: 13, color: T.ink}}>Phone accessories</span>, <Mono>6.2 kg</Mono>, <Mono color={T.green}>0.018</Mono>, <Mono>$180</Mono>, state === 'picked_up' ? <Badge variant="success" size="sm">Collected</Badge> : <Badge variant="warning" size="sm">Authorized</Badge>]},
          {cells: [<Mono>SHX-00004</Mono>, <span style={{fontSize: 13, color: T.ink}}>Spare parts (auto)</span>, <Mono>9.1 kg</Mono>, <Mono color={T.green}>0.024</Mono>, <Mono>$320</Mono>, state === 'picked_up' ? <Badge variant="success" size="sm">Collected</Badge> : <Badge variant="warning" size="sm">Authorized</Badge>]},
        ]}
      />
    </Card>

    {withModal === 'split' && <SplitReleaseModal />}
    {withModal === 'pickup' && <RecordPickupModal />}
  </PageShell>
);

// ============================================================
// PRINTABLE RELEASE NOTE
// ============================================================
const ReleaseNotePrint = () => (
  <div style={{
    background: '#fff', boxShadow: T.shadowRest, borderRadius: 8,
    padding: 28, maxWidth: 560, margin: '0 auto',
    fontFamily: T.body, fontSize: 11, color: T.ink, position: 'relative',
  }}>
    {/* Watermark for "released with outstanding" — would show if applicable */}
    {/* Header */}
    <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', paddingBottom: 14, borderBottom: `2px solid ${T.ink}`, marginBottom: 14}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
        <div style={{width: 44, height: 44, borderRadius: 8, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 18, fontFamily: T.display}}>AL</div>
        <div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 13, color: T.ink}}>Acme Logistics Ltd</div>
          <div style={{fontSize: 9, color: T.ink4, fontStyle: 'italic', marginTop: 1}}>Trusted China-Nigeria cargo since 2019</div>
        </div>
      </div>
      <div style={{width: 64, height: 64, background: '#fff', border: `1px solid ${T.ink}`, padding: 4}}>
        {/* QR placeholder */}
        <div style={{width: '100%', height: '100%', background: `repeating-conic-gradient(${T.ink} 0% 25%, #fff 0% 50%) 50% / 8px 8px`}} />
      </div>
    </div>

    <div style={{textAlign: 'center', marginBottom: 14}}>
      <h1 style={{fontFamily: T.display, fontWeight: 900, fontSize: 16, letterSpacing: '0.1em', margin: 0, color: T.ink}}>GOODS RELEASE NOTE</h1>
      <div style={{fontFamily: T.mono, fontSize: 10, color: T.ink3, marginTop: 4}}>RN-20260728-ABC123</div>
    </div>

    {/* Meta */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 9, marginBottom: 14, padding: 10, background: T.muted, borderRadius: 4}}>
      <div><div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 7}}>Date of issue</div><div style={{fontFamily: T.mono, fontWeight: 600, marginTop: 2}}>28 July 2026</div></div>
      <div style={{textAlign: 'right'}}><div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 7}}>Valid until</div><div style={{fontFamily: T.mono, fontWeight: 600, marginTop: 2, color: T.warning}}>04 August 2026 (7d)</div></div>
    </div>

    {/* Customer & cargo */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 9.5, marginBottom: 14, border: `1px solid ${T.line}`}}>
      <div style={{padding: 10, borderRight: `1px solid ${T.line}`}}>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 8, marginBottom: 4}}>Customer</div>
        <div style={{fontWeight: 700}}>NGOZI OKONKWO</div>
        <div style={{fontFamily: T.mono, color: T.ink3, marginTop: 2}}>+234 801 234 5678</div>
      </div>
      <div style={{padding: 10}}>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 8, marginBottom: 4}}>Cargo</div>
        <div style={{fontFamily: T.mono, fontWeight: 700}}>MSCU1234567</div>
        <div style={{color: T.ink3, marginTop: 2}}>4 cartons · MSC Altair</div>
      </div>
    </div>

    {/* Carton tags */}
    <div style={{fontSize: 8, marginBottom: 14}}>
      <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6}}>Carton tags</div>
      <div style={{display: 'flex', gap: 4, flexWrap: 'wrap'}}>
        {['SHX-00001', 'SHX-00002', 'SHX-00003', 'SHX-00004'].map(t => (
          <span key={t} style={{fontFamily: T.mono, fontSize: 9, padding: '3px 8px', background: T.ink, color: '#fff', borderRadius: 2, fontWeight: 700}}>{t}</span>
        ))}
      </div>
    </div>

    {/* Payment status */}
    <div style={{padding: 10, background: T.successSoft, border: `1px solid ${T.success}`, borderRadius: 4, marginBottom: 14, textAlign: 'center'}}>
      <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 11, color: T.successStrong, letterSpacing: '0.06em'}}>✓ PAYMENT STATUS: PAID IN FULL</div>
      <div style={{fontFamily: T.mono, fontSize: 9, color: T.ink2, marginTop: 4}}>₦100,008 settled · Ref TRF-20260728-001</div>
    </div>

    {/* Collection instructions */}
    <div style={{fontSize: 9, marginBottom: 14}}>
      <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>Collection instructions</div>
      <p style={{margin: 0, lineHeight: 1.6}}>Present this release note (printed or digital) at <strong>12 Wharf Road, Apapa, Lagos · Bay 4</strong>. Operating hours: Mon-Sat, 8:00 AM – 5:00 PM. Customer or authorized delegate must present valid photo ID.</p>
    </div>

    {/* Auth footer */}
    <div className="sx-grid2" style={{paddingTop: 12, borderTop: `2px solid ${T.ink}`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 9}}>
      <div>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 7, marginBottom: 2}}>Authorized by</div>
        <div style={{fontWeight: 700}}>Ifeoma Uche</div>
        <div style={{color: T.ink3}}>Nigeria Office Staff</div>
      </div>
      <div style={{textAlign: 'right'}}>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 7, marginBottom: 2}}>Signature</div>
        <div style={{fontFamily: 'Brush Script MT, cursive', fontSize: 18, color: T.ink, fontStyle: 'italic'}}>Ifeoma U.</div>
      </div>
    </div>
    <div style={{textAlign: 'center', fontSize: 7, color: T.ink4, marginTop: 14, fontStyle: 'italic'}}>This document is valid for one-time use only. Shipx Platform.</div>
  </div>
);

// ============================================================
// 9.2a — SPLIT RELEASE MODAL
// ============================================================
const SplitReleaseModal = () => (
  <ModalOverlay>
    <div style={{width: 620, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Split release note</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>RN-20260728-ABC123 · Ngozi Okonkwo</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Banner variant="info" title="What does splitting do?">
          The customer collects part of their cartons now, and the rest stays on a new release note for later pickup. Useful when customers want to pick up by truckload, or split between recipients.
        </Banner>
        <div style={{height: 16}} />

        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 8}}>Select cartons for this pickup</label>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, fontSize: 12}}>
          <span style={{color: T.ink3}}><strong style={{color: T.green}}>2 of 4</strong> cartons selected</span>
          <div style={{display: 'flex', gap: 12}}>
            <a style={{color: T.green, fontWeight: 600, cursor: 'pointer'}}>Select all</a>
            <a style={{color: T.ink4, cursor: 'pointer'}}>Deselect all</a>
          </div>
        </div>

        <div style={{border: `1px solid ${T.line}`, borderRadius: 8, marginBottom: 16}}>
          <SplitCartonRow tag="SHX-00001" desc="Electronics (mixed)" wt="12.8 kg" selected />
          <SplitCartonRow tag="SHX-00002" desc="Clothing (assorted)" wt="8.5 kg" selected />
          <SplitCartonRow tag="SHX-00003" desc="Phone accessories" wt="6.2 kg" />
          <SplitCartonRow tag="SHX-00004" desc="Spare parts (auto)" wt="9.1 kg" last />
        </div>

        <Banner variant="warning" title="A partial release note will be generated">
          You're authorizing pickup of <strong>2 cartons (SHX-00001, SHX-00002)</strong>. The remaining <strong>2 cartons (SHX-00003, SHX-00004)</strong> stay on a new release note <Mono color={T.warningStrong}>RN-20260728-NEW001</Mono>. Both notes share the same payment record.
        </Banner>

        <Field label="Reason for split" optional multiline value="" placeholder="Customer requested separate pickups (visible in audit log only)" />
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="check">Split &amp; generate new note</Button>
      </div>
    </div>
  </ModalOverlay>
);

const SplitCartonRow = ({tag, desc, wt, selected, last}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '12px 14px', borderBottom: last ? 'none' : `1px solid ${T.line}`,
    background: selected ? T.greenTint : '#fff', cursor: 'pointer',
  }}>
    <Check checked={selected} />
    <Mono color={T.ink}>{tag}</Mono>
    <span style={{flex: 1, fontSize: 13, color: T.ink2}}>{desc}</span>
    <Mono color={T.ink3}>{wt}</Mono>
    {selected && <Badge variant="success" size="sm" dot={false}>Pickup now</Badge>}
  </div>
);

// ============================================================
// 9.2b — RECORD PICKUP MODAL
// ============================================================
const RecordPickupModal = () => (
  <ModalOverlay>
    <div style={{width: 640, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body, maxHeight: '90vh', display: 'flex', flexDirection: 'column'}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Record pickup</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>RN-20260728-ABC123 · Ngozi Okonkwo · 4 cartons</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px', overflowY: 'auto', flex: 1}}>
        {/* Verification banner */}
        <div style={{padding: 14, background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 10, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10}}>
          <Icon name="qr" size={18} color={T.green} stroke={2.5} />
          <div style={{flex: 1}}>
            <div style={{fontSize: 12, fontWeight: 700, color: T.greenDeep}}>QR code verified · 14:30 today</div>
            <div style={{fontSize: 11, color: T.ink3, marginTop: 1}}>Scanned by Taiwo Adeyemi (warehouse) — release note authentic and valid.</div>
          </div>
        </div>

        <Field label="Cartons released" required prefix="" suffix="of 4 authorized" value="4" helper="Default = all cartons. Reduce only if customer is collecting partially today." />

        <label style={{display: 'block', fontFamily: T.body, fontWeight: 600, fontSize: 13, color: T.ink2, marginBottom: 8}}>Who is collecting?</label>

        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16}}>
          <PickupChoice icon="user" title="Customer in person" sub="Photo ID required" />
          <PickupChoice icon="users" title="Authorized delegate" sub="ID + delegation proof" current />
        </div>

        {/* Delegate fields */}
        <Card padding={16} style={{background: T.muted, borderColor: T.line, marginBottom: 16}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12}}>Delegate details</div>
          <Field label="Full name" required value="Adesoji Okonkwo" placeholder="As written on ID" />
          <Field label="Phone number" icon="phone" value="+234 805 124 7765" />
          <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 1.4fr', gap: 14}}>
            <Field label="ID type" required>
              <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
                <span style={{flex: 1, fontSize: 14, color: T.ink}}>National ID (NIN)</span>
                <Icon name="chevdown" size={14} color={T.ink4} />
              </div>
            </Field>
            <Field label="ID number" required value="NIN-89472018349" placeholder="As on card" />
          </div>
        </Card>

        <Field label="Pickup notes" optional multiline value="" placeholder="Any observations on cargo condition, special handling, photos…" />

        <div style={{padding: 14, background: T.warningSoft, border: `1px solid ${T.warning}33`, borderRadius: 8, fontSize: 12, color: T.ink2, lineHeight: 1.5}}>
          <strong style={{color: T.warningStrong}}>Pickup confirmation</strong> is final. Once recorded, the cartons leave warehouse responsibility. Confirm delegate identity carefully before proceeding.
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="accent" icon="check">Confirm pickup</Button>
      </div>
    </div>
  </ModalOverlay>
);

const PickupChoice = ({icon, title, sub, current}) => (
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
// 9.3 — WAREHOUSE ATTENDANT VIEW
// ============================================================
const warehouseSidebarItems = (active) => [
  {group: 'Pickups', items: [
    {icon: 'package', label: 'Pickup queue', active: active === 'queue', badge: {color: T.warning, count: '11'}},
    {icon: 'check', label: "Today's pickups", active: active === 'today', count: '14'},
    {icon: 'card', label: 'All release notes', active: active === 'all'},
  ]},
];

const warehouseUser = {name: 'Taiwo Adeyemi', role: 'Warehouse Attendant'};

const WarehouseView = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="warehouse" brand={tenantBrand} items={warehouseSidebarItems('queue')} user={warehouseUser} />}
    topbar={<TopBar role="warehouse" title="" user={warehouseUser} search={false} actions={<DateRangeButton />} />}
    bg="#f5f2ec"
  >
    {/* Greeting */}
    <div style={{marginBottom: 20}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.warning, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Pickup queue</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Good morning, Taiwo. 11 to release.</h2>
      <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>Mon 28 July · 32°C · Bay 4 operational · 14 completed today</p>
    </div>

    {/* Big scanner block */}
    <Card padding={28} style={{marginBottom: 20, background: `linear-gradient(135deg, ${T.greenForest} 0%, ${T.greenDeep} 100%)`, color: '#fff', border: 'none', boxShadow: T.shadowModal}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap'}}>
        <div style={{
          width: 88, height: 88, borderRadius: 18,
          background: 'rgba(255,255,255,0.1)', color: T.greenFlash,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          border: '2px dashed rgba(255,255,255,0.3)',
        }}>
          <Icon name="qr" size={48} stroke={2} />
        </div>
        <div style={{flex: 1, minWidth: 280}}>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: '#fff'}}>Scan or type a release note reference</h3>
          <p style={{fontSize: 13, color: 'rgba(255,255,255,0.65)', margin: '6px 0 0'}}>Use the handheld scanner or type the RN-XXXX reference on the customer's release note.</p>
          <div style={{display: 'flex', gap: 8, marginTop: 14}}>
            <div style={{
              flex: 1, height: 48, background: '#fff', borderRadius: 8,
              display: 'flex', alignItems: 'center', padding: '0 16px', gap: 10,
            }}>
              <Icon name="search" size={16} color={T.ink4} />
              <input placeholder="RN-20260728-ABC123" style={{flex: 1, border: 0, outline: 0, fontFamily: T.mono, fontSize: 15, color: T.ink, fontWeight: 600}} />
            </div>
            <button style={{height: 48, padding: '0 24px', background: T.copper, color: '#fff', border: 'none', borderRadius: 8, fontFamily: T.body, fontWeight: 700, fontSize: 15, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8}}>
              <Icon name="arrowright" size={16} stroke={2.5} /> Look up
            </button>
          </div>
        </div>
      </div>
    </Card>

    {/* Stats row */}
    <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Awaiting pickup today" value="11" sublabel="2 urgent · 24h+ old" accent={<Icon name="clock" size={15} stroke={2.2} />} />
      <StatCard label="Completed today" value="14" trend="+4" trendDir="up" sublabel="vs yesterday" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Expired · not collected" value="1" sublabel="Aisha Lawal — call her" accent={<Icon name="warn" size={15} stroke={2.2} />} />
    </div>

    {/* Active queue table — warehouse-optimized */}
    <Card padding={0}>
      <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <SectionHead title="Ready for pickup" sub="Sorted by urgency · refresh every 2 min" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4}}><Icon name="refresh" size={13} /> Last updated 2 min ago</a>} />
      </div>
      <Table
        columns={[
          {title: 'Priority'},
          {title: 'Reference'},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Cartons', align: 'right'},
          {title: 'Authorized'},
          {title: '', width: 140},
        ]}
        rows={[
          warehouseRow({priority: 'urgent', ref: 'RN-20260727-GHI789', cust: 'Funmilayo Adeyemi', container: 'MSCU1234567', cartons: '14', when: 'Yesterday, 14:08', age: '26h ago'}),
          warehouseRow({priority: 'urgent', ref: 'RN-20260727-JKL012', cust: 'Bola Adesina', container: 'HLBU9384712', cartons: '6 / 8', when: 'Yesterday, 16:42', age: '24h ago', partial: true}),
          warehouseRow({priority: 'normal', ref: 'RN-20260728-DEF456', cust: 'Emeka Eze', container: 'MSCU1234567', cartons: '22', when: 'Today, 08:14', age: '4h ago'}),
          warehouseRow({priority: 'normal', ref: 'RN-20260728-ABC123', cust: 'Ngozi Okonkwo', container: 'MSCU1234567', cartons: '4', when: 'Today, 12:08', age: '2h ago'}),
          warehouseRow({priority: 'new', ref: 'RN-20260728-XYZ789', cust: 'Adaeze Nwosu', container: 'COSU7194820', cartons: '10', when: 'Today, 13:42', age: '20min ago'}),
          warehouseRow({priority: 'new', ref: 'RN-20260728-LMN456', cust: 'Ibrahim Musa', container: 'COSU7194820', cartons: '12', when: 'Today, 14:00', age: 'Just now'}),
        ]}
      />
    </Card>

    {withModal && <RecordPickupModal />}
  </PageShell>
);

const warehouseRow = ({priority, ref, cust, container, cartons, when, age, partial}) => {
  const priorityChip = {
    urgent: <div style={{display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: T.errorSoft, color: T.errorStrong, borderRadius: 9999, fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.error, boxShadow: `0 0 0 3px ${T.error}33`}} />Urgent</div>,
    normal: <div style={{display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: T.warningSoft, color: T.warningStrong, borderRadius: 9999, fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.warning}} />Normal</div>,
    new: <div style={{display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', background: T.successSoft, color: T.successStrong, borderRadius: 9999, fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}><span style={{width: 6, height: 6, borderRadius: '50%', background: T.success}} />New</div>,
  }[priority];
  return {
    cells: [
      priorityChip,
      <Mono color={T.ink}>{ref}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <Mono color={partial ? T.warning : T.ink}>{cartons}</Mono>,
      <div>
        <div style={{fontSize: 12, color: T.ink2}}>{when}</div>
        <div style={{fontSize: 11, color: T.ink4, marginTop: 1, fontStyle: 'italic'}}>{age}</div>
      </div>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        <Button variant="accent" size="sm" icon="check">Record pickup</Button>
      </div>,
    ],
  };
};

Object.assign(window, {
  ReleaseNotesList, ReleaseNoteDetail, SplitReleaseModal, RecordPickupModal,
  WarehouseView, ReleaseNotePrint,
});
