// ============================================================
// Shipx — China Office Staff Screens (Section 5)
// 5.1 Container List · 5.2 Create Container · 5.3 Container Detail
// 5.4 Create Packing List · 5.5 Packing List Detail · 5.6 Packing List List
// ============================================================

const chinaSidebarItems = (active) => [
  {group: 'Operations', items: [
    {icon: 'container', label: 'Containers', active: active === 'containers'},
    {icon: 'plus', label: 'Create container', active: active === 'new-container'},
  ]},
  {group: 'Packing lists', items: [
    {icon: 'package', label: 'All packing lists', active: active === 'pls', badge: {color: T.warning, count: '6'}},
    {icon: 'plus', label: 'Create packing list', active: active === 'new-pl'},
  ]},
  {group: 'Coordination', items: [
    {icon: 'file', label: 'Manifests', active: active === 'manifests'},
    {icon: 'warn', label: 'CBM disputes', active: active === 'disputes', badge: {color: T.error, count: '2'}},
  ]},
];

const chinaUser = {name: 'Kwame Asante', role: 'China Office Staff'};

// Local modal overlay (avoid cross-file coupling)
const ModalOverlay = ({children}) => (
  <div style={{position: 'absolute', inset: 0, background: 'rgba(11,47,13,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 32}}>{children}</div>
);

// ============================================================
// 5.1 — CONTAINER LIST
// ============================================================
const ContainerList = () => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('containers')} user={chinaUser} />}
    topbar={<TopBar role="china" title="Containers" breadcrumb={['Operations', 'Containers']} user={chinaUser} actions={
      <>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus">Create container</Button>
      </>
    } />}
  >
    {/* Stats row */}
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Active" value="14" sublabel="China-side" accent={<Icon name="container" size={15} stroke={2.2} />} />
      <StatCard label="Packed" value="8" sublabel="ready to ship" accent={<Icon name="package" size={15} stroke={2.2} />} />
      <StatCard label="In transit" value="22" sublabel="at sea" accent={<Icon name="ship" size={15} stroke={2.2} />} />
      <StatCard label="Arrived (NG)" value="6" sublabel="handed off" accent={<Icon name="map" size={15} stroke={2.2} />} />
      <StatCard label="Cleared (30d)" value="48" trend="+12%" trendDir="up" accent={<Icon name="check" size={15} stroke={2.2} />} />
    </div>

    {/* Filter bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>50</span></Chip>
          <Chip count={14}>Active</Chip>
          <Chip count={8}>Packed</Chip>
          <Chip count={22}>In transit</Chip>
          <Chip count={6}>Arrived NG</Chip>
          <Chip count={48}>Cleared</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Container number, vessel name, voyage…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="calendar">Last 30 days</Button>
        <Button variant="secondary" size="md" icon="filter">Filters</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Container', sortable: true},
          {title: 'Vessel · voyage'},
          {title: 'Route'},
          {title: 'Status'},
          {title: 'Packing lists', align: 'right'},
          {title: 'CBM', align: 'right'},
          {title: 'ETA', sortable: true},
          {title: '', width: 40},
        ]}
        rows={[
          containerRow({num: 'MSCU1234567', vessel: 'MSC Altair', voyage: '248E', origin: 'Guangzhou', dest: 'Lagos', status: 'in_transit', pls: '12 / 12', cbm: '11.84', eta: '14 Aug'}),
          containerRow({num: 'HLBU9384712', vessel: 'Hapag Hamburg', voyage: '094W', origin: 'Shanghai', dest: 'Lagos', status: 'arrived_ng', pls: '8 / 8', cbm: '8.42', eta: 'Today'}),
          containerRow({num: 'COSU7194820', vessel: 'COSCO Beijing', voyage: '301E', origin: 'Shenzhen', dest: 'Lagos', status: 'cleared', pls: '15 / 15', cbm: '14.20', eta: 'Cleared'}),
          containerRow({num: 'ONEU2847510', vessel: 'ONE Aquila', voyage: '156W', origin: 'Ningbo', dest: 'Lagos', status: 'in_transit', pls: '9 / 10', cbm: '6.12', eta: '22 Aug'}),
          containerRow({num: 'MAEU4729183', vessel: 'Maersk Surabaya', voyage: '188E', origin: 'Guangzhou', dest: 'Lagos', status: 'active', pls: '7 / 12', cbm: '5.80', eta: '04 Sep', selected: true}),
          containerRow({num: 'SUDU3819273', vessel: 'Hamburg Süd Rio', voyage: '042W', origin: 'Shanghai', dest: 'Lagos', status: 'packed', pls: '11 / 11', cbm: '12.04', eta: '12 Sep'}),
          containerRow({num: 'EGHU8472019', vessel: 'Evergreen Marine', voyage: '215E', origin: 'Shenzhen', dest: 'Lagos', status: 'active', pls: '4 / 18', cbm: '2.10', eta: '18 Sep'}),
          containerRow({num: 'YMLU6018937', vessel: 'Yang Ming', voyage: '128W', origin: 'Ningbo', dest: 'Lagos', status: 'in_transit', pls: '13 / 13', cbm: '9.82', eta: '28 Aug'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const containerRow = ({num, vessel, voyage, origin, dest, status, pls, cbm, eta, selected}) => {
  const badge = {
    active: <Badge variant="warning">Active</Badge>,
    packed: <Badge variant="info">Packed</Badge>,
    in_transit: <Badge variant="info">In transit</Badge>,
    arrived_ng: <Badge variant="warning">Arrived NG</Badge>,
    cleared: <Badge variant="success">Cleared</Badge>,
  }[status];
  const originCode = {Guangzhou: 'CN-CAN', Shanghai: 'CN-SHA', Shenzhen: 'CN-SZX', Ningbo: 'CN-NGB'}[origin] || origin;
  const destCode = {Lagos: 'NG-LOS'}[dest] || dest;
  return {
    selected,
    cells: [
      <div><Mono color={T.ink}>{num}</Mono></div>,
      <div style={{minWidth: 0}}>
        <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.25}}>{vessel}</div>
        <div style={{fontSize: 11, color: T.ink4, marginTop: 1, fontFamily: T.mono}}>Voy {voyage}</div>
      </div>,
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <span style={{fontFamily: T.mono, fontSize: 11, fontWeight: 600, color: T.info}}>{originCode}</span>
        <Icon name="arrowright" size={10} color={T.ink4} />
        <span style={{fontFamily: T.mono, fontSize: 11, fontWeight: 600, color: T.copper}}>{destCode}</span>
      </div>,
      badge,
      <Mono>{pls}</Mono>,
      <Mono>{cbm}</Mono>,
      <Mono color={eta === 'Today' ? T.warning : eta === 'Cleared' ? T.success : T.ink}>{eta}</Mono>,
      <KebabBtn />,
    ],
  };
};

// ============================================================
// 5.2 — CREATE CONTAINER
// ============================================================
const CreateContainer = () => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('new-container')} user={chinaUser} />}
    topbar={<TopBar role="china" title="" breadcrumb={['Operations', 'Containers', 'New container']} user={chinaUser} />}
  >
    <div style={{maxWidth: 720, margin: '0 auto'}}>
      <PageHeader
        eyebrow="China-side · operations"
        title="Create new container"
        subtitle="Set up the container manifest. You'll attach customer packing lists once the container is created."
      />

      <Card padding={32}>
        <SectionHead title="Container details" sub="ISO 6346 format · validated on save" />
        <div style={{height: 16}} />
        <Field label="Container number" required icon="container" placeholder="e.g. MSCU1234567" value="MSCU1234567" focused helper="11-character ISO 6346 identifier. We validate the check digit." />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="Container type" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{flex: 1, fontSize: 14, color: T.ink}}>40' High Cube (HC)</span>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
          <Field label="Seal number" placeholder="e.g. SHX-04891" value="SHX-04891" helper="Optional · added at packing time" />
        </div>

        <SectionHead title="Vessel & voyage" />
        <div style={{height: 12}} />
        <Field label="Vessel name" required value="MSC Altair" placeholder="e.g. MSC Altair" />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="Voyage number" required value="248E" placeholder="e.g. 248E" />
          <Field label="Shipping line" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{flex: 1, fontSize: 14, color: T.ink}}>Mediterranean Shipping Co. (MSC)</span>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
        </div>

        <SectionHead title="Route" />
        <div style={{height: 12}} />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="Origin port" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{display: 'inline-flex', alignItems: 'center', gap: 8}}>
                <Mono color={T.info}>CN-CAN</Mono>
                <span style={{fontSize: 14, color: T.ink}}>Guangzhou Baiyun</span>
              </span>
              <span style={{flex: 1}} />
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
          <Field label="Destination port" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{display: 'inline-flex', alignItems: 'center', gap: 8}}>
                <Mono color={T.copper}>NG-LOS</Mono>
                <span style={{fontSize: 14, color: T.ink}}>Tin Can Island, Lagos</span>
              </span>
              <span style={{flex: 1}} />
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
        </div>

        <SectionHead title="Schedule" />
        <div style={{height: 12}} />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="ETD Guangzhou" required icon="calendar" value="01 Aug 2026" />
          <Field label="ETA Lagos" required icon="calendar" value="14 Aug 2026" />
        </div>

        <Field label="Internal notes" optional multiline value="" placeholder="Anything special about this container (priority customer, special handling, fragile cargo)…" />
      </Card>

      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 0 0'}}>
        <Button variant="ghost" icon="arrowleft">Cancel</Button>
        <div style={{display: 'flex', gap: 10}}>
          <Button variant="secondary">Save as draft</Button>
          <Button variant="primary" icon="check">Create container</Button>
        </div>
      </div>
    </div>
  </PageShell>
);

// ============================================================
// 5.3 — CONTAINER DETAIL
// ============================================================
const ContainerDetail = ({tab = 'overview', withDocsModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('containers')} user={chinaUser} />}
    topbar={<TopBar role="china" title="" breadcrumb={['Operations', 'Containers', 'MSCU1234567']} user={chinaUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: T.infoSoft, color: T.info,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="container" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>MSCU1234567</h1>
            <Badge variant="info">In transit</Badge>
            <Badge variant="neutral" dot={false}>40' HC</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <span style={{fontWeight: 600}}>MSC Altair · Voy 248E</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
              <Mono color={T.info}>CN-CAN</Mono>
              <Icon name="arrowright" size={10} color={T.ink4} />
              <Mono color={T.copper}>NG-LOS</Mono>
            </span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>ETA 14 Aug 2026</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="download">Export manifest</Button>
        <Button variant="secondary" icon="upload">Upload document</Button>
        <Button variant="primary" icon="plus">Add packing list</Button>
      </div>
    </div>

    <Tabs tabs={['Overview', 'Packing lists', 'Manifest', 'Documents', 'Tracking']} active={
      tab === 'overview' ? 'Overview' :
      tab === 'pls' ? 'Packing lists' :
      tab === 'manifest' ? 'Manifest' :
      tab === 'docs' ? 'Documents' :
      tab === 'tracking' ? 'Tracking' : 'Overview'
    } />

    {tab === 'overview' && <ContainerOverview />}
    {tab === 'pls' && <ContainerPLs />}
    {tab === 'docs' && <ContainerDocs />}
    {tab === 'tracking' && <ContainerTracking />}
    {withDocsModal && <UploadDocumentModal />}
  </PageShell>
);

// ============================================================
// CONTAINER DOCUMENTS TAB + UPLOAD MODAL (14.4)
// ============================================================
const ContainerDocs = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
      <SectionHead title="Documents" sub="Bill of lading, customs forms, inspection reports" />
      <Button variant="primary" size="sm" icon="upload">Upload document</Button>
    </div>
    <Table
      columns={[
        {title: 'Type'},
        {title: 'Description'},
        {title: 'Uploaded by'},
        {title: 'Size', align: 'right'},
        {title: 'Date'},
        {title: '', width: 120},
      ]}
      rows={[
        {cells: [
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}><div style={{width: 32, height: 32, borderRadius: 8, background: T.errorSoft, color: T.error, display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Icon name="file" size={15} /></div><span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Bill of Lading</span></div>,
          <span style={{fontSize: 13, color: T.ink2}}>BL-MSCU1234567-2026</span>,
          <UserCell name="Kwame Asante" email="China Office" />,
          <Mono color={T.ink3}>1.2 MB</Mono>,
          <span style={{fontSize: 12, color: T.ink3}}>28 Jul 2026</span>,
          <div style={{display: 'flex', gap: 8, justifyContent: 'flex-end'}}><button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Download</button><button style={{background: 'transparent', border: 0, color: T.error, padding: 4, cursor: 'pointer', display: 'flex'}}><Icon name="x" size={14} /></button></div>,
        ]},
        {cells: [
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}><div style={{width: 32, height: 32, borderRadius: 8, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Icon name="file" size={15} /></div><span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Customs Declaration</span></div>,
          <span style={{fontSize: 13, color: T.ink2}}>NCS Form C-47</span>,
          <UserCell name="Ifeoma Uche" email="Nigeria Office" />,
          <Mono color={T.ink3}>820 KB</Mono>,
          <span style={{fontSize: 12, color: T.ink3}}>29 Jul 2026</span>,
          <div style={{display: 'flex', gap: 8, justifyContent: 'flex-end'}}><button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Download</button><button style={{background: 'transparent', border: 0, color: T.error, padding: 4, cursor: 'pointer', display: 'flex'}}><Icon name="x" size={14} /></button></div>,
        ]},
        {cells: [
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}><div style={{width: 32, height: 32, borderRadius: 8, background: T.warningSoft, color: T.warning, display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Icon name="file" size={15} /></div><span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Container Seal Certificate</span></div>,
          <span style={{fontSize: 13, color: T.ink2}}>Seal SHX-04891 photo</span>,
          <UserCell name="Mei Lin Zhang" email="China Office" />,
          <Mono color={T.ink3}>2.4 MB</Mono>,
          <span style={{fontSize: 12, color: T.ink3}}>29 Jul 2026</span>,
          <div style={{display: 'flex', gap: 8, justifyContent: 'flex-end'}}><button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Download</button><button style={{background: 'transparent', border: 0, color: T.error, padding: 4, cursor: 'pointer', display: 'flex'}}><Icon name="x" size={14} /></button></div>,
        ]},
      ]}
    />
  </Card>
);

const UploadDocumentModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Upload document</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>Container MSCU1234567</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Field label="Document type" required>
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
            <span style={{flex: 1, fontSize: 14, color: T.ink}}>Bill of Lading</span>
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <Field label="Description" value="" placeholder="Brief description of the document" optional />

        {/* Upload zone with progress */}
        <div style={{marginBottom: 16}}>
          <label style={{display: 'block', fontFamily: T.body, fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>File</label>
          <div style={{border: `1.5px solid ${T.green}55`, borderRadius: 10, padding: 16, background: T.greenTint}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10}}>
              <div style={{width: 36, height: 36, borderRadius: 8, background: T.green, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}><Icon name="file" size={16} /></div>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>bill-of-lading-mscu1234567.pdf</div>
                <div style={{fontSize: 11, color: T.ink4}}>1.2 MB · uploading…</div>
              </div>
              <button style={{background: 'transparent', border: 0, color: T.ink4, fontSize: 12, fontWeight: 600, cursor: 'pointer'}}>Cancel</button>
            </div>
            <div style={{height: 6, background: '#fff', borderRadius: 3, overflow: 'hidden'}}>
              <div style={{height: '100%', width: '67%', background: T.green, borderRadius: 3}} />
            </div>
            <div style={{fontSize: 11, color: T.green, fontWeight: 600, marginTop: 6, textAlign: 'right'}}>Uploading… 67%</div>
          </div>
          <div style={{fontSize: 11, color: T.ink4, marginTop: 6}}>Accepted: PDF, JPG, PNG · Max 25 MB</div>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="upload">Upload</Button>
      </div>
    </div>
  </ModalOverlay>
);

const ContainerOverview = () => (
  <>
    {/* Tracking stepper */}
    <Card style={{marginBottom: 20}}>
      <SectionHead title="Tracking pipeline" sub="China-side stages in blue · Nigeria-side stages in green" />
      <div style={{height: 20}} />
      <TrackingStepper current={3} />
    </Card>

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20}}>
      <Card>
        <SectionHead title="Container info" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Edit →</a>} />
        <div style={{height: 8}} />
        <Kvp label="Container #" value={<Mono>MSCU1234567</Mono>} />
        <Kvp label="Container type" value="40' High Cube (HC)" />
        <Kvp label="Seal #" value={<Mono>SHX-04891</Mono>} />
        <Kvp label="Vessel" value="MSC Altair" />
        <Kvp label="Voyage" value={<Mono>248E</Mono>} />
        <Kvp label="Shipping line" value="Mediterranean Shipping Co." />
        <Kvp label="Created by" value="Kwame Asante · 28 Jul 2026" divider={false} />
      </Card>

      <Card>
        <SectionHead title="Cargo summary" sub="Aggregated from all packing lists" />
        <div style={{height: 12}} />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12}}>
          <SummaryTile label="Customers" value="12" sub="all approved" />
          <SummaryTile label="Packing lists" value="12 / 12" sub="all approved" color={T.success} />
          <SummaryTile label="Total cartons" value="148" sub="across 12 PLs" />
          <SummaryTile label="Total CBM" value="11.84" sub="of 76 CBM capacity" />
        </div>
        <div style={{padding: 14, background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 8}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6}}>
            <span style={{fontSize: 12, fontWeight: 600, color: T.greenDeep}}>Utilization</span>
            <span style={{fontFamily: T.mono, fontSize: 13, fontWeight: 700, color: T.green}}>15.6%</span>
          </div>
          <div style={{height: 6, background: T.greenSoft, borderRadius: 3, overflow: 'hidden'}}>
            <div style={{height: '100%', width: '15.6%', background: T.green, borderRadius: 3}} />
          </div>
          <div style={{fontSize: 11, color: T.ink3, marginTop: 6}}>11.84 of 76 CBM packed · room for 64.16 more</div>
        </div>
      </Card>
    </div>

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Recent events" sub="Last 5 tracking events" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>View all →</a>} />
        </div>
        <div style={{padding: '0 20px 20px'}}>
          <EventRow icon="ship" color={T.info} title="Loaded onto vessel" sub="MSC Altair · voyage 248E · 09:08 WAT" when="31 Jul" />
          <EventRow icon="package" color={T.success} title="Container packed & sealed" sub="Seal SHX-04891 applied · 11.84 CBM final" when="29 Jul" />
          <EventRow icon="check" color={T.success} title="All packing lists approved" sub="12 / 12 approved by Amara Okafor" when="28 Jul" />
          <EventRow icon="plus" color={T.info} title="12th packing list added" sub="Funmilayo Adeyemi · 8 cartons · 0.74 CBM" when="27 Jul" />
          <EventRow icon="container" color={T.ink3} title="Container created" sub="MSCU1234567 created by Kwame Asante" when="25 Jul" last />
        </div>
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Customers on this container" sub="12 customers · sorted by CBM" />
        </div>
        <Table
          dense
          columns={[
            {title: 'Customer'},
            {title: 'Cartons', align: 'right'},
            {title: 'CBM', align: 'right'},
            {title: 'Status'},
          ]}
          rows={[
            {cells: [<UserCell name="Emeka Eze" email="42 shipments lifetime" />, <Mono>22</Mono>, <Mono>2.14</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
            {cells: [<UserCell name="Ngozi Okonkwo" email="14 shipments lifetime" />, <Mono>18</Mono>, <Mono>1.84</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
            {cells: [<UserCell name="Funmilayo Adeyemi" email="21 shipments lifetime" />, <Mono>14</Mono>, <Mono>1.42</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
            {cells: [<UserCell name="Ibrahim Musa" email="28 shipments lifetime" />, <Mono>12</Mono>, <Mono>1.18</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
            {cells: [<UserCell name="Adaeze Nwosu" email="3 shipments lifetime" />, <Mono>10</Mono>, <Mono>0.94</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
            {cells: [<UserCell name="Bola Adesina" email="11 shipments lifetime" />, <Mono>8</Mono>, <Mono>0.72</Mono>, <Badge variant="success" size="sm">Approved</Badge>]},
          ]}
        />
      </Card>
    </div>
  </>
);

const TrackingStepper = ({current = 3}) => {
  const stages = [
    {label: 'Received', sub: 'China warehouse', side: 'china'},
    {label: 'Packed', sub: 'Container sealed', side: 'china'},
    {label: 'In transit', sub: 'At sea', side: 'china'},
    {label: 'Arrived NG', sub: 'Tin Can Port', side: 'ng'},
    {label: 'Customs', sub: 'Clearance', side: 'ng'},
    {label: 'Cleared', sub: 'Released', side: 'ng'},
    {label: 'Ready', sub: 'For pickup', side: 'ng'},
    {label: 'Completed', sub: 'Delivered', side: 'ng'},
  ];
  return (
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 4, position: 'relative'}}>
      {stages.map((s, i) => {
        const done = i < current;
        const isCurrent = i === current;
        const sideColor = s.side === 'china' ? T.info : T.green;
        return (
          <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative'}}>
            {/* Connecting line */}
            {i > 0 && (
              <div style={{
                position: 'absolute', top: 14, right: '50%', width: '100%', height: 2,
                background: done ? sideColor : T.line, zIndex: 0,
              }} />
            )}
            <div style={{
              width: 30, height: 30, borderRadius: '50%',
              background: done ? sideColor : isCurrent ? '#fff' : T.muted,
              border: `${isCurrent ? 3 : 2}px solid ${done || isCurrent ? sideColor : T.lineStrong}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', position: 'relative', zIndex: 1,
              boxShadow: isCurrent ? `0 0 0 6px ${sideColor}22` : 'none',
            }}>
              {done ? <Icon name="check" size={14} color="#fff" stroke={3} /> :
               isCurrent ? <div style={{width: 8, height: 8, borderRadius: '50%', background: sideColor}} /> : null}
            </div>
            <div style={{marginTop: 8, textAlign: 'center'}}>
              <div style={{fontSize: 11, fontWeight: 700, color: done || isCurrent ? T.ink : T.ink4, letterSpacing: '0.02em'}}>{s.label}</div>
              <div style={{fontSize: 10, color: T.ink4, marginTop: 1}}>{s.sub}</div>
              {isCurrent && (
                <div style={{
                  marginTop: 6, display: 'inline-flex', alignItems: 'center', gap: 4,
                  background: sideColor, color: '#fff', padding: '2px 8px', borderRadius: 9999,
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                }}>Now</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const SummaryTile = ({label, value, sub, color}) => (
  <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8}}>
    <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}>{label}</div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: color || T.ink, marginTop: 4, letterSpacing: '-0.01em', lineHeight: 1.1}}>{value}</div>
    <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{sub}</div>
  </div>
);

const EventRow = ({icon, color, title, sub, when, last}) => (
  <div style={{display: 'flex', gap: 12, padding: '10px 0', borderBottom: last ? 'none' : `1px dashed ${T.line}`}}>
    <div style={{width: 28, height: 28, borderRadius: 8, background: color + '18', color, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
      <Icon name={icon} size={14} />
    </div>
    <div style={{flex: 1, minWidth: 0}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.3}}>{title}</div>
      <div style={{fontSize: 12, color: T.ink3, marginTop: 2}}>{sub}</div>
    </div>
    <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono, flexShrink: 0}}>{when}</div>
  </div>
);

const ContainerPLs = () => (
  <Card padding={0}>
    <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
      <SectionHead title="Packing lists on this container" sub="12 lists · all approved · 11.84 CBM total" />
      <Button variant="primary" size="sm" icon="plus">Add packing list</Button>
    </div>
    <Table
      columns={[
        {title: 'Ref #', sortable: true},
        {title: 'Customer'},
        {title: 'Cartons', align: 'right'},
        {title: 'CBM', align: 'right'},
        {title: 'Weight', align: 'right'},
        {title: 'Status'},
        {title: 'Submitted'},
        {title: '', width: 40},
      ]}
      rows={[
        {cells: [<Mono>PL-20260725-001</Mono>, <UserCell name="Emeka Eze" email="22 cartons" />, <Mono>22</Mono>, <Mono>2.14</Mono>, <Mono>148 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>25 Jul</span>, <ViewLink />]},
        {cells: [<Mono>PL-20260725-002</Mono>, <UserCell name="Ngozi Okonkwo" email="18 cartons" />, <Mono>18</Mono>, <Mono>1.84</Mono>, <Mono>122 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>25 Jul</span>, <ViewLink />]},
        {cells: [<Mono>PL-20260726-003</Mono>, <UserCell name="Funmilayo Adeyemi" email="14 cartons" />, <Mono>14</Mono>, <Mono>1.42</Mono>, <Mono>96 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>26 Jul</span>, <ViewLink />]},
        {cells: [<Mono>PL-20260726-004</Mono>, <UserCell name="Ibrahim Musa" email="12 cartons" />, <Mono>12</Mono>, <Mono>1.18</Mono>, <Mono>82 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>26 Jul</span>, <ViewLink />]},
        {cells: [<Mono>PL-20260727-005</Mono>, <UserCell name="Adaeze Nwosu" email="10 cartons" />, <Mono>10</Mono>, <Mono>0.94</Mono>, <Mono>62 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>27 Jul</span>, <ViewLink />]},
        {cells: [<Mono>PL-20260727-006</Mono>, <UserCell name="Bola Adesina" email="8 cartons" />, <Mono>8</Mono>, <Mono>0.72</Mono>, <Mono>48 kg</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>27 Jul</span>, <ViewLink />]},
      ]}
    />
  </Card>
);

const ContainerTracking = () => (
  <>
    <Card style={{marginBottom: 20}}>
      <SectionHead title="Tracking timeline" sub="All status events for MSCU1234567" />
      <div style={{height: 16}} />
      <TrackingStepper current={3} />
    </Card>
    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Event log" sub="All tracking events, newest first" action={<Button variant="secondary" size="sm" icon="download">Export</Button>} />
      </div>
      <Table
        columns={[
          {title: 'Timestamp'},
          {title: 'Event'},
          {title: 'Status change'},
          {title: 'Updated by'},
          {title: 'Notes'},
        ]}
        rows={[
          {cells: [<Mono>31 Jul 09:08</Mono>, <Badge variant="info">Loaded vessel</Badge>, <span style={{fontSize: 12, color: T.ink3}}>packed → <strong style={{color: T.success}}>in_transit</strong></span>, <UserCell name="Kwame Asante" email="China Office" />, <span style={{fontSize: 12, color: T.ink3}}>MSC Altair voy 248E</span>]},
          {cells: [<Mono>29 Jul 16:42</Mono>, <Badge variant="info">Container sealed</Badge>, <span style={{fontSize: 12, color: T.ink3}}>received → <strong style={{color: T.success}}>packed</strong></span>, <UserCell name="Mei Lin Zhang" email="China Office" />, <span style={{fontSize: 12, color: T.ink3}}>Seal SHX-04891 applied</span>]},
          {cells: [<Mono>28 Jul 11:30</Mono>, <Badge variant="success">PL approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>12 / 12 packing lists approved</span>, <UserCell name="Amara Okafor" email="Tenant Admin" />, <span style={{fontSize: 12, color: T.ink3}}>Bulk approve action</span>]},
          {cells: [<Mono>27 Jul 14:08</Mono>, <Badge variant="success">PL added</Badge>, <span style={{fontSize: 12, color: T.ink3}}>12th packing list submitted</span>, <UserCell name="Kwame Asante" email="China Office" />, <span style={{fontSize: 12, color: T.ink3}}>Funmilayo Adeyemi · 0.74 CBM</span>]},
          {cells: [<Mono>25 Jul 09:00</Mono>, <Badge variant="info">Created</Badge>, <span style={{fontSize: 12, color: T.ink3}}>— → <strong style={{color: T.success}}>active</strong></span>, <UserCell name="Kwame Asante" email="China Office" />, <span style={{fontSize: 12, color: T.ink3}}>Container created in Shipx</span>]},
        ]}
      />
    </Card>
  </>
);

// ============================================================
// 5.4 — CREATE PACKING LIST (3-step wizard)
// ============================================================
const CreatePackingList = ({step = 1}) => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('new-pl')} user={chinaUser} />}
    topbar={<TopBar role="china" title="" breadcrumb={['Operations', 'Packing lists', 'New packing list']} user={chinaUser} />}
  >
    <div style={{maxWidth: 1100, margin: '0 auto'}}>
      <PageHeader
        eyebrow="China-side · packing"
        title="Create packing list"
        subtitle="Capture carton-level details for a customer's cargo. Submit for approval when complete."
      />

      <WizardSteps current={step} />
      <div style={{height: 20}} />

      {step === 1 && <PLStep1 />}
      {step === 2 && <PLStep2 />}
      {step === 3 && <PLStep3 />}
    </div>
  </PageShell>
);

const WizardSteps = ({current = 1}) => {
  const steps = [
    {n: 1, label: 'Details', sub: 'Customer + container'},
    {n: 2, label: 'Items', sub: 'Cartons + measurements'},
    {n: 3, label: 'Review', sub: 'Verify + submit'},
  ];
  return (
    <Card padding={0}>
      <div style={{display: 'flex', padding: 8}}>
        {steps.map((s, i) => {
          const done = s.n < current;
          const isCurrent = s.n === current;
          return (
            <React.Fragment key={s.n}>
              <div style={{
                flex: 1, display: 'flex', alignItems: 'center', gap: 12,
                padding: '14px 16px', borderRadius: 10,
                background: isCurrent ? T.greenTint : 'transparent',
              }}>
                <div style={{
                  width: 36, height: 36, borderRadius: '50%',
                  background: done ? T.success : isCurrent ? T.green : T.muted,
                  border: `2px solid ${done ? T.success : isCurrent ? T.green : T.lineStrong}`,
                  color: done || isCurrent ? '#fff' : T.ink4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontWeight: 700, fontSize: 14, flexShrink: 0,
                  boxShadow: isCurrent ? `0 0 0 5px ${T.green}22` : 'none',
                }}>
                  {done ? <Icon name="check" size={16} stroke={3} /> : s.n}
                </div>
                <div>
                  <div style={{fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.ink4, lineHeight: 1.2}}>Step {s.n}</div>
                  <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: isCurrent || done ? T.ink : T.ink3, lineHeight: 1.2, marginTop: 1}}>{s.label}</div>
                  <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{s.sub}</div>
                </div>
              </div>
              {i < steps.length - 1 && <div style={{width: 24, alignSelf: 'center', display: 'flex', justifyContent: 'center'}}><Icon name="chevright" size={14} color={T.ink4} /></div>}
            </React.Fragment>
          );
        })}
      </div>
    </Card>
  );
};

const PLStep1 = () => (
  <Card padding={32}>
    <SectionHead title="Customer & container" sub="Who is this cargo for, and which container is it loading into?" />
    <div style={{height: 20}} />
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16}}>
      <Field label="Customer" required>
        <div style={{
          height: 48, background: '#fff', border: `2px solid ${T.green}`,
          borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 12,
          boxShadow: `0 0 0 3px rgba(45,196,56,0.15)`,
        }}>
          <Avatar size={32} name="Ngozi Okonkwo" color={T.copper} />
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontSize: 14, fontWeight: 600, color: T.ink, lineHeight: 1.2}}>Ngozi Okonkwo</div>
            <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono}}>+234 801 234 5678 · 14 shipments lifetime</div>
          </div>
          <Icon name="chevdown" size={14} color={T.ink4} />
        </div>
      </Field>

      <Field label="Container" required>
        <div style={{
          height: 48, background: '#fff', border: `2px solid ${T.green}`,
          borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 12,
          boxShadow: `0 0 0 3px rgba(45,196,56,0.15)`,
        }}>
          <div style={{width: 32, height: 32, borderRadius: 8, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
            <Icon name="container" size={16} />
          </div>
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{fontFamily: T.mono, fontSize: 14, fontWeight: 700, color: T.ink, lineHeight: 1.2}}>MSCU1234567</div>
            <div style={{fontSize: 11, color: T.ink4}}>MSC Altair · CN-CAN → NG-LOS · 7 of 12 PLs</div>
          </div>
          <Icon name="chevdown" size={14} color={T.ink4} />
        </div>
      </Field>
    </div>

    <div style={{height: 16}} />
    <Banner variant="info" title="What happens next">
      Once you click Next, we'll generate a unique <Mono>PL-{`{date}`}-{`{seq}`}</Mono> reference for this packing list. You can add carton items, save as draft anytime, and submit for approval when complete.
    </Banner>

    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24, paddingTop: 20, borderTop: `1px solid ${T.line}`}}>
      <Button variant="ghost">Cancel</Button>
      <Button variant="primary" trailing="arrowright">Next: Add items</Button>
    </div>
  </Card>
);

const PLStep2 = () => (
  <>
    {/* Header context bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
          <Avatar size={32} name="Ngozi Okonkwo" color={T.copper} />
          <div>
            <div style={{fontSize: 13, fontWeight: 700, color: T.ink, lineHeight: 1.2}}>Ngozi Okonkwo</div>
            <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono}}>+234 801 234 5678</div>
          </div>
        </div>
        <span style={{color: T.lineStrong}}>·</span>
        <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
          <Icon name="container" size={14} color={T.info} />
          <div>
            <div style={{fontSize: 13, fontWeight: 700, color: T.ink, lineHeight: 1.2, fontFamily: T.mono}}>MSCU1234567</div>
            <div style={{fontSize: 11, color: T.ink4}}>MSC Altair · ETA 14 Aug</div>
          </div>
        </div>
        <span style={{color: T.lineStrong}}>·</span>
        <Mono color={T.ink3}>PL-20260728-008 (draft)</Mono>
        <span style={{flex: 1}} />
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px',
          background: T.warningSoft, color: T.warningStrong, borderRadius: 9999,
          fontSize: 11, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
        }}>
          <Icon name="refresh" size={11} stroke={2.5} /> Auto-saving
        </span>
      </div>
    </Card>

    {/* Items table */}
    <Card padding={0} style={{marginBottom: 16}}>
      <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <SectionHead title="Carton items" sub="Each row is one carton. CBM is auto-computed from L × W × H." />
        <div style={{display: 'flex', gap: 8}}>
          <Button variant="secondary" size="sm" icon="upload">Import CSV</Button>
          <Button variant="primary" size="sm" icon="plus">Add item</Button>
        </div>
      </div>
      <div style={{overflow: 'auto'}}>
        <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: T.body, fontSize: 12}}>
          <thead>
            <tr style={{background: T.muted, borderBottom: `1px solid ${T.line}`}}>
              <th style={{padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase'}}>Tag</th>
              <th style={{padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase', minWidth: 200}}>Description</th>
              <th style={{padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase'}}>Wt dispatch (kg)</th>
              <th style={{padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase'}}>Wt actual (kg)</th>
              <th style={{padding: '10px 14px', textAlign: 'center', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase'}}>L × W × H (cm)</th>
              <th style={{padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: T.green, letterSpacing: '0.08em', textTransform: 'uppercase'}}>CBM (auto)</th>
              <th style={{padding: '10px 14px', textAlign: 'right', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase'}}>Declared (USD)</th>
              <th style={{padding: '10px 14px', width: 36}}></th>
            </tr>
          </thead>
          <tbody>
            <PLItemRow tag="SHX-00001" desc="Electronics (mixed — phones, accessories)" wd="12.5" wa="12.8" dim={['40', '30', '25']} cbm="0.030" usd="380" />
            <PLItemRow tag="SHX-00002" desc="Clothing (women's apparel, assorted)" wd="8.2" wa="8.5" dim={['35', '30', '20']} cbm="0.021" usd="240" />
            <PLItemRow tag="SHX-00003" desc="Phone accessories (cables, cases)" wd="6.0" wa="6.2" dim={['30', '25', '24']} cbm="0.018" usd="180" />
            <PLItemRow tag="SHX-00004" desc="Spare parts (auto)" wd="9.0" wa="9.1" dim={['40', '30', '20']} cbm="0.024" usd="320" focused />
          </tbody>
          <tfoot>
            <tr style={{borderTop: `2px solid ${T.line}`, background: T.greenTint}}>
              <td style={{padding: '12px 14px', fontWeight: 700, fontSize: 12, color: T.ink}} colSpan={2}>Totals — 4 cartons</td>
              <td style={{padding: '12px 14px', fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: T.ink, textAlign: 'right'}}>35.7 kg</td>
              <td style={{padding: '12px 14px', fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: T.ink, textAlign: 'right'}}>36.6 kg</td>
              <td></td>
              <td style={{padding: '12px 14px', fontFamily: T.mono, fontSize: 13, fontWeight: 700, color: T.green, textAlign: 'right'}}>0.093</td>
              <td style={{padding: '12px 14px', fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: T.ink, textAlign: 'right'}}>$1,120</td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
      <div style={{padding: 14, borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'center'}}>
        <Button variant="ghost" icon="plus">Add another carton</Button>
      </div>
    </Card>

    {/* Live pricing card */}
    <Card style={{marginBottom: 16}}>
      <SectionHead title="Live pricing estimate" sub="Computed using current rates · final billing happens in Nigeria" />
      <div style={{height: 12}} />
      <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12}}>
        <PriceTile label="Total CBM" value="0.093" sub="auto-computed" />
        <PriceTile label="CBM rate" value="$48.00" sub="per cubic meter" />
        <PriceTile label="Shipping (USD)" value="$4.46" sub="0.093 × $48" />
        <PriceTile label="Shipping (NGN)" value="₦7,365" sub="× ₦1,650 FX" highlight />
      </div>
    </Card>

    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8}}>
      <Button variant="ghost" icon="arrowleft">Back: Details</Button>
      <div style={{display: 'flex', gap: 10}}>
        <Button variant="secondary">Save draft</Button>
        <Button variant="primary" trailing="arrowright">Next: Review</Button>
      </div>
    </div>
  </>
);

const PLItemRow = ({tag, desc, wd, wa, dim, cbm, usd, focused}) => (
  <tr style={{borderBottom: `1px solid ${T.line}`, background: focused ? T.greenTint : '#fff'}}>
    <td style={{padding: '10px 14px'}}><Mono color={T.ink}>{tag}</Mono></td>
    <td style={{padding: '10px 14px'}}>
      <div style={{
        height: 32, background: '#fff', border: `1px solid ${focused ? T.green : T.line}`, borderRadius: 6,
        display: 'flex', alignItems: 'center', padding: '0 10px', fontSize: 13, color: T.ink,
        boxShadow: focused ? `0 0 0 3px rgba(45,196,56,0.18)` : 'none',
      }}>{desc}</div>
    </td>
    <td style={{padding: '10px 14px'}}>
      <div style={{height: 32, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 6, display: 'flex', alignItems: 'center', padding: '0 10px', fontFamily: T.mono, fontSize: 12, color: T.ink, justifyContent: 'flex-end'}}>{wd}</div>
    </td>
    <td style={{padding: '10px 14px'}}>
      <div style={{height: 32, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 6, display: 'flex', alignItems: 'center', padding: '0 10px', fontFamily: T.mono, fontSize: 12, color: T.ink, justifyContent: 'flex-end'}}>{wa}</div>
    </td>
    <td style={{padding: '10px 14px'}}>
      <div style={{display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'center'}}>
        <DimInput value={dim[0]} />
        <span style={{color: T.ink4, fontSize: 11}}>×</span>
        <DimInput value={dim[1]} />
        <span style={{color: T.ink4, fontSize: 11}}>×</span>
        <DimInput value={dim[2]} />
      </div>
    </td>
    <td style={{padding: '10px 14px', textAlign: 'right'}}>
      <span style={{display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px', background: T.greenSoft, color: T.green, borderRadius: 6, fontFamily: T.mono, fontSize: 12, fontWeight: 700}}>
        {cbm}
      </span>
    </td>
    <td style={{padding: '10px 14px'}}>
      <div style={{height: 32, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 6, display: 'flex', alignItems: 'center', padding: '0 10px', fontFamily: T.mono, fontSize: 12, color: T.ink, justifyContent: 'flex-end'}}>${usd}</div>
    </td>
    <td style={{padding: '10px 14px', textAlign: 'center'}}>
      <button style={{background: 'transparent', border: 0, padding: 4, color: T.error, cursor: 'pointer', borderRadius: 4, display: 'inline-flex'}}>
        <Icon name="x" size={14} />
      </button>
    </td>
  </tr>
);

const DimInput = ({value}) => (
  <div style={{width: 44, height: 32, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: T.mono, fontSize: 12, color: T.ink}}>{value}</div>
);

const PriceTile = ({label, value, sub, highlight}) => (
  <div style={{padding: 14, background: highlight ? T.greenTint : T.muted, border: `1px solid ${highlight ? T.green + '55' : T.line}`, borderRadius: 8}}>
    <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}>{label}</div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: highlight ? T.greenDeep : T.ink, marginTop: 4, letterSpacing: '-0.01em'}}>{value}</div>
    <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{sub}</div>
  </div>
);

const PLStep3 = () => (
  <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 360px', gap: 20}}>
    <div>
      <Card style={{marginBottom: 16}}>
        <SectionHead title="Ready to submit" sub="Review the summary, then submit for Tenant Admin approval." />
        <div style={{height: 14}} />
        <Banner variant="success" title="All items look valid">
          4 cartons captured · all dimensions present · CBM totals computed · no missing fields.
        </Banner>
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px', borderBottom: `1px solid ${T.line}`}}>
          <SectionHead title="Document preview" sub="How this packing list will appear when printed" />
        </div>
        <div style={{padding: 24, background: T.muted}}>
          <div style={{background: '#fff', boxShadow: T.shadowRest, borderRadius: 8, padding: 24, maxWidth: 600, margin: '0 auto', fontFamily: T.body, fontSize: 11}}>
            {/* Doc header */}
            <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', paddingBottom: 14, borderBottom: `1px solid ${T.line}`, marginBottom: 14}}>
              <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
                <div style={{width: 40, height: 40, borderRadius: 8, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 16, fontFamily: T.display}}>AL</div>
                <div>
                  <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 13, color: T.ink}}>Acme Logistics Ltd</div>
                  <div style={{fontSize: 9, color: T.ink4, fontStyle: 'italic'}}>Trusted China-Nigeria cargo since 2019</div>
                </div>
              </div>
              <div style={{textAlign: 'right'}}>
                <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 13, letterSpacing: '0.04em', color: T.ink}}>PACKING LIST</div>
                <div style={{fontFamily: T.mono, fontSize: 9, color: T.ink3, marginTop: 2}}>PL-20260728-008</div>
              </div>
            </div>
            {/* Header info */}
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 10, marginBottom: 14}}>
              <div><div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 8}}>Customer</div><div style={{fontWeight: 700, marginTop: 2}}>Ngozi Okonkwo</div><div style={{fontFamily: T.mono, color: T.ink3}}>+234 801 234 5678</div></div>
              <div><div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', fontSize: 8}}>Container</div><div style={{fontFamily: T.mono, fontWeight: 700, marginTop: 2}}>MSCU1234567</div><div style={{color: T.ink3}}>MSC Altair · Voy 248E</div></div>
            </div>
            {/* Items */}
            <div className="sx-cols" style={{background: T.muted, padding: '5px 8px', display: 'grid', gridTemplateColumns: '60px 1fr 50px 60px 40px 50px', gap: 6, fontSize: 8, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em', borderRadius: 3}}>
              <span>Tag</span><span>Description</span><span style={{textAlign: 'right'}}>Wt (kg)</span><span style={{textAlign: 'right'}}>L×W×H</span><span style={{textAlign: 'right'}}>CBM</span><span style={{textAlign: 'right'}}>USD</span>
            </div>
            {[
              ['SHX-00001', 'Electronics (mixed)', '12.8', '40×30×25', '0.030', '$380'],
              ['SHX-00002', 'Clothing (assorted)', '8.5', '35×30×20', '0.021', '$240'],
              ['SHX-00003', 'Phone accessories', '6.2', '30×25×24', '0.018', '$180'],
              ['SHX-00004', 'Spare parts (auto)', '9.1', '40×30×20', '0.024', '$320'],
            ].map((r, i) => (
              <div key={i} className="sx-cols" style={{display: 'grid', gridTemplateColumns: '60px 1fr 50px 60px 40px 50px', gap: 6, fontSize: 9, padding: '4px 8px', borderBottom: `1px solid ${T.line}`}}>
                <span style={{fontFamily: T.mono}}>{r[0]}</span><span>{r[1]}</span>
                <span style={{textAlign: 'right', fontFamily: T.mono}}>{r[2]}</span>
                <span style={{textAlign: 'right', fontFamily: T.mono}}>{r[3]}</span>
                <span style={{textAlign: 'right', fontFamily: T.mono, color: T.green, fontWeight: 700}}>{r[4]}</span>
                <span style={{textAlign: 'right', fontFamily: T.mono}}>{r[5]}</span>
              </div>
            ))}
            <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, fontSize: 9.5, fontWeight: 700, marginTop: 6, paddingTop: 6, borderTop: `1px solid ${T.line}`}}>
              <span>4 cartons</span><span>·</span><span>36.6 kg</span><span>·</span><span style={{color: T.green}}>0.093 CBM</span>
            </div>
          </div>
        </div>
      </Card>

      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 20}}>
        <Button variant="ghost" icon="arrowleft">Back: Items</Button>
        <div style={{display: 'flex', gap: 10}}>
          <Button variant="secondary">Save as draft</Button>
          <Button variant="accent" icon="check">Submit for approval</Button>
        </div>
      </div>
    </div>

    {/* Summary sidebar */}
    <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
      <Card>
        <SectionHead title="Summary" />
        <div style={{height: 8}} />
        <Kvp label="Reference" value={<Mono>PL-20260728-008</Mono>} />
        <Kvp label="Customer" value="Ngozi Okonkwo" />
        <Kvp label="Container" value={<Mono>MSCU1234567</Mono>} />
        <Kvp label="Cartons" value={<Mono>4</Mono>} />
        <Kvp label="Total weight" value={<Mono>36.6 kg</Mono>} />
        <Kvp label="Total CBM" value={<Mono color={T.green}>0.093</Mono>} />
        <Kvp label="Declared value" value={<Mono>$1,120 USD</Mono>} divider={false} />
      </Card>

      <Card>
        <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8}}>
          <div style={{width: 36, height: 36, borderRadius: 10, background: T.warningSoft, color: T.warning, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
            <Icon name="clock" size={16} stroke={2} />
          </div>
          <div>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 13, color: T.ink}}>What happens after submit</div>
          </div>
        </div>
        <ol style={{margin: 0, padding: '0 0 0 20px', fontSize: 12, color: T.ink2, lineHeight: 1.7}}>
          <li>Amara Okafor (Tenant Admin) is notified to review.</li>
          <li>If approved, it gets attached to container MSCU1234567.</li>
          <li>If rejected, you'll see notes and can edit & resubmit.</li>
        </ol>
      </Card>
    </div>
  </div>
);

// ============================================================
// 5.5 — PACKING LIST DETAIL
// ============================================================
const PackingListDetail = ({state = 'approved'}) => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('pls')} user={chinaUser} />}
    topbar={<TopBar role="china" title="" breadcrumb={['Operations', 'Packing lists', 'PL-20260415-001']} user={chinaUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{width: 64, height: 64, borderRadius: 14, background: T.greenSoft, color: T.green, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="package" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>PL-20260415-001</h1>
            {state === 'approved' && <Badge variant="success">Approved</Badge>}
            {state === 'rejected' && <Badge variant="error">Rejected</Badge>}
            {state === 'pending' && <Badge variant="warning">Pending approval</Badge>}
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <span>Ngozi Okonkwo</span>
            <span style={{color: T.lineStrong}}>·</span>
            <Mono>MSCU1234567</Mono>
            <span style={{color: T.lineStrong}}>·</span>
            <span>4 cartons · 0.093 CBM</span>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Submitted 15 Apr 2026 by Kwame Asante</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="download">Export PDF</Button>
        <Button variant="secondary" icon="upload">Print</Button>
        {state === 'rejected' && <Button variant="primary" icon="edit">Edit &amp; resubmit</Button>}
        {state === 'pending' && <><Button variant="danger-outline" icon="x">Reject</Button><Button variant="success" icon="check">Approve</Button></>}
      </div>
    </div>

    {state === 'approved' && (
      <Banner variant="success" title="Approved by Amara Okafor on 16 Apr 2026 at 11:30">
        This packing list is locked. Cartons are attached to MSCU1234567. To make changes, contact Amara to revoke approval first.
      </Banner>
    )}
    {state === 'rejected' && (
      <Banner variant="error" title="Rejected by Amara Okafor on 16 Apr 2026 at 11:30">
        Comments: "Carton SHX-00003 dimensions don't match the photos uploaded. Re-measure and resubmit." Two carton items are flagged below.
      </Banner>
    )}
    <div style={{height: 20}} />

    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Carton items" sub="4 cartons · 36.6 kg · 0.093 CBM" />
      </div>
      <Table
        columns={[
          {title: 'Tag'},
          {title: 'Description'},
          {title: 'Weight (actual)', align: 'right'},
          {title: 'L × W × H (cm)', align: 'center'},
          {title: 'CBM', align: 'right'},
          {title: 'Declared', align: 'right'},
          state === 'rejected' && {title: 'Flag'},
        ].filter(Boolean)}
        rows={[
          {cells: [
            <Mono>SHX-00001</Mono>, <span style={{fontSize: 13, color: T.ink}}>Electronics (mixed)</span>,
            <Mono>12.8 kg</Mono>, <Mono>40 × 30 × 25</Mono>, <Mono color={T.green}>0.030</Mono>, <Mono>$380</Mono>,
            ...(state === 'rejected' ? [<span style={{fontSize: 12, color: T.ink4}}>OK</span>] : []),
          ]},
          {cells: [
            <Mono>SHX-00002</Mono>, <span style={{fontSize: 13, color: T.ink}}>Clothing (assorted)</span>,
            <Mono>8.5 kg</Mono>, <Mono>35 × 30 × 20</Mono>, <Mono color={T.green}>0.021</Mono>, <Mono>$240</Mono>,
            ...(state === 'rejected' ? [<span style={{fontSize: 12, color: T.ink4}}>OK</span>] : []),
          ]},
          {cells: [
            <Mono>SHX-00003</Mono>, <span style={{fontSize: 13, color: T.ink}}>Phone accessories</span>,
            <Mono>6.2 kg</Mono>, <Mono>30 × 25 × 24</Mono>, <Mono color={T.green}>0.018</Mono>, <Mono>$180</Mono>,
            ...(state === 'rejected' ? [<Badge variant="error" size="sm">Re-measure</Badge>] : []),
          ], suspended: state === 'rejected'},
          {cells: [
            <Mono>SHX-00004</Mono>, <span style={{fontSize: 13, color: T.ink}}>Spare parts (auto)</span>,
            <Mono>9.1 kg</Mono>, <Mono>40 × 30 × 20</Mono>, <Mono color={T.green}>0.024</Mono>, <Mono>$320</Mono>,
            ...(state === 'rejected' ? [<span style={{fontSize: 12, color: T.ink4}}>OK</span>] : []),
          ]},
        ]}
      />
      <div style={{padding: '14px 20px', borderTop: `2px solid ${T.line}`, background: T.greenTint, display: 'flex', justifyContent: 'flex-end', gap: 24, fontSize: 13, fontWeight: 700}}>
        <span>4 cartons</span>
        <span><span style={{color: T.ink4, fontWeight: 500}}>Weight:</span> <Mono>36.6 kg</Mono></span>
        <span><span style={{color: T.ink4, fontWeight: 500}}>CBM:</span> <Mono color={T.green}>0.093</Mono></span>
        <span><span style={{color: T.ink4, fontWeight: 500}}>Declared:</span> <Mono>$1,120</Mono></span>
      </div>
    </Card>
  </PageShell>
);

// ============================================================
// 5.6 — PACKING LIST LIST (with bulk actions)
// ============================================================
const PackingListList = ({withBulk} = {}) => (
  <PageShell
    sidebar={<Sidebar role="china" brand={tenantBrand} items={chinaSidebarItems('pls')} user={chinaUser} />}
    topbar={<TopBar role="china" title="Packing lists" breadcrumb={['Operations', 'Packing lists']} user={chinaUser} actions={
      <Button variant="primary" icon="plus">Create packing list</Button>
    } />}
  >
    {/* Bulk action bar */}
    {withBulk && (
      <Card padding={12} style={{
        marginBottom: 16, background: T.greenForest, color: '#fff', border: 'none',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16,
      }}>
        <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
          <Check checked />
          <span style={{fontSize: 14, fontWeight: 600, color: '#fff'}}>4 packing lists selected</span>
          <span style={{fontSize: 12, color: 'rgba(255,255,255,0.6)'}}>· 64 cartons · 5.94 CBM total</span>
        </div>
        <div style={{display: 'flex', gap: 8}}>
          <button style={{height: 32, padding: '0 14px', background: 'rgba(255,255,255,0.08)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 8, fontFamily: T.body, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Clear</button>
          <Button variant="danger-outline" size="sm" icon="x">Bulk reject</Button>
          <button style={{height: 32, padding: '0 14px', background: T.success, color: '#fff', border: 'none', borderRadius: 8, fontFamily: T.body, fontWeight: 600, fontSize: 13, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 6}}>
            <Icon name="check" size={13} stroke={2.5} /> Bulk approve · 4
          </button>
        </div>
      </Card>
    )}

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>48</span></Chip>
          <Chip count={4}>Draft</Chip>
          <Chip count={6}>Pending approval</Chip>
          <Chip count={36}>Approved</Chip>
          <Chip count={2}>Rejected</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Reference, customer name, container…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="filter">More filters</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Ref #', sortable: true},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Cartons', align: 'right'},
          {title: 'CBM', align: 'right'},
          {title: 'Status'},
          {title: 'Submitted', sortable: true},
          {title: '', width: 40},
        ]}
        rows={[
          {selected: withBulk, cells: [<Mono>PL-20260728-001</Mono>, <UserCell name="Emeka Eze" email="22 cartons" />, <Mono>MSCU1234567</Mono>, <Mono>22</Mono>, <Mono>2.14</Mono>, <Badge variant="warning">Pending</Badge>, <span style={{fontSize: 12, color: T.ink3}}>28 Jul, 14:22</span>, <ViewLink />]},
          {selected: withBulk, cells: [<Mono>PL-20260728-002</Mono>, <UserCell name="Ngozi Okonkwo" email="18 cartons" />, <Mono>MSCU1234567</Mono>, <Mono>18</Mono>, <Mono>1.84</Mono>, <Badge variant="warning">Pending</Badge>, <span style={{fontSize: 12, color: T.ink3}}>28 Jul, 14:08</span>, <ViewLink />]},
          {selected: withBulk, cells: [<Mono>PL-20260727-003</Mono>, <UserCell name="Funmilayo Adeyemi" email="14 cartons" />, <Mono>MSCU1234567</Mono>, <Mono>14</Mono>, <Mono>1.42</Mono>, <Badge variant="warning">Pending</Badge>, <span style={{fontSize: 12, color: T.ink3}}>27 Jul, 16:30</span>, <ViewLink />]},
          {selected: withBulk, cells: [<Mono>PL-20260727-004</Mono>, <UserCell name="Ibrahim Musa" email="10 cartons" />, <Mono>MSCU1234567</Mono>, <Mono>10</Mono>, <Mono>0.54</Mono>, <Badge variant="warning">Pending</Badge>, <span style={{fontSize: 12, color: T.ink3}}>27 Jul, 11:14</span>, <ViewLink />]},
          {cells: [<Mono>PL-20260726-005</Mono>, <UserCell name="Adaeze Nwosu" email="8 cartons" />, <Mono>HLBU9384712</Mono>, <Mono>8</Mono>, <Mono>0.72</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>26 Jul, 10:08</span>, <ViewLink />]},
          {cells: [<Mono>PL-20260725-006</Mono>, <UserCell name="Bola Adesina" email="6 cartons" />, <Mono>HLBU9384712</Mono>, <Mono>6</Mono>, <Mono>0.48</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>25 Jul, 14:00</span>, <ViewLink />]},
          {cells: [<Mono>PL-20260724-007</Mono>, <UserCell name="Chukwuemeka Nwogu" email="4 cartons" />, <Mono>COSU7194820</Mono>, <Mono>4</Mono>, <Mono>0.18</Mono>, <Badge variant="error">Rejected</Badge>, <span style={{fontSize: 12, color: T.ink3}}>24 Jul, 09:42</span>, <ViewLink />], suspended: true},
          {cells: [<Mono>PL-20260724-008</Mono>, <UserCell name="Olufemi Adetunji" email="12 cartons" />, <Mono>COSU7194820</Mono>, <Mono>12</Mono>, <Mono>1.04</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>24 Jul, 11:18</span>, <ViewLink />]},
          {cells: [<Mono>PL-20260723-009</Mono>, <UserCell name="Aisha Lawal" email="22 cartons" />, <Mono>COSU7194820</Mono>, <Mono>22</Mono>, <Mono>1.88</Mono>, <Badge variant="success">Approved</Badge>, <span style={{fontSize: 12, color: T.ink3}}>23 Jul, 16:42</span>, <ViewLink />]},
          {cells: [<Mono>PL-20260722-010</Mono>, <UserCell name="Yusuf Garba" email="(draft)" />, <Mono color={T.ink4}>—</Mono>, <Mono color={T.ink4}>0</Mono>, <Mono color={T.ink4}>—</Mono>, <Badge variant="neutral">Draft</Badge>, <span style={{fontSize: 12, color: T.ink3}}>22 Jul, 18:00</span>, <ViewLink />]},
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

Object.assign(window, {
  ContainerList, CreateContainer, ContainerDetail, CreatePackingList,
  PackingListDetail, PackingListList, ContainerDocs, UploadDocumentModal,
});
