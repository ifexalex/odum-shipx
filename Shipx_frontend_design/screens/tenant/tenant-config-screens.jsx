// ============================================================
// Shipx — Tenant Admin Configuration Screens (Section 4)
// 4.1 Company Settings · 4.2 Dollar Rate · 4.3 CBM Rate
// 4.4 Charge Types · 4.5 Notification Templates
// ============================================================

const configSidebarItems = (active) => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard'},
    {icon: 'chart', label: 'Reports'},
  ]},
  {group: 'Operations', items: [
    {icon: 'users', label: 'Customers', count: '142'},
    {icon: 'user', label: 'Staff users', count: '24'},
  ]},
  {group: 'Configuration', items: [
    {icon: 'settings', label: 'Company settings', active: active === 'company'},
    {icon: 'coin', label: 'Dollar rate', active: active === 'dollar'},
    {icon: 'package', label: 'CBM rate', active: active === 'cbm'},
    {icon: 'card', label: 'Charge types', active: active === 'charges'},
    {icon: 'bell', label: 'Notifications', active: active === 'notif'},
  ]},
];

// ============================================================
// Vertical config nav (used inside config pages)
// ============================================================
const ConfigSubNav = ({active}) => {
  const items = [
    {key: 'company', icon: 'settings', label: 'Company', desc: 'Logo, name, address'},
    {key: 'dollar', icon: 'coin', label: 'Dollar rate', desc: 'USD → NGN'},
    {key: 'cbm', icon: 'package', label: 'CBM rate', desc: 'Price per cubic meter'},
    {key: 'charges', icon: 'card', label: 'Charge types', desc: 'Custom misc charges'},
    {key: 'storage', icon: 'building', label: 'Storage fees', desc: 'Daily rate + free window'},
    {key: 'notif', icon: 'bell', label: 'Notifications', desc: 'SMS · WhatsApp · Email'},
  ];
  return (
    <Card padding={8} style={{position: 'sticky', top: 0}}>
      {items.map((it, i) => {
        const isActive = it.key === active;
        return (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            padding: '10px 12px', borderRadius: 8,
            background: isActive ? T.greenTint : 'transparent',
            cursor: 'pointer',
          }}>
            <div style={{
              width: 30, height: 30, borderRadius: 8,
              background: isActive ? T.green : T.muted,
              color: isActive ? '#fff' : T.ink3,
              display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
            }}>
              <Icon name={it.icon} size={14} stroke={2.2} />
            </div>
            <div style={{flex: 1, minWidth: 0}}>
              <div style={{fontSize: 13.5, fontWeight: isActive ? 700 : 600, color: isActive ? T.greenDeep : T.ink, lineHeight: 1.2}}>{it.label}</div>
              <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{it.desc}</div>
            </div>
            {isActive && <Icon name="chevright" size={13} color={T.green} />}
          </div>
        );
      })}
    </Card>
  );
};

// ============================================================
// 4.1 — COMPANY SETTINGS
// ============================================================
const CompanySettings = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={configSidebarItems('company')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Company settings" breadcrumb={['Admin', 'Configuration', 'Company']} user={tenantUser} />}
  >
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '260px 1fr 380px', gap: 24}}>
      <ConfigSubNav active="company" />

      <div>
        <Card style={{marginBottom: 20}}>
          <SectionHead title="Company identity" sub="Shown on packing lists, release notes, and the customer portal" />
          <div style={{height: 16}} />
          <Field label="Company name" required value="Acme Logistics Ltd" helper="Used everywhere a company name appears." />
          <Field label="Display tagline" value="Trusted China-Nigeria cargo since 2019" optional helper="Optional. Shown beneath the logo on documents." />

          <div style={{marginTop: 8, marginBottom: 16}}>
            <label style={{display: 'block', fontFamily: T.body, fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>
              Company logo <span style={{color: T.error}}>*</span>
            </label>
            <div style={{
              border: `1.5px dashed ${T.lineStrong}`, borderRadius: 10, padding: 16,
              display: 'flex', alignItems: 'center', gap: 16, background: T.muted,
            }}>
              <div style={{
                width: 80, height: 80, borderRadius: 14,
                background: T.copperSoft, color: T.copperDeep,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontWeight: 800, fontSize: 28, fontFamily: T.display, flexShrink: 0,
              }}>AL</div>
              <div style={{flex: 1, minWidth: 0}}>
                <div style={{fontWeight: 600, color: T.ink, fontSize: 14}}>acme-logistics-logo.svg</div>
                <div style={{fontSize: 12, color: T.ink4, marginTop: 2}}>SVG · 6.4 KB · uploaded 14 Jan 2026 by Amara Okafor</div>
                <div style={{fontSize: 11, color: T.ink4, marginTop: 6}}>Recommended: SVG or PNG, square or wider, max 2 MB. Light backgrounds preferred.</div>
              </div>
              <div style={{display: 'flex', flexDirection: 'column', gap: 6, flexShrink: 0}}>
                <Button variant="secondary" size="sm" icon="upload">Replace</Button>
                <Button variant="ghost" size="sm">Remove</Button>
              </div>
            </div>
          </div>
        </Card>

        <Card style={{marginBottom: 20}}>
          <SectionHead title="Warehouse & contact" sub="Where customers collect goods and reach you" />
          <div style={{height: 16}} />
          <Field label="Warehouse address" required multiline value={"12 Wharf Road, Apapa\nLagos 100242\nNigeria"} helper="Printed on release notes for customer pickup." />
          <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
            <Field label="Pickup hours" value="Mon–Sat · 8:00 AM – 5:00 PM" />
            <Field label="Pickup contact phone" value="+234 1 234 5678" icon="phone" />
          </div>
          <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
            <Field label="Support email" type="email" value="support@acmelogistics.com" icon="mail" />
            <Field label="Support WhatsApp" value="+234 802 415 0922" icon="phone" />
          </div>
        </Card>

        <Card>
          <SectionHead title="Document footer" sub="Boilerplate text on the bottom of generated PDFs" />
          <div style={{height: 16}} />
          <Field label="Footer text" multiline value={"This document is an official record issued by Acme Logistics Ltd.\nFor queries, contact support@acmelogistics.com or +234 1 234 5678.\nRC 1842519 · Member of NSC Freight Forwarders Association."} helper="Appears at the bottom of every packing list and release note." />
        </Card>

        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 0 0'}}>
          <div style={{fontSize: 12, color: T.ink4}}>Last saved 14 Apr 2026, 16:30 by Amara Okafor</div>
          <div style={{display: 'flex', gap: 10}}>
            <Button variant="ghost">Discard</Button>
            <Button variant="primary" icon="check">Save changes</Button>
          </div>
        </div>
      </div>

      {/* Live preview */}
      <div>
        <Card padding={20} style={{position: 'sticky', top: 0}}>
          <SectionHead title="Live preview" sub="How your branding appears on documents" />
          <div style={{height: 16}} />
          <PreviewToggle />
          <div style={{height: 16}} />
          <DocPreview />
        </Card>
      </div>
    </div>
  </PageShell>
);

const PreviewToggle = () => (
  <div style={{display: 'flex', background: T.muted, borderRadius: 8, padding: 4, border: `1px solid ${T.line}`}}>
    <button style={{flex: 1, padding: '6px 10px', background: '#fff', borderRadius: 6, border: 0, fontSize: 12, fontWeight: 700, color: T.ink, cursor: 'pointer', boxShadow: T.shadowRest}}>Packing list</button>
    <button style={{flex: 1, padding: '6px 10px', background: 'transparent', borderRadius: 6, border: 0, fontSize: 12, fontWeight: 600, color: T.ink3, cursor: 'pointer'}}>Release note</button>
    <button style={{flex: 1, padding: '6px 10px', background: 'transparent', borderRadius: 6, border: 0, fontSize: 12, fontWeight: 600, color: T.ink3, cursor: 'pointer'}}>Customer email</button>
  </div>
);

const DocPreview = () => (
  <div style={{
    background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8,
    aspectRatio: '210 / 297', padding: 18, fontSize: 9, fontFamily: T.body,
    color: T.ink, lineHeight: 1.4, overflow: 'hidden',
  }}>
    {/* Header */}
    <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14, paddingBottom: 10, borderBottom: `1px solid ${T.line}`}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <div style={{width: 36, height: 36, borderRadius: 6, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 14, fontFamily: T.display}}>AL</div>
        <div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 11, color: T.ink, lineHeight: 1.1}}>Acme Logistics Ltd</div>
          <div style={{fontSize: 7, color: T.ink4, fontStyle: 'italic', marginTop: 2}}>Trusted China-Nigeria cargo since 2019</div>
        </div>
      </div>
      <div style={{textAlign: 'right'}}>
        <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 11, letterSpacing: '0.04em', color: T.ink}}>PACKING LIST</div>
        <div style={{fontFamily: T.mono, fontSize: 7, color: T.ink3, marginTop: 2}}>PL-20260415-001</div>
      </div>
    </div>

    {/* Customer block */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 7.5, marginBottom: 10}}>
      <div>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 6.5, marginBottom: 2}}>Customer</div>
        <div style={{fontWeight: 700}}>Ngozi Okonkwo</div>
        <div style={{fontFamily: T.mono, color: T.ink3}}>+234 801 234 5678</div>
      </div>
      <div>
        <div style={{color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 6.5, marginBottom: 2}}>Container</div>
        <div style={{fontFamily: T.mono, fontWeight: 700}}>MSCU1234567</div>
        <div style={{color: T.ink3}}>Origin: Guangzhou</div>
      </div>
    </div>

    {/* Mini items table */}
    <div className="sx-cols" style={{background: T.muted, padding: '4px 6px', display: 'grid', gridTemplateColumns: '24px 1fr 40px 40px 40px', gap: 4, fontSize: 6.5, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.06em', borderRadius: 3}}>
      <span>Tag</span><span>Description</span><span style={{textAlign: 'right'}}>Wt</span><span style={{textAlign: 'right'}}>CBM</span><span style={{textAlign: 'right'}}>USD</span>
    </div>
    {[
      ['SHX-00001', 'Electronics (mixed)', '12.8', '0.030', '380'],
      ['SHX-00002', 'Clothing (assorted)', '8.5', '0.021', '240'],
      ['SHX-00003', 'Phone accessories', '6.2', '0.018', '180'],
      ['SHX-00004', 'Spare parts', '9.1', '0.024', '320'],
    ].map((row, i) => (
      <div key={i} className="sx-cols" style={{display: 'grid', gridTemplateColumns: '24px 1fr 40px 40px 40px', gap: 4, fontSize: 7, padding: '4px 6px', borderBottom: `1px solid ${T.line}`, color: T.ink2}}>
        <span style={{fontFamily: T.mono, color: T.ink}}>{row[0]}</span>
        <span>{row[1]}</span>
        <span style={{textAlign: 'right', fontFamily: T.mono}}>{row[2]} kg</span>
        <span style={{textAlign: 'right', fontFamily: T.mono}}>{row[3]}</span>
        <span style={{textAlign: 'right', fontFamily: T.mono}}>${row[4]}</span>
      </div>
    ))}

    {/* Totals */}
    <div style={{display: 'flex', justifyContent: 'flex-end', gap: 12, fontSize: 7.5, marginTop: 8, paddingTop: 6, borderTop: `1px solid ${T.line}`, fontWeight: 700}}>
      <span>4 cartons</span><span>·</span><span>36.6 kg</span><span>·</span><span style={{color: T.green}}>0.093 CBM</span>
    </div>

    {/* Footer */}
    <div style={{marginTop: 'auto', paddingTop: 20, fontSize: 6, color: T.ink4, lineHeight: 1.5, fontStyle: 'italic'}}>
      <div>This document is an official record issued by Acme Logistics Ltd.</div>
      <div>For queries: support@acmelogistics.com · +234 1 234 5678</div>
      <div>RC 1842519 · Member of NSC Freight Forwarders Association</div>
    </div>
  </div>
);

// ============================================================
// 4.2 — DOLLAR RATE
// ============================================================
const DollarRatePage = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={configSidebarItems('dollar')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Dollar exchange rate" breadcrumb={['Admin', 'Configuration', 'Dollar rate']} user={tenantUser} />}
  >
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24}}>
      <ConfigSubNav active="dollar" />

      <div>
        <PageHeader
          eyebrow="USD → NGN"
          title="Dollar exchange rate"
          subtitle="The rate used to convert USD shipping costs into NGN at billing time. Changes only affect billing records created after the change."
        />

        {/* Current rate hero */}
        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20, marginBottom: 20}}>
          <Card padding={28} style={{background: `linear-gradient(135deg, ${T.greenForest} 0%, ${T.greenDeep} 100%)`, color: '#fff', border: 'none', boxShadow: T.shadowModal}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16}}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                background: 'rgba(45,196,56,0.18)', color: T.greenFlash,
                padding: '4px 10px', borderRadius: 9999, fontSize: 10, fontWeight: 700,
                letterSpacing: '0.1em', textTransform: 'uppercase',
              }}>
                <span style={{width: 6, height: 6, borderRadius: '50%', background: T.greenFlash, boxShadow: `0 0 8px ${T.greenFlash}`}} /> Current rate
              </span>
            </div>
            <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 56, letterSpacing: '-0.03em', color: '#fff', lineHeight: 1, marginBottom: 8}}>
              ₦1,650<span style={{fontSize: 24, color: 'rgba(255,255,255,0.55)', fontWeight: 600, marginLeft: 8}}>per $1 USD</span>
            </div>
            <div style={{fontSize: 13, color: 'rgba(255,255,255,0.7)'}}>
              Set by <strong style={{color: '#fff'}}>Amara Okafor</strong> on 14 April 2026 at 18:30 WAT
            </div>
            <div style={{display: 'flex', gap: 16, marginTop: 24, paddingTop: 20, borderTop: '1px solid rgba(255,255,255,0.1)'}}>
              <DeltaChip label="vs 30 days ago" value="+₦70" pct="+4.4%" />
              <DeltaChip label="vs 90 days ago" value="+₦100" pct="+6.5%" />
              <DeltaChip label="vs onboarding" value="+₦100" pct="+6.5%" />
            </div>
          </Card>

          <Card padding={24}>
            <SectionHead title="Set a new rate" sub="Changes apply to new billing only" />
            <div style={{height: 16}} />
            <Field label="New USD → NGN rate" prefix="₦" required focused value="1680.00" helper="Per $1 USD" />
            <Field label="Reason for change" multiline value="Q2 FX adjustment per CBN intervention rate" helper="Logged in audit history." />
            <Banner variant="warning" title="Heads up">
              Existing billing records keep the rate they were created with. This change affects <strong>new</strong> records only.
            </Banner>
            <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 16}}>
              <Button variant="ghost">Cancel</Button>
              <Button variant="accent" icon="check">Update rate</Button>
            </div>
          </Card>
        </div>

        {/* Trend chart */}
        <Card style={{marginBottom: 20}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <SectionHead title="Rate over time" sub="Last 6 months" />
            <div style={{display: 'flex', gap: 4}}>
              <Chip>30D</Chip>
              <Chip active>6M</Chip>
              <Chip>1Y</Chip>
              <Chip>All</Chip>
            </div>
          </div>
          <div style={{height: 16}} />
          <RateLineChart />
        </Card>

        {/* History */}
        <Card padding={0}>
          <div style={{padding: '18px 20px'}}>
            <SectionHead title="Rate history" sub="Every change, who made it, and why" action={<Button variant="secondary" size="sm" icon="download">Export</Button>} />
          </div>
          <Table
            columns={[
              {title: 'Rate (₦/USD)', sortable: true},
              {title: 'Change'},
              {title: 'Changed by'},
              {title: 'Reason'},
              {title: 'Effective from', sortable: true},
              {title: 'Billing records', align: 'right'},
            ]}
            rows={[
              {cells: [
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}><Mono color={T.green}>₦1,650</Mono><Badge variant="primary" size="sm" dot={false}>Current</Badge></div>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦30</span>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>FX update, CBN window</span>,
                <Mono>14 Apr 2026 18:30</Mono>,
                <Mono>22</Mono>,
              ]},
              {cells: [
                <Mono>₦1,620</Mono>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦40</span>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>Monthly review</span>,
                <Mono>08 Apr 2026 09:14</Mono>,
                <Mono>14</Mono>,
              ]},
              {cells: [
                <Mono>₦1,580</Mono>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦30</span>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>FX update</span>,
                <Mono>24 Mar 2026 14:02</Mono>,
                <Mono>31</Mono>,
              ]},
              {cells: [
                <Mono>₦1,550</Mono>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦20</span>,
                <UserCell name="Olumide Bello" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>FX update</span>,
                <Mono>02 Mar 2026 11:30</Mono>,
                <Mono>28</Mono>,
              ]},
              {cells: [
                <Mono>₦1,530</Mono>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦40</span>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>Quarterly adjustment</span>,
                <Mono>14 Feb 2026 08:00</Mono>,
                <Mono>18</Mono>,
              ]},
              {cells: [
                <Mono>₦1,490</Mono>,
                <span style={{color: T.success, fontSize: 12, fontWeight: 700}}>+₦40</span>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>Initial set after onboarding</span>,
                <Mono>20 Jan 2026 16:45</Mono>,
                <Mono>9</Mono>,
              ]},
              {cells: [
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}><Mono color={T.ink4}>₦1,450</Mono><Badge variant="neutral" size="sm" dot={false}>Onboard</Badge></div>,
                <span style={{fontSize: 12, color: T.ink4}}>—</span>,
                <UserCell name="Alex Ifesinachi" email="Platform Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>Set at tenant onboarding</span>,
                <Mono>14 Jan 2026 12:00</Mono>,
                <Mono>5</Mono>,
              ]},
            ]}
          />
          <TablePagination />
        </Card>
      </div>
    </div>
  </PageShell>
);

const DeltaChip = ({label, value, pct}) => (
  <div>
    <div style={{fontSize: 10, color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, marginBottom: 3}}>{label}</div>
    <div style={{display: 'flex', alignItems: 'baseline', gap: 6}}>
      <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, color: '#fff'}}>{value}</span>
      <span style={{fontSize: 11, color: T.greenFlash, fontWeight: 700}}>{pct}</span>
    </div>
  </div>
);

const RateLineChart = () => {
  // 6 months of fake rate data
  const points = [
    {x: 40, y: 130, m: 'Nov'},
    {x: 130, y: 118, m: 'Dec'},
    {x: 220, y: 112, m: 'Jan'},
    {x: 310, y: 96, m: 'Feb'},
    {x: 400, y: 78, m: 'Mar'},
    {x: 490, y: 56, m: 'Apr'},
    {x: 580, y: 36, m: 'May'},
  ];
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  return (
    <svg viewBox="0 0 640 200" style={{width: '100%', height: 220, fontFamily: T.body}}>
      <defs>
        <linearGradient id="rateGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={T.green} stopOpacity="0.25" />
          <stop offset="1" stopColor={T.green} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Grid lines */}
      {[40, 80, 120, 160].map(y => (
        <line key={y} x1="0" x2="640" y1={y} y2={y} stroke={T.line} strokeDasharray="2 4" />
      ))}
      {/* Y axis labels */}
      <text x="0" y="42" fontSize="10" fill={T.ink4}>₦1,700</text>
      <text x="0" y="82" fontSize="10" fill={T.ink4}>₦1,600</text>
      <text x="0" y="122" fontSize="10" fill={T.ink4}>₦1,500</text>
      <text x="0" y="162" fontSize="10" fill={T.ink4}>₦1,400</text>
      {/* Area */}
      <path d={`${path} L 580 180 L 40 180 Z`} fill="url(#rateGrad)" />
      {/* Line */}
      <path d={path} fill="none" stroke={T.green} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {/* Dots */}
      {points.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="5" fill="#fff" stroke={T.green} strokeWidth="2.5" />
          {i === points.length - 1 && <circle cx={p.x} cy={p.y} r="11" fill={T.green} fillOpacity="0.15" />}
          <text x={p.x} y="195" textAnchor="middle" fontSize="10" fill={T.ink4} fontWeight="600">{p.m}</text>
        </g>
      ))}
      {/* Annotation on latest */}
      <g transform="translate(490 36)">
        <rect x="-44" y="-30" width="88" height="22" rx="11" fill={T.green} />
        <text x="0" y="-15" textAnchor="middle" fontSize="11" fill="#fff" fontWeight="700">₦1,650 today</text>
      </g>
    </svg>
  );
};

// ============================================================
// 4.3 — CBM RATE
// ============================================================
const CbmRatePage = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={configSidebarItems('cbm')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="CBM rate" breadcrumb={['Admin', 'Configuration', 'CBM rate']} user={tenantUser} />}
  >
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24}}>
      <ConfigSubNav active="cbm" />

      <div>
        <PageHeader
          eyebrow="Pricing"
          title="Base CBM rate"
          subtitle="The base shipping cost per cubic meter in USD. Multiplied by the current USD → NGN rate to compute billing."
        />

        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20, marginBottom: 20}}>
          <Card padding={28} style={{background: `linear-gradient(135deg, ${T.greenForest} 0%, ${T.greenDeep} 100%)`, color: '#fff', border: 'none', boxShadow: T.shadowModal}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16}}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                background: 'rgba(255,255,255,0.18)', color: '#fff',
                padding: '4px 10px', borderRadius: 9999, fontSize: 10, fontWeight: 700,
                letterSpacing: '0.1em', textTransform: 'uppercase',
              }}>
                <Icon name="package" size={11} stroke={2.5} /> Base CBM rate
              </span>
            </div>
            <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 56, letterSpacing: '-0.03em', color: '#fff', lineHeight: 1, marginBottom: 8}}>
              $48.00<span style={{fontSize: 24, color: 'rgba(255,255,255,0.6)', fontWeight: 600, marginLeft: 8}}>per CBM</span>
            </div>
            <div style={{fontSize: 13, color: 'rgba(255,255,255,0.78)'}}>
              Set by <strong style={{color: '#fff'}}>Amara Okafor</strong> on 14 January 2026 — unchanged since onboarding
            </div>
            <div style={{
              marginTop: 24, padding: 16, background: 'rgba(0,0,0,0.18)', borderRadius: 10,
              border: '1px solid rgba(255,255,255,0.1)',
            }}>
              <div style={{fontSize: 10, color: 'rgba(255,255,255,0.55)', textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700, marginBottom: 6}}>Equivalent at current FX</div>
              <div style={{fontFamily: T.mono, fontSize: 14, color: '#fff', fontWeight: 600}}>
                $48.00 × ₦1,650 = <span style={{color: T.greenFlash, fontWeight: 700}}>₦79,200 per CBM</span>
              </div>
            </div>
          </Card>

          <Card padding={24}>
            <SectionHead title="Set a new rate" />
            <div style={{height: 16}} />
            <Field label="CBM rate (USD)" prefix="$" required focused value="52.00" helper="Per cubic meter" />
            <Field label="Reason for change" multiline value="Q3 fuel surcharge pass-through" helper="Logged in audit history." />
            <div style={{background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 8, padding: 14, marginTop: 4, marginBottom: 16}}>
              <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6}}>New computed rate</div>
              <div style={{fontFamily: T.mono, fontSize: 14, color: T.ink, fontWeight: 600}}>
                $52.00 × ₦1,650 = <strong style={{color: T.green}}>₦85,800 per CBM</strong>
              </div>
            </div>
            <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10}}>
              <Button variant="ghost">Cancel</Button>
              <Button variant="accent" icon="check">Update rate</Button>
            </div>
          </Card>
        </div>

        <Card padding={0}>
          <div style={{padding: '18px 20px'}}>
            <SectionHead title="CBM rate history" sub="Every adjustment" action={<Button variant="secondary" size="sm" icon="download">Export</Button>} />
          </div>
          <Table
            columns={[
              {title: 'CBM rate (USD)'},
              {title: 'NGN equivalent (then)'},
              {title: 'Changed by'},
              {title: 'Reason'},
              {title: 'Effective from'},
            ]}
            rows={[
              {cells: [
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}><Mono color={T.green}>$48.00</Mono><Badge variant="primary" size="sm" dot={false}>Current</Badge></div>,
                <Mono>₦69,600</Mono>,
                <UserCell name="Amara Okafor" email="Tenant Admin" />,
                <span style={{fontSize: 12, color: T.ink3}}>Set at onboarding</span>,
                <Mono>14 Jan 2026 12:00</Mono>,
              ]},
            ]}
          />
        </Card>
      </div>
    </div>
  </PageShell>
);

// ============================================================
// 4.4 — CHARGE TYPES
// ============================================================
const ChargeTypesPage = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={configSidebarItems('charges')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Charge types" breadcrumb={['Admin', 'Configuration', 'Charge types']} user={tenantUser} actions={
      <Button variant="primary" icon="plus">Add charge type</Button>
    } />}
  >
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24}}>
      <ConfigSubNav active="charges" />

      <div>
        <PageHeader
          eyebrow="Misc charges"
          title="Custom charge types"
          subtitle="Define your company's miscellaneous charge categories — Customs Examination, Port Handling, Express Clearance, etc. They appear as options when staff add charges to a billing record."
        />

        <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
          <StatCard label="Total types" value="8" sublabel="6 active" accent={<Icon name="card" size={15} stroke={2.2} />} />
          <StatCard label="Applied this month" value="42" trend="+12" trendDir="up" sublabel="charges added" accent={<Icon name="plus" size={15} stroke={2.2} />} />
          <StatCard label="Revenue (NGN)" value="₦642k" trend="+18%" trendDir="up" sublabel="from misc charges" accent={<Icon name="coin" size={15} stroke={2.2} />} />
          <StatCard label="Most-used" value="Customs" sublabel="22 times this month" accent={<Icon name="star" size={15} stroke={2.2} />} />
        </div>

        <Card padding={16} style={{marginBottom: 16}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
            <div style={{display: 'flex', gap: 6}}>
              <Chip active>All <span style={{opacity: 0.5}}>8</span></Chip>
              <Chip count={6}>Active</Chip>
              <Chip count={2}>Inactive</Chip>
            </div>
            <div style={{flex: 1, minWidth: 240}}>
              <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
                <Icon name="search" size={14} color={T.ink4} />
                <input placeholder="Search charge types…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
              </div>
            </div>
          </div>
        </Card>

        <Card padding={0}>
          <Table
            columns={[
              {title: 'Charge name'},
              {title: 'Default amount', align: 'right'},
              {title: 'Applied this month', align: 'right'},
              {title: 'Revenue (NGN)', align: 'right'},
              {title: 'Status'},
              {title: '', width: 100, align: 'right'},
            ]}
            rows={[
              chargeRow({name: 'Customs Examination', desc: 'Physical inspection at Tin Can Port', amount: 15000, applied: 22, revenue: 330000, active: true}),
              chargeRow({name: 'Port Handling Surcharge', desc: 'Apapa terminal handling fee', amount: 8500, applied: 18, revenue: 153000, active: true}),
              chargeRow({name: 'Express Clearance', desc: 'Priority customs processing within 24h', amount: 22000, applied: 6, revenue: 132000, active: true}),
              chargeRow({name: 'Documentation Fee', desc: 'Bill of Lading & manifest processing', amount: 3500, applied: 12, revenue: 42000, active: true}),
              chargeRow({name: 'Demurrage', desc: 'Per-day fee after 7-day free period', amount: 5000, applied: 3, revenue: 75000, active: true}),
              chargeRow({name: 'Cold Chain Premium', desc: 'Refrigerated container handling', amount: 45000, applied: 0, revenue: 0, active: false}),
              chargeRow({name: 'Hazardous Goods', desc: 'Special handling for dangerous cargo', amount: 35000, applied: 1, revenue: 35000, active: true}),
              chargeRow({name: 'Weekend Pickup', desc: 'Saturday warehouse access surcharge', amount: 2500, applied: 0, revenue: 0, active: false}),
            ]}
          />
        </Card>
      </div>
    </div>
    {withModal && <ChargeTypeModal />}
  </PageShell>
);

const chargeRow = ({name, desc, amount, applied, revenue, active}) => ({
  suspended: !active,
  cells: [
    <div>
      <div style={{fontWeight: 600, color: T.ink, fontSize: 13, lineHeight: 1.3}}>{name}</div>
      <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>{desc}</div>
    </div>,
    <Mono>₦{amount.toLocaleString()}</Mono>,
    <Mono color={applied > 0 ? T.ink : T.ink4}>{applied}</Mono>,
    <Mono color={revenue > 0 ? T.green : T.ink4}>{revenue > 0 ? `₦${revenue.toLocaleString()}` : '—'}</Mono>,
    active ? <Badge variant="success">Active</Badge> : <Badge variant="neutral">Inactive</Badge>,
    <div style={{display: 'flex', gap: 6, justifyContent: 'flex-end'}}>
      <button style={{background: 'transparent', border: 0, color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer', padding: '4px 8px'}}>Edit</button>
      <KebabBtn />
    </div>,
  ],
});

const ChargeTypeModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Add a charge type</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>Becomes available when staff add charges to billing.</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Field label="Charge name" required value="Cold Chain Premium" placeholder="e.g. Customs Examination" />
        <Field label="Description" multiline value="Refrigerated container handling — applies to perishables and pharma cargo only." helper="Shown to staff when selecting this charge." />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="Default amount" required prefix="₦" value="45,000" helper="Editable per billing." />
          <Field label="Category" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', cursor: 'pointer'}}>
              <span style={{flex: 1, fontSize: 14, color: T.ink}}>Special handling</span>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0'}}>
          <Check checked />
          <span style={{fontSize: 13, color: T.ink2, fontWeight: 500}}>Active — staff can apply this charge immediately</span>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="check">Save charge type</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 4.5 — NOTIFICATION TEMPLATES
// ============================================================
const NotificationTemplatesPage = () => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={tenantBrand} items={configSidebarItems('notif')} user={tenantUser} />}
    topbar={<TopBar role="admin" title="Notifications" breadcrumb={['Admin', 'Configuration', 'Notifications']} user={tenantUser} />}
  >
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '260px 1fr', gap: 24}}>
      <ConfigSubNav active="notif" />

      <div>
        <PageHeader
          eyebrow="Customer messaging"
          title="Notification channels &amp; templates"
          subtitle="What we send to customers, on which channels, and in what wording. Templates support variables like {customer_name} and {amount_ngn}."
        />

        {/* Channels */}
        <Card style={{marginBottom: 20}}>
          <SectionHead title="Enabled channels" sub="Which channels Acme Logistics uses for outbound customer notifications" />
          <div style={{height: 14}} />
          <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12}}>
            <ChannelToggle channel="SMS" provider="Termii (platform default)" enabled sent="247 sent · last 30d · 96% delivered" />
            <ChannelToggle channel="WhatsApp" provider="Meta Cloud API (platform default)" enabled sent="412 sent · last 30d · 99% delivered" badge="Most reliable" />
            <ChannelToggle channel="Email" provider="Postmark (platform default)" enabled sent="89 sent · last 30d · 94% delivered" />
          </div>
        </Card>

        {/* Two column: events list + editor preview */}
        <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 420px', gap: 20}}>
          <div>
            <SectionHead title="Notification events" sub="Tap an event to edit its templates" />
            <div style={{height: 12}} />
            <NotifEventCard
              icon="coin" iconBg={T.copper} title="Payment notification"
              sub="Sent when a billing record is generated"
              channels={{sms: true, whatsapp: true, email: true}}
              active sent={88}
            />
            <NotifEventCard
              icon="truck" iconBg={T.info} title="Shipment status update"
              sub="Sent on each tracking stage change"
              channels={{sms: false, whatsapp: true, email: true}}
              sent={342}
            />
            <NotifEventCard
              icon="card" iconBg={T.green} title="Release note issued"
              sub="Sent when goods are ready for pickup"
              channels={{sms: true, whatsapp: true, email: true}}
              sent={64}
            />
            <NotifEventCard
              icon="warn" iconBg={T.error} title="Claim filed"
              sub="Sent when a damage or missing claim is logged"
              channels={{sms: false, whatsapp: false, email: true}}
              sent={6}
            />
            <NotifEventCard
              icon="clock" iconBg={T.warning} title="Storage fee reminder"
              sub="Sent daily once storage fees start accruing"
              channels={{sms: true, whatsapp: true, email: false}}
              disabled sent={0}
            />
          </div>

          {/* Editor + preview panel */}
          <div>
            <Card padding={0} style={{position: 'sticky', top: 0}}>
              <div style={{padding: '14px 18px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', gap: 10}}>
                <div style={{width: 30, height: 30, borderRadius: 8, background: T.copper + '18', color: T.copper, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
                  <Icon name="coin" size={14} />
                </div>
                <div style={{flex: 1, minWidth: 0}}>
                  <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink, lineHeight: 1.2}}>Payment notification</div>
                  <div style={{fontSize: 11, color: T.ink4}}>WhatsApp template</div>
                </div>
              </div>
              <div style={{display: 'flex', borderBottom: `1px solid ${T.line}`, padding: '0 14px'}}>
                <ChannelTab label="SMS" />
                <ChannelTab label="WhatsApp" active />
                <ChannelTab label="Email" />
              </div>
              <div style={{padding: 18}}>
                <Field label="Message body" multiline value={"Dear {customer_name},\n\nYour cargo in container {container_number} is cleared and ready for pickup at {warehouse_address}.\n\nAmount due: {amount_ngn}.\n\n— {company_name}"} />
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, fontFamily: T.mono, color: T.ink4, marginTop: -8, marginBottom: 14}}>
                  <span>Variables: <span style={{color: T.green, fontWeight: 600}}>5 used</span></span>
                  <span>168 chars · <span style={{color: T.warning, fontWeight: 700}}>2 segments</span></span>
                </div>
                <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Insert variable</div>
                <div style={{display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 16}}>
                  {['customer_name', 'container_number', 'amount_ngn', 'tracking_code', 'warehouse_address', 'company_name', 'pickup_deadline'].map(v => (
                    <Chip key={v}>{`{${v}}`}</Chip>
                  ))}
                </div>

                {/* Phone preview */}
                <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>Preview · WhatsApp</div>
                <WhatsAppPreview />
                <div style={{display: 'flex', gap: 10, marginTop: 16}}>
                  <Button variant="secondary" size="sm" full icon="mail">Send test</Button>
                  <Button variant="primary" size="sm" full icon="check">Save</Button>
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  </PageShell>
);

const ChannelToggle = ({channel, provider, enabled, sent, badge}) => {
  const ic = channel === 'SMS' ? 'phone' : channel === 'WhatsApp' ? 'phone' : 'mail';
  return (
    <div style={{
      border: `${enabled ? 2 : 1}px solid ${enabled ? T.green + '55' : T.line}`,
      background: enabled ? T.greenTint : '#fff',
      borderRadius: 12, padding: 16,
    }}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: enabled ? T.green : T.line,
          color: enabled ? '#fff' : T.ink4,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name={ic} size={16} stroke={2} />
        </div>
        <div style={{flex: 1, minWidth: 0}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 6}}>
            <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: T.ink}}>{channel}</span>
            {badge && <Badge variant="primary" size="sm" dot={false}>{badge}</Badge>}
          </div>
          <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{provider}</div>
        </div>
        <ToggleSwitch on={enabled} />
      </div>
      <div style={{fontSize: 12, color: T.ink3, lineHeight: 1.4}}>{sent}</div>
    </div>
  );
};

const ToggleSwitch = ({on}) => (
  <div style={{
    width: 36, height: 20, borderRadius: 9999,
    background: on ? T.green : T.lineStrong,
    position: 'relative', cursor: 'pointer',
    transition: 'background .2s',
  }}>
    <div style={{
      position: 'absolute', top: 2, left: on ? 18 : 2,
      width: 16, height: 16, borderRadius: '50%', background: '#fff',
      boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
      transition: 'left .2s',
    }} />
  </div>
);

const NotifEventCard = ({icon, iconBg, title, sub, channels, sent, active, disabled}) => (
  <div style={{
    background: '#fff',
    border: `${active ? 2 : 1}px solid ${active ? T.green : T.line}`,
    borderRadius: 10, padding: 16, marginBottom: 10,
    cursor: 'pointer',
    opacity: disabled ? 0.6 : 1,
  }}>
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 12}}>
      <div style={{
        width: 36, height: 36, borderRadius: 10,
        background: iconBg + '18', color: iconBg,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
      }}>
        <Icon name={icon} size={15} />
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2}}>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink, lineHeight: 1.3}}>{title}</div>
          {disabled && <Badge variant="neutral" size="sm">Disabled</Badge>}
          {active && <Badge variant="primary" size="sm">Editing</Badge>}
        </div>
        <div style={{fontSize: 12, color: T.ink3, marginBottom: 10, lineHeight: 1.4}}>{sub}</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
          <div style={{display: 'flex', gap: 4}}>
            <ChannelDot label="SMS" on={channels.sms} />
            <ChannelDot label="WA" on={channels.whatsapp} />
            <ChannelDot label="EM" on={channels.email} />
          </div>
          {sent > 0 && <span style={{fontSize: 11, color: T.ink4}}>· {sent} sent · last 30d</span>}
        </div>
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <ToggleSwitch on={!disabled} />
        <Icon name="chevright" size={14} color={T.ink4} />
      </div>
    </div>
  </div>
);

const ChannelDot = ({label, on}) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center',
    padding: '2px 7px', borderRadius: 4,
    background: on ? T.greenSoft : T.line,
    color: on ? T.green : T.ink4,
    fontSize: 10, fontWeight: 700, letterSpacing: '0.04em',
  }}>{label}</span>
);

const ChannelTab = ({label, active}) => (
  <button style={{
    padding: '10px 12px',
    background: 'transparent', border: 0,
    fontFamily: T.body, fontWeight: active ? 700 : 500,
    fontSize: 13, color: active ? T.green : T.ink3,
    borderBottom: active ? `2px solid ${T.green}` : '2px solid transparent',
    marginBottom: -1, cursor: 'pointer',
  }}>{label}</button>
);

const WhatsAppPreview = () => (
  <div style={{
    background: '#e5ddd5',
    backgroundImage: 'radial-gradient(circle at 30% 20%, rgba(0,0,0,0.04) 1px, transparent 1px)',
    backgroundSize: '12px 12px',
    borderRadius: 12, padding: 16,
  }}>
    {/* WA header */}
    <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', background: '#075e54', borderRadius: 8, marginBottom: 12, color: '#fff'}}>
      <div style={{width: 28, height: 28, borderRadius: '50%', background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 11, fontFamily: T.display, flexShrink: 0}}>AL</div>
      <div style={{flex: 1}}>
        <div style={{fontSize: 12, fontWeight: 700, lineHeight: 1.1}}>Acme Logistics</div>
        <div style={{fontSize: 9, color: 'rgba(255,255,255,0.7)'}}>online</div>
      </div>
    </div>
    {/* Message bubble */}
    <div style={{
      background: '#dcf8c6', borderRadius: '10px 10px 2px 10px',
      padding: '8px 10px', maxWidth: '88%', marginLeft: 'auto',
      fontSize: 11.5, color: T.ink, lineHeight: 1.45,
      boxShadow: '0 1px 1px rgba(0,0,0,0.08)',
    }}>
      Dear <strong>Ngozi Okonkwo</strong>,<br /><br />
      Your cargo in container <strong>MSCU1234567</strong> is cleared and ready for pickup at 12 Wharf Road, Apapa, Lagos.<br /><br />
      Amount due: <strong>₦49,352.00</strong>.<br /><br />
      — Acme Logistics
      <div style={{textAlign: 'right', fontSize: 9, color: T.ink4, marginTop: 4}}>
        14:32 <span style={{color: '#34b7f1'}}>✓✓</span>
      </div>
    </div>
  </div>
);

Object.assign(window, {
  CompanySettings, DollarRatePage, CbmRatePage, ChargeTypesPage, NotificationTemplatesPage,
});
