// ============================================================
// Shipx — Documents & Reports (Section 14, main file)
// 14.3 Bulk Import wizard · 14.7 Platform Audit Log
// 14.8 Tenant Reports · 14.9 Notification Delivery Log
// 14.10 Print layouts (Packing List + Release Note)
// ============================================================

// ---- local helper copies (avoid cross-file load-order coupling) ----
const ModalOverlay = ({children}) => (
  <div style={{position: 'absolute', inset: 0, background: 'rgba(11,47,13,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 32}}>{children}</div>
);

const UserCell = ({name, email}) => (
  <div style={{display: 'flex', gap: 10, alignItems: 'center'}}>
    <Avatar size={28} name={name} />
    <div style={{minWidth: 0}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink, lineHeight: 1.2}}>{name}</div>
      {email && <div style={{fontSize: 11, color: T.ink4, lineHeight: 1.3}}>{email}</div>}
    </div>
  </div>
);

const Kvp = ({label, value, divider = true}) => (
  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: divider ? `1px dashed ${T.line}` : 'none', gap: 16}}>
    <span style={{fontSize: 12, color: T.ink4, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.06em'}}>{label}</span>
    <span style={{fontSize: 13, color: T.ink2, textAlign: 'right'}}>{value}</span>
  </div>
);

const SummaryTile = ({label, value, sub, color}) => (
  <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8}}>
    <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase'}}>{label}</div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: color || T.ink, marginTop: 4, letterSpacing: '-0.01em', lineHeight: 1.1}}>{value}</div>
    <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{sub}</div>
  </div>
);

const TablePagination = () => (
  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderTop: `1px solid ${T.line}`, fontSize: 13, color: T.ink3}}>
    <div>Showing <strong style={{color: T.ink}}>1–10</strong> of <strong style={{color: T.ink}}>2,341</strong></div>
    <div style={{display: 'flex', gap: 4}}>
      <button style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, color: T.ink4, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Icon name="chevleft" size={14} /></button>
      <button style={{width: 30, height: 30, border: `1px solid ${T.green}`, background: T.greenSoft, color: T.greenDeep, borderRadius: 6, fontWeight: 700, fontSize: 13, cursor: 'pointer'}}>1</button>
      <button style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, color: T.ink, fontWeight: 600, cursor: 'pointer', fontSize: 13}}>2</button>
      <button style={{width: 30, height: 30, border: `1px solid ${T.line}`, background: '#fff', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink}}><Icon name="chevright" size={14} /></button>
    </div>
  </div>
);

// ---- sidebar item helpers (local copies to avoid load-order coupling) ----
const platformNav = (active) => [
  {group: 'Overview', items: [{icon: 'grid', label: 'Dashboard'}]},
  {group: 'Tenants', items: [{icon: 'building', label: 'All Tenants', count: '12'}, {icon: 'plus', label: 'Onboard Tenant'}]},
  {group: 'Platform', items: [{icon: 'settings', label: 'Settings'}, {icon: 'log', label: 'Audit Log', active: active === 'audit'}]},
];
const platformU = {name: 'Alex Ifesinachi', role: 'Platform Admin'};

const adminNav = (active) => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard'},
    {icon: 'chart', label: 'Reports', active: active === 'reports'},
  ]},
  {group: 'Operations', items: [
    {icon: 'users', label: 'Customers', count: '142'},
    {icon: 'user', label: 'Staff users', count: '24'},
  ]},
  {group: 'Configuration', items: [
    {icon: 'settings', label: 'Company settings'},
    {icon: 'bell', label: 'Notifications', active: active === 'notiflog'},
  ]},
];
const adminU = {name: 'Amara Okafor', role: 'Tenant Admin'};

const chinaNav = (active) => [
  {group: 'Operations', items: [
    {icon: 'container', label: 'Containers'},
    {icon: 'plus', label: 'Create container'},
  ]},
  {group: 'Packing lists', items: [
    {icon: 'package', label: 'All packing lists', active: active === 'pls'},
    {icon: 'plus', label: 'Create packing list'},
    {icon: 'upload', label: 'Import from Excel', active: active === 'import'},
  ]},
];
const chinaU = {name: 'Kwame Asante', role: 'China Office Staff'};

// ============================================================
// 14.3 — BULK IMPORT WIZARD (China Office)
// ============================================================
const BulkImport = ({step = 1}) => (
  <PageShell
    sidebar={<Sidebar role="china" brand={<TenantBrand name="Acme Logistics" logo="AL" />} items={chinaNav('import')} user={chinaU} />}
    topbar={<TopBar role="china" title="" breadcrumb={['Packing lists', 'Import from Excel']} user={chinaU} />}
  >
    <div style={{maxWidth: 1100, margin: '0 auto'}}>
      <PageHeader
        eyebrow="China-side · bulk entry"
        title="Import packing lists from Excel"
        subtitle="Upload a filled ShipX template to create one packing list per customer in a single pass. Each row is one carton."
      />
      <ImportSteps current={step} />
      <div style={{height: 20}} />
      {step === 1 && <ImportStep1 />}
      {step === 2 && <ImportStep2 />}
      {step === 3 && <ImportStep3 />}
      {step === 4 && <ImportSuccess />}
    </div>
  </PageShell>
);

const ImportSteps = ({current}) => {
  const steps = [
    {n: 1, label: 'Upload file', sub: 'Pick container + .xlsx'},
    {n: 2, label: 'Review & validate', sub: 'Fix any errors'},
    {n: 3, label: 'Confirm import', sub: 'Create packing lists'},
  ];
  return (
    <Card padding={0}>
      <div style={{display: 'flex', padding: 8}}>
        {steps.map((s, i) => {
          const done = s.n < current;
          const isCurrent = s.n === current || (current === 4 && s.n === 3);
          return (
            <React.Fragment key={s.n}>
              <div style={{flex: 1, display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', borderRadius: 10, background: isCurrent ? T.greenTint : 'transparent'}}>
                <div style={{
                  width: 36, height: 36, borderRadius: '50%',
                  background: done ? T.success : isCurrent ? T.green : T.muted,
                  border: `2px solid ${done ? T.success : isCurrent ? T.green : T.lineStrong}`,
                  color: done || isCurrent ? '#fff' : T.ink4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontWeight: 700, fontSize: 14, flexShrink: 0,
                  boxShadow: isCurrent ? `0 0 0 5px ${T.green}22` : 'none',
                }}>{done ? <Icon name="check" size={16} stroke={3} /> : s.n}</div>
                <div>
                  <div style={{fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.ink4}}>Step {s.n}</div>
                  <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: isCurrent || done ? T.ink : T.ink3, marginTop: 1}}>{s.label}</div>
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

const ImportStep1 = () => (
  <Card padding={32}>
    <SectionHead title="Upload your file" sub="Which container are these packing lists for?" />
    <div style={{height: 16}} />
    <Field label="Container" required>
      <div style={{height: 48, background: '#fff', border: `2px solid ${T.green}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 12, boxShadow: `0 0 0 3px rgba(45,196,56,0.15)`, cursor: 'pointer'}}>
        <div style={{width: 32, height: 32, borderRadius: 8, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="container" size={16} />
        </div>
        <div style={{flex: 1, minWidth: 0}}>
          <div style={{fontFamily: T.mono, fontSize: 14, fontWeight: 700, color: T.ink, lineHeight: 1.2}}>MSCU1234567</div>
          <div style={{fontSize: 11, color: T.ink4}}>MSC Altair · Voy 248E · Active · 7 of 12 PLs</div>
        </div>
        <Icon name="chevdown" size={14} color={T.ink4} />
      </div>
    </Field>

    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
        <div style={{width: 36, height: 36, borderRadius: 8, background: T.successSoft, color: T.success, display: 'flex', alignItems: 'center', justifyContent: 'center'}}><Icon name="file" size={16} /></div>
        <div>
          <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Don't have the template?</div>
          <div style={{fontSize: 12, color: T.ink4}}>Download the ShipX Excel template with the right columns + validation.</div>
        </div>
      </div>
      <Button variant="secondary" size="sm" icon="download">Download template</Button>
    </div>

    {/* Upload zone */}
    <div style={{border: `2px dashed ${T.green}55`, borderRadius: 12, padding: '48px 20px', background: T.greenTint, textAlign: 'center', marginBottom: 16}}>
      <div style={{width: 56, height: 56, margin: '0 auto 14px', borderRadius: 14, background: T.green, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <Icon name="upload" size={24} stroke={2.5} />
      </div>
      <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 17, color: T.ink}}>Drag &amp; drop your .xlsx file here</div>
      <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>or click to browse · .xlsx only · max 10 MB</div>
    </div>

    {/* Selected file */}
    <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: 14, background: '#fff', border: `1px solid ${T.success}55`, borderRadius: 10}}>
      <div style={{width: 40, height: 40, borderRadius: 8, background: T.successSoft, color: T.success, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}><Icon name="file" size={18} /></div>
      <div style={{flex: 1}}>
        <div style={{fontSize: 14, fontWeight: 600, color: T.ink}}>july-batch-mscu1234567.xlsx</div>
        <div style={{fontSize: 12, color: T.ink4}}>248 KB · 47 rows detected</div>
      </div>
      <Icon name="check" size={18} color={T.success} stroke={2.5} />
      <button style={{background: 'transparent', border: 0, color: T.error, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Remove</button>
    </div>

    <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 24}}>
      <Button variant="ghost">Cancel</Button>
      <Button variant="primary" trailing="arrowright">Upload &amp; parse</Button>
    </div>
  </Card>
);

const ImportStep2 = () => (
  <>
    {/* Summary bar */}
    <Card padding={16} style={{marginBottom: 16, background: T.warningSoft, borderColor: T.warning + '55', borderLeft: `4px solid ${T.warning}`}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <Icon name="warn" size={18} color={T.warning} stroke={2.5} />
        <span style={{fontSize: 14, fontWeight: 700, color: T.warningStrong}}>47 rows parsed · 3 customers · 4 errors</span>
        <span style={{fontSize: 13, color: T.ink3}}>— fix errors below or skip invalid rows before importing.</span>
        <div style={{flex: 1}} />
        <label style={{display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.ink2, fontWeight: 500, cursor: 'pointer'}}>
          <Check checked /> Skip rows with errors, import 43 valid rows
        </label>
      </div>
    </Card>

    <Card padding={0} style={{marginBottom: 16}}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Preview &amp; validate" sub="Edit cells inline, or fix in the file and re-upload" />
      </div>
      <div style={{overflowX: 'auto'}}>
        <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: T.body, fontSize: 12}}>
          <thead>
            <tr style={{background: T.muted, borderBottom: `1px solid ${T.line}`}}>
              {['Tag', 'Customer', 'Description', 'Wt dispatch', 'Wt actual', 'L×W×H', 'CBM', 'Received', 'Status'].map(h => (
                <th key={h} style={{padding: '10px 14px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: T.ink3, letterSpacing: '0.08em', textTransform: 'uppercase', whiteSpace: 'nowrap'}}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <ImportRow tag="SHX-00001" cust="Ngozi Okonkwo" desc="Electronics (mixed)" wd="12.5" wa="12.8" dim="40×30×25" cbm="0.030" date="15 Apr" status="ok" />
            <ImportRow tag="SHX-00002" cust="Ngozi Okonkwo" desc="Clothing (assorted)" wd="8.2" wa="—" dim="35×30×20" cbm="—" date="15 Apr" status="warn" note="Missing actual weight" />
            <ImportRow tag="SHX-00003" cust="Ngozi Okonkwo" desc="Phone accessories" wd="6.0" wa="6.2" dim="30×25×24" cbm="0.018" date="15 Apr" status="ok" />
            <ImportRow tag="—" cust="Emeka Ezeh" desc="Phone accessories" wd="—" wa="—" dim="—" cbm="—" date="—" status="error" note="Customer not found — 'Emeka Ezeh' (check spelling)" />
            <ImportRow tag="SHX-00005" cust="Adaeze Nwosu" desc="Cosmetics" wd="4.2" wa="4.4" dim="25×20×15" cbm="0.008" date="15 Apr" status="ok" />
            <ImportRow tag="SHX-00006" cust="Adaeze Nwosu" desc="Shoes" wd="9.8" wa="10.1" dim="45×30×25" cbm="0.034" date="32 Apr" status="error" note="Invalid date — '32 Apr' is not a real date" />
            <ImportRow tag="SHX-00007" cust="Chukwuemeka Nwogu" desc="Auto parts" wd="22.0" wa="22.4" dim="60×40×30" cbm="0.072" date="15 Apr" status="ok" />
          </tbody>
        </table>
      </div>
    </Card>

    {/* Error panel */}
    <Card padding={0} style={{marginBottom: 16}}>
      <div style={{padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', borderBottom: `1px solid ${T.line}`}}>
        <Icon name="chevdown" size={14} color={T.error} />
        <span style={{fontSize: 14, fontWeight: 700, color: T.error}}>4 errors found</span>
        <span style={{fontSize: 12, color: T.ink4}}>· these rows can't be imported until fixed</span>
      </div>
      <div style={{padding: '12px 20px'}}>
        {[
          'Row 4: Customer not found in system — "Emeka Ezeh" (did you mean "Emeka Eze"?)',
          'Row 6: Received date is invalid — "32 Apr 2026"',
          'Row 19: CBM mismatch — provided 0.045 but L×W×H computes to 0.038',
          'Row 33: Carton tag SHX-00033 already exists on another packing list',
        ].map((e, i) => (
          <div key={i} style={{display: 'flex', gap: 10, padding: '8px 0', borderBottom: i < 3 ? `1px dashed ${T.line}` : 'none', fontSize: 13, color: T.ink2}}>
            <Icon name="x" size={14} color={T.error} stroke={2.5} />
            {e}
          </div>
        ))}
        <div style={{marginTop: 10}}>
          <a style={{color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Fix in file &amp; re-upload →</a>
        </div>
      </div>
    </Card>

    <div style={{display: 'flex', justifyContent: 'space-between'}}>
      <Button variant="ghost" icon="arrowleft">Back to upload</Button>
      <Button variant="primary" trailing="arrowright">Continue · import 43 valid rows</Button>
    </div>
  </>
);

const ImportRow = ({tag, cust, desc, wd, wa, dim, cbm, date, status, note}) => {
  const bg = status === 'error' ? T.errorSoft + '66' : status === 'warn' ? T.warningSoft + '66' : '#fff';
  const statusCell = status === 'ok' ?
    <Icon name="check" size={14} color={T.success} stroke={2.5} /> :
    status === 'warn' ?
    <span style={{display: 'inline-flex', alignItems: 'center', gap: 4, color: T.warningStrong, fontSize: 11, fontWeight: 600}}><Icon name="warn" size={12} stroke={2.5} />{note}</span> :
    <span style={{display: 'inline-flex', alignItems: 'center', gap: 4, color: T.errorStrong, fontSize: 11, fontWeight: 600}}><Icon name="x" size={12} stroke={2.5} />{note}</span>;
  return (
    <tr style={{background: bg, borderBottom: `1px solid ${T.line}`}}>
      <td style={{padding: '10px 14px'}}><Mono color={tag === '—' ? T.ink4 : T.ink}>{tag}</Mono></td>
      <td style={{padding: '10px 14px', fontSize: 13, color: cust.includes('Ezeh') ? T.error : T.ink, fontWeight: cust.includes('Ezeh') ? 600 : 400}}>{cust}</td>
      <td style={{padding: '10px 14px', fontSize: 13, color: T.ink2}}>{desc}</td>
      <td style={{padding: '10px 14px'}}><Mono color={wd === '—' ? T.ink4 : T.ink2}>{wd}</Mono></td>
      <td style={{padding: '10px 14px'}}><Mono color={wa === '—' ? T.error : T.ink2}>{wa}</Mono></td>
      <td style={{padding: '10px 14px'}}><Mono color={dim === '—' ? T.ink4 : T.ink2}>{dim}</Mono></td>
      <td style={{padding: '10px 14px'}}><Mono color={cbm === '—' ? T.ink4 : T.green}>{cbm}</Mono></td>
      <td style={{padding: '10px 14px'}}><Mono color={date === '—' || date === '32 Apr' ? T.error : T.ink2}>{date}</Mono></td>
      <td style={{padding: '10px 14px', whiteSpace: 'nowrap'}}>{statusCell}</td>
    </tr>
  );
};

const ImportStep3 = () => (
  <>
    <Card style={{marginBottom: 16}}>
      <SectionHead title="Confirm import" sub="Review what will be created. Each customer gets one new packing list." />
      <div style={{height: 16}} />
      <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 16}}>
        <SummaryTile label="Container" value="MSCU…" sub="MSC Altair" />
        <SummaryTile label="Customers" value="3" sub="distinct shippers" />
        <SummaryTile label="Packing lists" value="3" sub="one per customer" color={T.green} />
        <SummaryTile label="Total cartons" value="43" sub="2.35 CBM total" />
      </div>
      <Banner variant="info" title="What happens on import">
        3 new packing lists are created in <strong>Draft</strong> status. Review and submit each for approval afterward. 4 rows with errors were skipped.
      </Banner>
    </Card>

    <Card padding={0} style={{marginBottom: 16}}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Per-customer summary" />
      </div>
      <Table
        columns={[{title: 'Customer'}, {title: 'Cartons', align: 'right'}, {title: 'Total CBM', align: 'right'}, {title: 'Total weight', align: 'right'}, {title: 'Result'}]}
        rows={[
          {cells: [<UserCell name="Ngozi Okonkwo" email="+234 801 234 5678" />, <Mono>18</Mono>, <Mono>0.89</Mono>, <Mono>142 kg</Mono>, <Badge variant="info" size="sm">Will create PL</Badge>]},
          {cells: [<UserCell name="Adaeze Nwosu" email="+234 802 415 0922" />, <Mono>13</Mono>, <Mono>0.72</Mono>, <Mono>98 kg</Mono>, <Badge variant="info" size="sm">Will create PL</Badge>]},
          {cells: [<UserCell name="Chukwuemeka Nwogu" email="+234 805 219 3382" />, <Mono>12</Mono>, <Mono>0.74</Mono>, <Mono>118 kg</Mono>, <Badge variant="info" size="sm">Will create PL</Badge>]},
        ]}
      />
    </Card>

    <div style={{display: 'flex', justifyContent: 'space-between'}}>
      <Button variant="ghost" icon="arrowleft">Back</Button>
      <Button variant="accent" icon="check">Confirm &amp; import 3 packing lists</Button>
    </div>
  </>
);

const ImportSuccess = () => (
  <Card padding={48} style={{textAlign: 'center'}}>
    <div style={{width: 84, height: 84, borderRadius: '50%', background: T.successSoft, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 20}}>
      <Icon name="check" size={44} color={T.success} stroke={2.5} />
    </div>
    <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 24, margin: '0 0 6px', letterSpacing: '-0.015em'}}>3 packing lists imported.</h2>
    <p style={{fontSize: 14, color: T.ink3, margin: '0 0 24px'}}>They're now in <strong style={{color: T.ink}}>Draft</strong> status on container MSCU1234567 and need to be submitted for approval.</p>
    <div style={{display: 'flex', gap: 12, justifyContent: 'center'}}>
      <Button variant="secondary" icon="upload">Import another file</Button>
      <Button variant="primary" trailing="arrowright">View packing lists</Button>
    </div>
  </Card>
);

// ============================================================
// 14.7 — PLATFORM AUDIT LOG
// ============================================================
const PlatformAuditLog = () => (
  <PageShell
    sidebar={<Sidebar role="platform" items={platformNav('audit')} user={platformU} />}
    topbar={<TopBar role="platform" title="Platform audit log" breadcrumb={['Platform', 'Audit log']} user={platformU} actions={
      <Button variant="secondary" icon="download">Export CSV</Button>
    } />}
  >
    {/* Filter bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap'}}>
        <FilterSelect label="Tenant" value="All tenants" />
        <FilterSelect label="Entity type" value="All entities" />
        <FilterSelect label="Action" value="All actions" />
        <div style={{flex: 1, minWidth: 200}}>
          <label style={{display: 'block', fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6}}>Actor</label>
          <div style={{position: 'relative', height: 38, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Search by user name or ID…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <FilterSelect label="Date range" value="Last 7 days" icon="calendar" />
        <Button variant="primary">Apply</Button>
      </div>
    </Card>

    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12}}>
      <span style={{fontSize: 13, color: T.ink3}}>Showing <strong style={{color: T.ink}}>1–8</strong> of <strong style={{color: T.ink}}>2,341</strong> events matching filters</span>
    </div>

    <Card padding={0}>
      <Table
        dense
        columns={[
          {title: 'Timestamp'},
          {title: 'Tenant'},
          {title: 'Entity'},
          {title: 'Action'},
          {title: 'Actor'},
          {title: 'Before → After'},
          {title: '', width: 40},
        ]}
        rows={[
          auditRow({ts: '15 Apr 14:32:01', tenant: 'Acme Logistics', entity: 'billing', id: 'BL-001…', action: 'STATUS_CHANGE', av: 'info', actor: 'Amara Okafor', role: 'Nigeria Office', diff: <>status: <span style={{color: T.error, textDecoration: 'line-through'}}>unpaid</span> → <span style={{color: T.success, fontWeight: 600}}>paid</span></>, expanded: true}),
          auditRow({ts: '15 Apr 14:29:14', tenant: 'StarShip Cargo', entity: 'tenant', id: 'tnt_8a…', action: 'SUSPEND', av: 'error', actor: 'Alex Ifesinachi', role: 'Platform Admin', diff: <>status: <span style={{color: T.error, textDecoration: 'line-through'}}>active</span> → <span style={{color: T.warningStrong, fontWeight: 600}}>suspended</span></>}),
          auditRow({ts: '15 Apr 12:08:42', tenant: 'Acme Logistics', entity: 'packing_list', id: 'PL-148…', action: 'CREATE', av: 'success', actor: 'Kwame Asante', role: 'China Office', diff: '+ 14 cartons · 0.84 CBM'}),
          auditRow({ts: '15 Apr 10:44:09', tenant: 'Eze Freight', entity: 'customer', id: 'cus_8…', action: 'ANONYMISE', av: 'purple', actor: 'Ngozi Eze', role: 'Tenant Admin', diff: 'PII scrubbed · records retained'}),
          auditRow({ts: '14 Apr 18:30:55', tenant: 'Acme Logistics', entity: 'tenant', id: 'tnt_2b…', action: 'UPDATE', av: 'warning', actor: 'Amara Okafor', role: 'Tenant Admin', diff: <>dollar_rate: <span style={{color: T.error, textDecoration: 'line-through'}}>1620</span> → <span style={{color: T.success, fontWeight: 600}}>1650</span></>}),
          auditRow({ts: '14 Apr 16:12:33', tenant: 'StarShip Cargo', entity: 'release_note', id: 'RN-029…', action: 'CREATE', av: 'success', actor: 'Bayo Adekola', role: 'Nigeria Office', diff: '4 cartons · ₦49,352 settled'}),
          auditRow({ts: '14 Apr 09:08:17', tenant: 'Lion Freight', entity: 'tenant_user', id: 'usr_4f…', action: 'CREATE', av: 'success', actor: 'Adaeze Eze', role: 'Tenant Admin', diff: '+ chinedu@… · Nigeria Office'}),
          auditRow({ts: '13 Apr 22:01:48', tenant: 'Naija Cargo', entity: 'refund', id: 'RF-014…', action: 'DELETE', av: 'error', actor: 'Emeka Nwogu', role: 'Tenant Admin', diff: 'Refund request withdrawn'}),
        ]}
      />
      {/* Expanded JSON diff row */}
      <div style={{padding: '16px 20px', background: T.muted, borderTop: `1px solid ${T.line}`}}>
        <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Expanded · BL-001 STATUS_CHANGE</div>
        <div style={{fontFamily: T.mono, fontSize: 12, lineHeight: 1.7, background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8, padding: 14}}>
          <div style={{color: T.ink4}}>Before:</div>
          <div style={{color: T.errorStrong, background: T.errorSoft + '66', padding: '2px 8px', borderRadius: 4, margin: '2px 0'}}>{'{ "status": "unpaid", "total_paid_ngn": 0 }'}</div>
          <div style={{color: T.ink4, marginTop: 6}}>After:</div>
          <div style={{color: T.successStrong, background: T.successSoft + '66', padding: '2px 8px', borderRadius: 4, margin: '2px 0'}}>{'{ "status": "paid", "total_paid_ngn": 49352 }'}</div>
        </div>
      </div>
      <TablePagination />
    </Card>
  </PageShell>
);

const FilterSelect = ({label, value, icon}) => (
  <div>
    <label style={{display: 'block', fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6}}>{label}</label>
    <div style={{height: 38, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8, cursor: 'pointer', minWidth: 140}}>
      {icon && <Icon name={icon} size={13} color={T.ink4} />}
      <span style={{flex: 1, fontSize: 13, color: T.ink, whiteSpace: 'nowrap'}}>{value}</span>
      <Icon name="chevdown" size={13} color={T.ink4} />
    </div>
  </div>
);

const auditRow = ({ts, tenant, entity, id, action, av, actor, role, diff, expanded}) => ({
  cells: [
    <Mono color={T.ink2}>{ts}</Mono>,
    <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
      <div style={{width: 20, height: 20, borderRadius: 5, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 9, fontFamily: T.display}}>{tenant.split(' ').map(w => w[0]).slice(0,2).join('')}</div>
      <span style={{fontSize: 12, color: T.ink2, fontWeight: 500, whiteSpace: 'nowrap'}}>{tenant}</span>
    </div>,
    <div><span style={{fontSize: 12, color: T.ink2, fontWeight: 600}}>{entity}</span><div style={{fontFamily: T.mono, fontSize: 10, color: T.ink4}}>{id}</div></div>,
    <Badge variant={av} size="sm">{action}</Badge>,
    <UserCell name={actor} email={role} />,
    <span style={{fontSize: 12, color: T.ink3}}>{diff}</span>,
    <Icon name={expanded ? 'chevup' : 'chevdown'} size={14} color={T.ink4} />,
  ],
});

// ============================================================
// 14.10 — TENANT REPORTS
// ============================================================
const TenantReports = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={<TenantBrand name="Acme Logistics" logo="AL" />} items={adminNav('reports')} user={adminU} />}
    topbar={<TopBar role="admin" title="Reports &amp; analytics" breadcrumb={['Admin', 'Reports']} user={adminU} actions={
      <>
        <Button variant="secondary" trailing="chevdown">Last 3 months</Button>
        <Button variant="secondary" icon="download">Export</Button>
      </>
    } />}
  >
    {/* Section A — Operational overview */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Containers processed" value="14" trend="+3" trendDir="up" sublabel="vs last period" accent={<Icon name="container" size={15} stroke={2.2} />} />
      <StatCard label="Total revenue" value="₦4.23" suffix="M" trend="+12%" trendDir="up" sublabel="collected this period" accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Active customers" value="89" trend="+7" trendDir="up" sublabel="new this period" accent={<Icon name="users" size={15} stroke={2.2} />} />
      <StatCard label="Avg days to pickup" value="4.2" suffix="days" trend="−0.8d" trendDir="down" sublabel="faster vs last" accent={<Icon name="clock" size={15} stroke={2.2} />} />
    </div>

    {/* Section B — Container pipeline chart */}
    <Card style={{marginBottom: 24}}>
      <SectionHead title="Container pipeline" sub="Containers by status, per week" />
      <div style={{height: 16}} />
      <StackedBarChart />
    </Card>

    {/* Section C — Revenue breakdown */}
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 20, marginBottom: 24}}>
      <Card>
        <SectionHead title="Revenue by payment status" sub="Total: ₦4,231,000" />
        <div style={{height: 16}} />
        <DonutChart />
      </Card>
      <Card>
        <SectionHead title="Top customers by revenue" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13}}>Full list →</a>} />
        <div style={{height: 16}} />
        <TopCustomersChart />
      </Card>
    </div>

    {/* Section D — CBM & billing table */}
    <Card padding={0} style={{marginBottom: 24}}>
      <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <SectionHead title="CBM &amp; billing by container" sub="Every container processed this period" />
        <Button variant="secondary" size="sm" icon="download">Export</Button>
      </div>
      <Table
        dense
        columns={[
          {title: 'Container'},
          {title: 'Customers', align: 'right'},
          {title: 'Total CBM', align: 'right'},
          {title: 'CBM rate', align: 'right'},
          {title: 'FX', align: 'right'},
          {title: 'Billed', align: 'right'},
          {title: 'Collected', align: 'right'},
          {title: 'Outstanding', align: 'right'},
        ]}
        rows={[
          {cells: [<Mono>MSCU1234567</Mono>, <Mono>12</Mono>, <Mono>8.42</Mono>, <Mono>$48</Mono>, <Mono>₦1,650</Mono>, <Mono>₦665,000</Mono>, <Mono color={T.success}>₦620,000</Mono>, <Mono color={T.warning}>₦45,000</Mono>]},
          {cells: [<Mono>HLBU9384712</Mono>, <Mono>8</Mono>, <Mono>8.42</Mono>, <Mono>$48</Mono>, <Mono>₦1,650</Mono>, <Mono>₦582,000</Mono>, <Mono color={T.success}>₦582,000</Mono>, <Mono color={T.ink4}>—</Mono>]},
          {cells: [<Mono>COSU7194820</Mono>, <Mono>15</Mono>, <Mono>14.20</Mono>, <Mono>$48</Mono>, <Mono>₦1,650</Mono>, <Mono>₦1,124,000</Mono>, <Mono color={T.success}>₦1,050,000</Mono>, <Mono color={T.error}>₦74,000</Mono>]},
          {cells: [<Mono>ONEU2847510</Mono>, <Mono>9</Mono>, <Mono>6.12</Mono>, <Mono>$48</Mono>, <Mono>₦1,650</Mono>, <Mono>₦485,000</Mono>, <Mono color={T.success}>₦485,000</Mono>, <Mono color={T.ink4}>—</Mono>]},
          {cells: [<Mono>MAEU4729183</Mono>, <Mono>11</Mono>, <Mono>5.80</Mono>, <Mono>$48</Mono>, <Mono>₦1,650</Mono>, <Mono>₦459,000</Mono>, <Mono color={T.success}>₦412,000</Mono>, <Mono color={T.warning}>₦47,000</Mono>]},
        ]}
      />
    </Card>

    {/* Section E — Claims summary */}
    <SectionHead title="Claims summary" />
    <div style={{height: 12}} />
    <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16}}>
      <ClaimsSummaryCard icon="warn" color={T.error} title="Damage claims" stats={[['Filed', '8'], ['Resolved', '6'], ['Open', '2']]} />
      <ClaimsSummaryCard icon="package" color={T.warning} title="Missing items" stats={[['Logged', '5'], ['Found', '3'], ['Lost', '1']]} />
      <ClaimsSummaryCard icon="coin" color={T.success} title="Refunds issued" stats={[['Approved', '18'], ['Total', '₦842k'], ['', '']]} />
    </div>
  </PageShell>
);

const StackedBarChart = () => {
  const weeks = [
    {w: 'Apr 1', t: 2, c: 1, cl: 1, p: 3},
    {w: 'Apr 8', t: 1, c: 2, cl: 2, p: 2},
    {w: 'Apr 15', t: 3, c: 1, cl: 1, p: 1},
    {w: 'Apr 22', t: 2, c: 2, cl: 3, p: 2},
    {w: 'Apr 29', t: 1, c: 1, cl: 2, p: 4},
    {w: 'May 6', t: 3, c: 0, cl: 1, p: 3},
    {w: 'May 13', t: 2, c: 2, cl: 2, p: 2},
    {w: 'May 20', t: 1, c: 1, cl: 3, p: 3},
  ];
  const max = 8;
  const segs = [{k: 't', label: 'In transit', color: T.info}, {k: 'c', label: 'At customs', color: T.warning}, {k: 'cl', label: 'Cleared', color: T.green}, {k: 'p', label: 'Picked up', color: T.greenFlash}];
  return (
    <div>
      <div style={{display: 'flex', alignItems: 'flex-end', gap: 12, height: 200, padding: '0 0 0 4px'}}>
        {weeks.map((wk, i) => (
          <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6}}>
            <div style={{width: '100%', maxWidth: 44, display: 'flex', flexDirection: 'column-reverse', height: 170, justifyContent: 'flex-start'}}>
              {segs.map(s => wk[s.k] > 0 && (
                <div key={s.k} style={{height: `${(wk[s.k] / max) * 100}%`, background: s.color, borderRadius: s.k === 'p' ? '0 0 3px 3px' : 0, minHeight: 3}} />
              ))}
            </div>
            <div style={{fontSize: 10, color: T.ink4, fontFamily: T.mono}}>{wk.w}</div>
          </div>
        ))}
      </div>
      <div style={{display: 'flex', gap: 16, marginTop: 16, justifyContent: 'center', flexWrap: 'wrap'}}>
        {segs.map(s => (
          <div key={s.k} style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.ink3}}>
            <span style={{width: 10, height: 10, borderRadius: 3, background: s.color}} />{s.label}
          </div>
        ))}
      </div>
    </div>
  );
};

const DonutChart = () => {
  const segs = [
    {label: 'Paid', value: 68, color: T.success, amt: '₦2.88M'},
    {label: 'Partially paid', value: 14, color: T.warning, amt: '₦592k'},
    {label: 'Unpaid', value: 9, color: T.error, amt: '₦381k'},
    {label: 'Released w/ outstanding', value: 6, color: T.rolePlatform, amt: '₦254k'},
    {label: 'Waived', value: 3, color: T.ink4, amt: '₦127k'},
  ];
  let acc = 0;
  const grad = segs.map(s => {
    const start = acc; acc += s.value;
    return `${s.color} ${start}% ${acc}%`;
  }).join(', ');
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 24}}>
      <div style={{position: 'relative', width: 160, height: 160, flexShrink: 0}}>
        <div style={{width: '100%', height: '100%', borderRadius: '50%', background: `conic-gradient(${grad})`}} />
        <div style={{position: 'absolute', inset: 28, borderRadius: '50%', background: '#fff', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
          <div style={{fontSize: 10, color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Total</div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 18, color: T.ink, letterSpacing: '-0.01em'}}>₦4.23M</div>
        </div>
      </div>
      <div style={{flex: 1}}>
        {segs.map(s => (
          <div key={s.label} style={{display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0'}}>
            <span style={{width: 10, height: 10, borderRadius: 3, background: s.color, flexShrink: 0}} />
            <span style={{flex: 1, fontSize: 13, color: T.ink2}}>{s.label}</span>
            <Mono color={T.ink}>{s.amt}</Mono>
            <span style={{fontSize: 11, color: T.ink4, width: 32, textAlign: 'right'}}>{s.value}%</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const TopCustomersChart = () => {
  const customers = [
    {name: 'Emeka Eze', amt: 842000, pct: 100},
    {name: 'Ibrahim Musa', amt: 624000, pct: 74},
    {name: 'Funmilayo Adeyemi', amt: 518000, pct: 62},
    {name: 'Ngozi Okonkwo', amt: 412000, pct: 49},
    {name: 'Aisha Lawal', amt: 386000, pct: 46},
    {name: 'Bola Adesina', amt: 298000, pct: 35},
    {name: 'Olufemi Adetunji', amt: 254000, pct: 30},
  ];
  return (
    <div>
      {customers.map((c, i) => (
        <div key={c.name} style={{display: 'flex', alignItems: 'center', gap: 12, padding: '7px 0'}}>
          <span style={{fontSize: 12, color: T.ink2, width: 130, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{c.name}</span>
          <div style={{flex: 1, height: 18, background: T.muted, borderRadius: 4, overflow: 'hidden'}}>
            <div style={{height: '100%', width: `${c.pct}%`, background: i === 0 ? T.copper : T.green, borderRadius: 4}} />
          </div>
          <Mono color={T.ink}>₦{(c.amt / 1000).toFixed(0)}k</Mono>
        </div>
      ))}
    </div>
  );
};

const ClaimsSummaryCard = ({icon, color, title, stats}) => (
  <Card padding={20}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14}}>
      <div style={{width: 36, height: 36, borderRadius: 10, background: color + '18', color, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
        <Icon name={icon} size={16} />
      </div>
      <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: T.ink}}>{title}</span>
    </div>
    <div style={{display: 'flex', gap: 20}}>
      {stats.filter(s => s[0]).map(([label, val]) => (
        <div key={label}>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, color: T.ink, letterSpacing: '-0.01em'}}>{val}</div>
          <div style={{fontSize: 11, color: T.ink4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 2}}>{label}</div>
        </div>
      ))}
    </div>
  </Card>
);

// ============================================================
// 14.11 — NOTIFICATION DELIVERY LOG
// ============================================================
const NotificationLog = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={<TenantBrand name="Acme Logistics" logo="AL" />} items={adminNav('notiflog')} user={adminU} />}
    topbar={<TopBar role="admin" title="Notification delivery log" breadcrumb={['Admin', 'Notifications', 'Delivery log']} user={adminU} actions={
      <Button variant="secondary" icon="download">Export</Button>
    } />}
  >
    {/* Summary stats bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap'}}>
        <div style={{fontSize: 12, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Last 30 days</div>
        <LogStat label="Sent" value="247" color={T.info} />
        <LogStat label="Delivered" value="234" sub="94.7%" color={T.success} />
        <LogStat label="Failed" value="13" color={T.error} />
        <LogStat label="Pending" value="0" color={T.ink4} />
      </div>
    </Card>

    {/* Filters */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All channels</Chip>
          <Chip count={88}>SMS</Chip>
          <Chip count={124}>WhatsApp</Chip>
          <Chip count={35}>Email</Chip>
        </div>
        <div style={{flex: 1, minWidth: 200}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Customer, event type, message…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" trailing="chevdown">Status: All</Button>
        <Button variant="secondary" size="md" icon="calendar">Last 30 days</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Sent at'},
          {title: 'Customer'},
          {title: 'Channel'},
          {title: 'Event type'},
          {title: 'Message preview'},
          {title: 'Status'},
          {title: '', width: 90},
        ]}
        rows={[
          logRow({ts: '15 Apr 14:32', cust: 'Ngozi Okonkwo', ch: 'WhatsApp', event: 'Payment due', msg: 'Your cargo is ready… ₦49,352', status: 'delivered'}),
          logRow({ts: '15 Apr 14:31', cust: 'Adaeze Nwosu', ch: 'SMS', event: 'Payment due', msg: 'Dear Adaeze, your shipment…', status: 'failed'}),
          logRow({ts: '15 Apr 09:00', cust: 'Emeka Eze', ch: 'Email', event: 'Status update', msg: 'Your container has cleared customs…', status: 'delivered'}),
          logRow({ts: '14 Apr 18:22', cust: 'Funmilayo Adeyemi', ch: 'WhatsApp', event: 'Release note', msg: 'Your goods are ready for pickup at…', status: 'delivered'}),
          logRow({ts: '14 Apr 16:08', cust: 'Ibrahim Musa', ch: 'SMS', event: 'Status update', msg: 'Container HLBU9384712 has arrived…', status: 'sent'}),
          logRow({ts: '14 Apr 11:44', cust: 'Bola Adesina', ch: 'Email', event: 'Claim filed', msg: 'We received your damage claim DC-…', status: 'delivered'}),
          logRow({ts: '13 Apr 22:30', cust: 'Aisha Lawal', ch: 'WhatsApp', event: 'Payment due', msg: 'Reminder: ₦88,560 outstanding on…', status: 'pending'}),
          logRow({ts: '13 Apr 14:02', cust: 'Yusuf Garba', ch: 'SMS', event: 'Status update', msg: 'Your cargo is in transit. ETA…', status: 'failed'}),
        ]}
      />
      <TablePagination />
    </Card>

    {withModal && <NotifDetailModal />}
  </PageShell>
);

const LogStat = ({label, value, sub, color}) => (
  <div style={{display: 'flex', alignItems: 'baseline', gap: 6}}>
    <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 20, color, letterSpacing: '-0.01em'}}>{value}</span>
    <span style={{fontSize: 12, color: T.ink3, fontWeight: 600}}>{label}</span>
    {sub && <span style={{fontSize: 11, color: T.ink4}}>({sub})</span>}
  </div>
);

const logRow = ({ts, cust, ch, event, msg, status}) => {
  const chIcon = ch === 'Email' ? 'mail' : 'phone';
  const chColor = ch === 'WhatsApp' ? T.success : ch === 'SMS' ? T.info : T.copper;
  const statusBadge = {
    delivered: <Badge variant="success" size="sm">Delivered</Badge>,
    failed: <Badge variant="error" size="sm">Failed</Badge>,
    sent: <Badge variant="info" size="sm">Sent</Badge>,
    pending: <Badge variant="warning" size="sm">Pending</Badge>,
  }[status];
  return {
    suspended: status === 'failed',
    cells: [
      <Mono color={T.ink2}>{ts}</Mono>,
      <UserCell name={cust} email={''} />,
      <div style={{display: 'inline-flex', alignItems: 'center', gap: 6}}><Icon name={chIcon} size={13} color={chColor} /><span style={{fontSize: 12, color: T.ink2}}>{ch}</span></div>,
      <span style={{fontSize: 12, color: T.ink2}}>{event}</span>,
      <span style={{fontSize: 12, color: T.ink3, fontStyle: 'italic', maxWidth: 240, display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>"{msg}"</span>,
      statusBadge,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        {status === 'failed' ? <Button variant="secondary" size="sm" icon="refresh">Retry</Button> : <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

const NotifDetailModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Notification detail</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>WhatsApp · Payment due · 15 Apr 14:32</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Kvp label="Recipient" value={<Mono>+234***4567</Mono>} />
        <Kvp label="Channel" value={<div style={{display: 'inline-flex', alignItems: 'center', gap: 6}}><Icon name="phone" size={13} color={T.success} />WhatsApp</div>} />
        <Kvp label="Status" value={<Badge variant="success" size="sm">Delivered · 14:32:08</Badge>} />
        <div style={{marginTop: 12, marginBottom: 14}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8}}>Message body</div>
          <div style={{background: '#dcf8c6', borderRadius: '10px 10px 2px 10px', padding: '10px 12px', fontSize: 13, color: T.ink, lineHeight: 1.5}}>
            Dear Ngozi Okonkwo, your cargo in container MSCU1234567 is cleared and ready for pickup. Amount due: ₦49,352. Collect at 12 Wharf Rd, Lagos. — Acme Logistics
          </div>
        </div>
        <div style={{padding: 12, background: T.muted, borderRadius: 8, fontSize: 11, fontFamily: T.mono, color: T.ink3}}>
          <div style={{fontWeight: 700, color: T.ink2, marginBottom: 4}}>Gateway response</div>
          WhatsApp API: 200 OK · Message ID: wamid.HBgM...abc123
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="secondary" icon="refresh">Resend</Button>
        <Button variant="primary">Close</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 14.12 — PRINT LAYOUTS (A4)
// ============================================================
const PrintPackingList = () => (
  <div style={{background: '#525659', padding: 40, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 794, minHeight: 1123, background: '#fff', boxShadow: '0 4px 24px rgba(0,0,0,0.3)', padding: '56px 56px', fontFamily: T.body, color: '#000', position: 'relative'}}>
      {/* Approved stamp */}
      <div style={{position: 'absolute', top: 120, right: 80, width: 120, height: 120, borderRadius: '50%', border: `4px solid ${T.success}`, opacity: 0.12, display: 'flex', alignItems: 'center', justifyContent: 'center', transform: 'rotate(-12deg)'}}>
        <span style={{fontFamily: T.display, fontWeight: 900, fontSize: 20, color: T.success, letterSpacing: '0.06em'}}>APPROVED</span>
      </div>

      {/* Header */}
      <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20}}>
        <div style={{width: 64, height: 64, borderRadius: 10, background: '#333', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 22, fontFamily: T.display}}>AL</div>
        <div style={{textAlign: 'right'}}>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 20, color: '#000'}}>Acme Logistics Ltd</div>
          <div style={{fontSize: 10, color: '#666', fontStyle: 'italic'}}>Trusted China-Nigeria cargo since 2019</div>
        </div>
      </div>
      <div style={{borderTop: '2px solid #000', marginBottom: 16}} />

      {/* Title row */}
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4}}>
        <h1 style={{fontFamily: T.display, fontWeight: 800, fontSize: 22, letterSpacing: '0.04em', margin: 0}}>PACKING LIST</h1>
        <span style={{fontFamily: T.mono, fontSize: 13, fontWeight: 600}}>Ref: PL-20260415-001</span>
      </div>
      <div style={{fontSize: 11, color: '#444', marginBottom: 14}}>Container: <strong>MSCU1234567</strong> &nbsp;·&nbsp; Vessel: MSC Altair &nbsp;·&nbsp; Origin: Guangzhou</div>

      {/* Customer block */}
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 11, padding: 14, background: '#f5f5f5', borderRadius: 4, marginBottom: 20}}>
        <div><span style={{color: '#666'}}>Customer:</span> <strong>Ngozi Okonkwo</strong></div>
        <div><span style={{color: '#666'}}>Date:</span> 15 April 2026</div>
        <div><span style={{color: '#666'}}>Phone:</span> +234 801 234 5678</div>
        <div><span style={{color: '#666'}}>Tracking:</span> <span style={{fontFamily: T.mono}}>SHX-2026-NGOZI-001</span></div>
      </div>

      {/* Items table */}
      <table style={{width: '100%', borderCollapse: 'collapse', fontSize: 10, marginBottom: 20}}>
        <thead>
          <tr style={{borderBottom: '1.5px solid #000'}}>
            {['Carton Tag', 'Description', 'Wt Dispatch', 'Wt Actual', 'L×W×H (cm)', 'CBM', 'Received'].map(h => (
              <th key={h} style={{padding: '7px 6px', textAlign: h === 'Description' || h === 'Carton Tag' ? 'left' : 'right', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#444'}}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[
            ['SHX-00001', 'Electronics (mixed)', '12.5 kg', '12.8 kg', '40×30×25', '0.030', '15 Apr'],
            ['SHX-00002', 'Clothing (assorted)', '8.2 kg', '8.5 kg', '35×30×20', '0.021', '15 Apr'],
            ['SHX-00003', 'Phone accessories', '6.0 kg', '6.2 kg', '30×25×24', '0.018', '15 Apr'],
            ['SHX-00004', 'Spare parts (auto)', '9.0 kg', '9.1 kg', '40×30×20', '0.024', '15 Apr'],
          ].map((r, i) => (
            <tr key={i} style={{borderBottom: '0.5px solid #ccc', background: i % 2 ? '#fafafa' : '#fff'}}>
              <td style={{padding: '7px 6px', fontFamily: T.mono, fontWeight: 600}}>{r[0]}</td>
              <td style={{padding: '7px 6px'}}>{r[1]}</td>
              <td style={{padding: '7px 6px', textAlign: 'right', fontFamily: T.mono}}>{r[2]}</td>
              <td style={{padding: '7px 6px', textAlign: 'right', fontFamily: T.mono}}>{r[3]}</td>
              <td style={{padding: '7px 6px', textAlign: 'right', fontFamily: T.mono}}>{r[4]}</td>
              <td style={{padding: '7px 6px', textAlign: 'right', fontFamily: T.mono, fontWeight: 600}}>{r[5]}</td>
              <td style={{padding: '7px 6px', textAlign: 'right'}}>{r[6]}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Summary */}
      <div style={{borderTop: '2px solid #000', paddingTop: 12, marginBottom: 28}}>
        <div style={{fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#444', marginBottom: 6}}>Summary</div>
        <div style={{display: 'flex', gap: 32, fontSize: 12}}>
          <span>Total Cartons: <strong>4</strong></span>
          <span>Total Weight (Actual): <strong>36.6 kg</strong></span>
          <span>Total CBM: <strong>0.093</strong></span>
        </div>
      </div>

      {/* Footer */}
      <div style={{fontSize: 11, marginBottom: 8}}>Prepared by: <strong>Kwame Asante</strong> (China Office) &nbsp;&nbsp; Date: 15 April 2026</div>
      <div style={{display: 'inline-block', padding: '4px 12px', border: `1.5px solid ${T.success}`, color: T.success, borderRadius: 4, fontWeight: 700, fontSize: 11, letterSpacing: '0.04em'}}>STATUS: APPROVED ✓</div>
      <div style={{borderTop: '1px solid #ccc', marginTop: 28, paddingTop: 12, fontSize: 9, color: '#888', textAlign: 'center', lineHeight: 1.5}}>
        This packing list is an official document issued by Acme Logistics Ltd.<br />
        For queries, contact: support@acmelogistics.com &nbsp;·&nbsp; Page 1 of 1
      </div>
    </div>
  </div>
);

const PrintReleaseNote = () => (
  <div style={{background: '#525659', padding: 40, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 794, minHeight: 1123, background: '#fff', boxShadow: '0 4px 24px rgba(0,0,0,0.3)', padding: '56px', fontFamily: T.body, color: '#000', position: 'relative'}}>
      {/* Header */}
      <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 20}}>
        <div style={{width: 64, height: 64, borderRadius: 10, background: '#333', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 22, fontFamily: T.display}}>AL</div>
        <div style={{textAlign: 'right'}}>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 20}}>Acme Logistics Ltd</div>
          <div style={{fontSize: 10, color: '#666'}}>support@acmelogistics.com · +234 1 234 5678</div>
        </div>
      </div>
      <div style={{borderTop: '3px double #000', marginBottom: 18}} />

      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18}}>
        <div>
          <h1 style={{fontFamily: T.display, fontWeight: 900, fontSize: 24, letterSpacing: '0.06em', margin: '0 0 12px'}}>GOODS RELEASE NOTE</h1>
          <div style={{fontSize: 11, lineHeight: 1.8}}>
            <div><span style={{color: '#666'}}>Reference:</span> <strong style={{fontFamily: T.mono}}>RN-20260415-ABC123</strong></div>
            <div><span style={{color: '#666'}}>Date of issue:</span> 15 April 2026</div>
            <div><span style={{color: '#666'}}>Valid until:</span> <strong>22 April 2026</strong> (7 days)</div>
          </div>
        </div>
        {/* QR */}
        <div style={{width: 100, height: 100, border: '1px solid #000', padding: 5}}>
          <div style={{width: '100%', height: '100%', background: `repeating-conic-gradient(#000 0% 25%, #fff 0% 50%) 50% / 11px 11px`}} />
        </div>
      </div>

      {/* Customer & cargo */}
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', border: '1px solid #000', marginBottom: 18}}>
        <div style={{padding: 14, borderRight: '1px solid #000'}}>
          <div style={{fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#666', marginBottom: 6}}>Customer Details</div>
          <div style={{fontSize: 11, lineHeight: 1.7}}>
            <div><span style={{color: '#666'}}>Name:</span> <strong>Ngozi Okonkwo</strong></div>
            <div><span style={{color: '#666'}}>Phone:</span> +234 801 234 5678</div>
          </div>
        </div>
        <div style={{padding: 14}}>
          <div style={{fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: '#666', marginBottom: 6}}>Cargo Details</div>
          <div style={{fontSize: 11, lineHeight: 1.7}}>
            <div><span style={{color: '#666'}}>Container:</span> <strong style={{fontFamily: T.mono}}>MSCU1234567</strong></div>
            <div><span style={{color: '#666'}}>Vessel:</span> MSC Altair</div>
            <div><span style={{color: '#666'}}>Total cartons:</span> 4 — <span style={{fontFamily: T.mono}}>SHX-00001…00004</span></div>
          </div>
        </div>
      </div>

      {/* Payment */}
      <div style={{border: `1.5px solid ${T.success}`, background: '#f0fdf4', borderRadius: 4, padding: 14, marginBottom: 18}}>
        <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 13, color: T.successStrong, letterSpacing: '0.04em', marginBottom: 4}}>PAYMENT STATUS: PAID IN FULL ✓</div>
        <div style={{fontSize: 11, fontFamily: T.mono}}>Amount Paid: ₦100,008.00 &nbsp;·&nbsp; Payment Ref: TRF-20260415-001</div>
      </div>

      {/* Collection instructions */}
      <div style={{marginBottom: 24}}>
        <div style={{fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#444', marginBottom: 6, borderBottom: '1px solid #ccc', paddingBottom: 4}}>Collection Instructions</div>
        <p style={{fontSize: 11, lineHeight: 1.7, margin: '8px 0'}}>Please present this release note (printed or digital) at:</p>
        <p style={{fontSize: 12, fontWeight: 700, margin: '4px 0'}}>12 Wharf Road, Apapa, Lagos — Bay 4</p>
        <p style={{fontSize: 11, color: '#444', margin: '4px 0'}}>Operating Hours: Monday – Saturday, 8:00 AM – 5:00 PM</p>
        <p style={{fontSize: 11, color: '#444', margin: '4px 0'}}>The customer or authorized delegate must present valid photo ID.</p>
      </div>

      {/* Auth footer */}
      <div className="sx-grid2" style={{borderTop: '3px double #000', paddingTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
        <div style={{fontSize: 11, lineHeight: 1.8}}>
          <div><span style={{color: '#666'}}>Authorized by:</span> <strong>Amara Okafor</strong></div>
          <div style={{color: '#444'}}>Nigeria Office Staff · Acme Logistics</div>
          <div style={{color: '#666', marginTop: 4}}>Date: 15 April 2026</div>
        </div>
        <div style={{textAlign: 'right'}}>
          <div style={{fontSize: 9, color: '#666', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14}}>Signature</div>
          <div style={{fontFamily: 'Brush Script MT, cursive', fontSize: 24, fontStyle: 'italic', borderBottom: '1px solid #000', paddingBottom: 4, display: 'inline-block', minWidth: 160}}>Amara O.</div>
        </div>
      </div>
      <div style={{textAlign: 'center', fontSize: 9, color: '#888', marginTop: 24, fontStyle: 'italic'}}>This document is valid for one-time use only. Shipx Platform.</div>
    </div>
  </div>
);

Object.assign(window, {
  BulkImport, PlatformAuditLog, TenantReports, NotificationLog,
  PrintPackingList, PrintReleaseNote,
});
