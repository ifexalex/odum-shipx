// ============================================================
// Shipx — Customer Portal Screens (Section 10)
// 10.1 My Shipments · 10.2 Shipment Detail · 10.3 Billing
// 10.4 Billing Detail · 10.5 Claims · 10.6 File Claim · 10.7 Account
// ============================================================

const custUser = {name: 'Ngozi Okonkwo', role: 'Customer'};

// Local helpers (avoid cross-file dependency)
const ToggleSwitch = ({on}) => (
  <div style={{
    width: 36, height: 20, borderRadius: 9999,
    background: on ? T.green : T.lineStrong,
    position: 'relative', cursor: 'pointer', flexShrink: 0,
    transition: 'background .2s',
  }}>
    <div style={{
      position: 'absolute', top: 2, left: on ? 18 : 2,
      width: 16, height: 16, borderRadius: '50%', background: '#fff',
      boxShadow: '0 1px 3px rgba(0,0,0,0.2)', transition: 'left .2s',
    }} />
  </div>
);

const BreakdownRow = ({label, amount, accent, total, outstanding, note}) => (
  <tr style={{
    borderBottom: total ? `2px solid ${T.line}` : outstanding ? 'none' : `1px solid ${T.line}`,
    background: outstanding ? T.errorSoft + '88' : accent ? T.greenTint : '#fff',
    borderTop: outstanding ? `2px solid ${T.line}` : 'none',
  }}>
    <td style={{padding: '14px 20px', fontSize: 13, color: T.ink}}>
      {label}
      {note && <div style={{fontSize: 11, color: T.ink4, marginTop: 4, fontStyle: 'italic'}}>{note}</div>}
    </td>
    <td style={{padding: '14px 20px', textAlign: 'right', fontFamily: T.mono, fontSize: 14, fontWeight: 600, color: T.ink, width: 200}}>
      {amount}
    </td>
  </tr>
);

// ============================================================
// CUSTOMER TOP NAV (no sidebar)
// ============================================================
const CustomerTopNav = ({active = 'shipments'}) => (
  <header style={{
    background: T.green, color: '#fff',
    height: 72, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0 32px', fontFamily: T.body, flexShrink: 0,
    boxShadow: T.shadowRest,
  }}>
    {/* Left — Brand + tenant */}
    <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
        <KolaMark size={28} color={T.greenFlash} />
        <ShipxWordmark size={20} color="#fff" xColor={T.copperSoft} />
      </div>
      <div style={{width: 1, height: 24, background: 'rgba(255,255,255,0.2)'}} />
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <div style={{width: 24, height: 24, borderRadius: 5, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 10, fontFamily: T.display}}>AL</div>
        <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: '#fff'}}>Acme Logistics</span>
      </div>
    </div>

    {/* Center — Nav */}
    <nav style={{display: 'flex', gap: 4, alignItems: 'center'}}>
      <CustNavLink label="My shipments" icon="package" active={active === 'shipments'} />
      <CustNavLink label="Billing" icon="coin" active={active === 'billing'} badge={1} />
      <CustNavLink label="Claims" icon="warn" active={active === 'claims'} />
      <CustNavLink label="Account" icon="user" active={active === 'account'} />
    </nav>

    {/* Right — bell + avatar */}
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      <div style={{position: 'relative'}}>
        <button style={{
          width: 38, height: 38, borderRadius: 9999,
          background: 'rgba(255,255,255,0.1)', border: 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', color: '#fff',
        }}>
          <Icon name="bell" size={17} stroke={2} />
        </button>
        <span style={{
          position: 'absolute', top: -2, right: -2,
          background: T.copper, color: '#fff', borderRadius: 999,
          fontSize: 10, fontWeight: 700, minWidth: 18, height: 18, padding: '0 5px',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          border: `2px solid ${T.green}`, lineHeight: 1,
        }}>3</span>
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '4px 14px 4px 4px', borderRadius: 9999, background: 'rgba(255,255,255,0.1)', cursor: 'pointer'}}>
        <Avatar size={30} name="Ngozi Okonkwo" color={T.copper} />
        <span style={{fontFamily: T.body, fontWeight: 600, fontSize: 13, color: '#fff'}}>Ngozi</span>
        <Icon name="chevdown" size={13} color="rgba(255,255,255,0.7)" />
      </div>
    </div>
  </header>
);

const CustNavLink = ({label, icon, active, badge}) => (
  <button style={{
    display: 'inline-flex', alignItems: 'center', gap: 8,
    height: 40, padding: '0 16px', borderRadius: 9999,
    background: active ? 'rgba(255,255,255,0.15)' : 'transparent',
    border: 'none', cursor: 'pointer',
    color: active ? '#fff' : 'rgba(255,255,255,0.75)',
    fontFamily: T.body, fontWeight: active ? 700 : 500, fontSize: 14,
  }}>
    <Icon name={icon} size={15} stroke={2} />
    {label}
    {badge && <span style={{background: T.copper, color: '#fff', borderRadius: 999, padding: '1px 7px', fontSize: 10, fontWeight: 700, minWidth: 18, textAlign: 'center'}}>{badge}</span>}
  </button>
);

const CustShell = ({active, children, bg = T.page}) => (
  <div style={{display: 'flex', flexDirection: 'column', height: '100%', background: bg, fontFamily: T.body, color: T.ink}}>
    <CustomerTopNav active={active} />
    <main style={{flex: 1, overflowY: 'auto', padding: '32px 40px'}}>
      <div style={{maxWidth: 1180, margin: '0 auto'}}>
        {children}
      </div>
    </main>
  </div>
);

// ============================================================
// 10.1 — MY SHIPMENTS (Customer home)
// ============================================================
const CustomerShipments = () => (
  <CustShell active="shipments">
    {/* Greeting */}
    <div style={{marginBottom: 24}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.copper, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>My shipments</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Hello Ngozi 👋 — your shipment is moving.</h2>
      <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>1 active · 13 completed · 1 outstanding balance to settle</p>
    </div>

    {/* Active shipment feature card */}
    <SectionHead title="Active shipment" sub="In transit and getting closer" />
    <div style={{height: 12}} />
    <Card padding={0} style={{marginBottom: 28, overflow: 'hidden'}}>
      <div style={{padding: 24, background: `linear-gradient(135deg, ${T.greenTint} 0%, #fff 60%)`, borderBottom: `1px solid ${T.line}`}}>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 12}}>
          <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
            <div style={{width: 56, height: 56, borderRadius: 12, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
              <Icon name="ship" size={26} stroke={2} />
            </div>
            <div>
              <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
                <Mono color={T.ink} style={{fontSize: 16, fontWeight: 700}}>SHX-2026-NGOZI-014</Mono>
                <Badge variant="info">In transit</Badge>
              </div>
              <div style={{fontSize: 12, color: T.ink3, marginTop: 2}}>Container <Mono color={T.ink2}>MSCU1234567</Mono> · MSC Altair · Voy 248E</div>
            </div>
          </div>
          <div style={{textAlign: 'right'}}>
            <div style={{fontSize: 11, color: T.ink4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Expected arrival</div>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, color: T.green, marginTop: 2, letterSpacing: '-0.01em'}}>14 Aug 2026</div>
            <div style={{fontSize: 11, color: T.ink4}}>in 17 days · Tin Can Port</div>
          </div>
        </div>

        {/* Tracking stepper */}
        <CustomerStepper current={3} />
      </div>
      <div className="sx-grid4" style={{padding: 20, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr) auto', gap: 20, alignItems: 'center'}}>
        <CustStat label="Cartons" value="4" />
        <CustStat label="CBM" value="0.093" />
        <CustStat label="Total cost" value="₦100,008" color={T.warning} />
        <CustStat label="Outstanding" value="₦50,656" color={T.error} />
        <Button variant="primary" trailing="arrowright">View details</Button>
      </div>
    </Card>

    {/* Past shipments */}
    <SectionHead title="Past shipments" sub="Your previous 13 deliveries" action={<a style={{color: T.green, fontWeight: 600, fontSize: 13, cursor: 'pointer'}}>Download history →</a>} />
    <div style={{height: 12}} />
    <Card padding={0}>
      <Table
        columns={[
          {title: 'Tracking code'},
          {title: 'Container'},
          {title: 'Status'},
          {title: 'Cartons', align: 'right'},
          {title: 'Delivered'},
          {title: 'Amount paid', align: 'right'},
          {title: '', width: 80},
        ]}
        rows={[
          {cells: [<Mono>SHX-2026-NGOZI-013</Mono>, <Mono>COSU7194820</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>6</Mono>, <span style={{fontSize: 12, color: T.ink3}}>02 Apr 2026</span>, <Mono>₦110,880</Mono>, <ViewLink />]},
          {cells: [<Mono>SHX-2026-NGOZI-012</Mono>, <Mono>ONEU2847510</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>3</Mono>, <span style={{fontSize: 12, color: T.ink3}}>14 Mar 2026</span>, <Mono>₦42,240</Mono>, <ViewLink />]},
          {cells: [<Mono>SHX-2026-NGOZI-011</Mono>, <Mono>MAEU4729183</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>8</Mono>, <span style={{fontSize: 12, color: T.ink3}}>28 Feb 2026</span>, <Mono>₦147,840</Mono>, <ViewLink />]},
          {cells: [<Mono>SHX-2026-NGOZI-010</Mono>, <Mono>HLBU8473892</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>5</Mono>, <span style={{fontSize: 12, color: T.ink3}}>14 Feb 2026</span>, <Mono>₦97,680</Mono>, <ViewLink />]},
          {cells: [<Mono>SHX-2026-NGOZI-009</Mono>, <Mono>EGHU8472019</Mono>, <Badge variant="success">Delivered</Badge>, <Mono>11</Mono>, <span style={{fontSize: 12, color: T.ink3}}>22 Jan 2026</span>, <Mono>₦178,420</Mono>, <ViewLink />]},
        ]}
      />
    </Card>
  </CustShell>
);

const CustStat = ({label, value, color}) => (
  <div>
    <div style={{fontSize: 11, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.06em'}}>{label}</div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 20, color: color || T.ink, marginTop: 2, letterSpacing: '-0.01em'}}>{value}</div>
  </div>
);

const CustomerStepper = ({current = 3}) => {
  const stages = [
    {label: 'Received', side: 'cn', sub: 'China'},
    {label: 'Packed', side: 'cn', sub: 'Container sealed'},
    {label: 'In transit', side: 'cn', sub: 'At sea'},
    {label: 'Arrived NG', side: 'ng', sub: 'Tin Can Port'},
    {label: 'Customs', side: 'ng', sub: 'Clearance'},
    {label: 'Cleared', side: 'ng', sub: 'Released'},
    {label: 'Ready', side: 'ng', sub: 'For pickup'},
    {label: 'Delivered', side: 'ng', sub: 'Done'},
  ];
  return (
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 4, position: 'relative'}}>
      {stages.map((s, i) => {
        const done = i < current;
        const isCurrent = i === current;
        const color = s.side === 'cn' ? T.info : T.green;
        return (
          <div key={i} style={{flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative'}}>
            {i > 0 && <div style={{position: 'absolute', top: 14, right: '50%', width: '100%', height: 2, background: done ? color : T.line, zIndex: 0}} />}
            <div style={{
              width: 30, height: 30, borderRadius: '50%',
              background: done ? color : isCurrent ? '#fff' : T.muted,
              border: `${isCurrent ? 3 : 2}px solid ${done || isCurrent ? color : T.lineStrong}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', position: 'relative', zIndex: 1,
              boxShadow: isCurrent ? `0 0 0 6px ${color}22` : 'none',
            }}>
              {done ? <Icon name="check" size={14} color="#fff" stroke={3} /> :
               isCurrent ? <div style={{width: 8, height: 8, borderRadius: '50%', background: color, animation: 'pulse 1.5s infinite'}} /> : null}
            </div>
            <div style={{marginTop: 8, textAlign: 'center'}}>
              <div style={{fontSize: 11, fontWeight: 700, color: done || isCurrent ? T.ink : T.ink4}}>{s.label}</div>
              <div style={{fontSize: 10, color: T.ink4, marginTop: 1}}>{s.sub}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ============================================================
// 10.2 — SHIPMENT DETAIL
// ============================================================
const CustomerShipmentDetail = () => (
  <CustShell active="shipments">
    <a style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: T.green, fontWeight: 600, fontSize: 13, marginBottom: 16, cursor: 'pointer'}}>
      <Icon name="arrowleft" size={14} stroke={2.5} /> My shipments
    </a>

    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{width: 56, height: 56, borderRadius: 12, background: T.infoSoft, color: T.info, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="ship" size={26} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 22, color: T.ink, margin: 0, letterSpacing: '-0.01em'}}>SHX-2026-NGOZI-014</h1>
            <Badge variant="info">In transit</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>
            Container <Mono color={T.ink}>MSCU1234567</Mono> · MSC Altair · Last updated 5 hours ago
          </div>
        </div>
      </div>
      <Button variant="secondary" icon="bell">Notify me on update</Button>
    </div>

    {/* Tracking card */}
    <Card padding={28} style={{marginBottom: 24}}>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20, flexWrap: 'wrap', gap: 12}}>
        <SectionHead title="Tracking" sub="Where your cargo is right now" />
        <div style={{textAlign: 'right'}}>
          <div style={{fontSize: 11, color: T.ink4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Expected pickup window</div>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, color: T.green, marginTop: 2}}>16 – 18 Aug 2026</div>
        </div>
      </div>
      <CustomerStepper current={3} />
      <div style={{marginTop: 20, padding: 14, background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 10, display: 'flex', alignItems: 'center', gap: 12}}>
        <Icon name="ship" size={18} color={T.green} />
        <div style={{flex: 1, fontSize: 13, color: T.greenDeep}}>
          <strong>Currently at sea</strong> — your container left Guangzhou Baiyun on 01 Aug and is expected at Tin Can Port on 14 Aug. We'll notify you the moment it docks.
        </div>
      </div>
    </Card>

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20, marginBottom: 20}}>
      {/* My cartons */}
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="My cartons" sub="4 cartons · 0.093 CBM total" />
        </div>
        <Table
          dense
          columns={[
            {title: 'Tag'},
            {title: 'Description'},
            {title: 'Weight', align: 'right'},
            {title: 'CBM', align: 'right'},
            {title: 'Received'},
          ]}
          rows={[
            {cells: [<Mono>SHX-00001</Mono>, <span style={{fontSize: 13, color: T.ink}}>Electronics (mixed)</span>, <Mono>12.8 kg</Mono>, <Mono color={T.green}>0.030</Mono>, <span style={{fontSize: 12, color: T.ink3}}>10 Apr</span>]},
            {cells: [<Mono>SHX-00002</Mono>, <span style={{fontSize: 13, color: T.ink}}>Clothing (assorted)</span>, <Mono>8.5 kg</Mono>, <Mono color={T.green}>0.021</Mono>, <span style={{fontSize: 12, color: T.ink3}}>10 Apr</span>]},
            {cells: [<Mono>SHX-00003</Mono>, <span style={{fontSize: 13, color: T.ink}}>Phone accessories</span>, <Mono>6.2 kg</Mono>, <Mono color={T.green}>0.018</Mono>, <span style={{fontSize: 12, color: T.ink3}}>10 Apr</span>]},
            {cells: [<Mono>SHX-00004</Mono>, <span style={{fontSize: 13, color: T.ink}}>Spare parts</span>, <Mono>9.1 kg</Mono>, <Mono color={T.green}>0.024</Mono>, <span style={{fontSize: 12, color: T.ink3}}>10 Apr</span>]},
          ]}
        />
      </Card>

      {/* Billing + documents */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <Card>
          <SectionHead title="Billing" action={<a style={{color: T.green, fontWeight: 600, fontSize: 12, cursor: 'pointer'}}>View full →</a>} />
          <div style={{height: 8}} />
          <Kvp label="Shipping cost" value={<Mono>₦73,656</Mono>} />
          <Kvp label="Misc fees" value={<Mono>₦23,500</Mono>} />
          <Kvp label="Adjustments" value={<Mono color={T.success}>−₦5,648</Mono>} />
          <Kvp label="Total" value={<Mono style={{fontWeight: 700}}>₦100,008</Mono>} />
          <Kvp label="Paid" value={<Mono color={T.success}>₦49,352</Mono>} />
          <Kvp label="Outstanding" value={<Mono color={T.error} style={{fontSize: 15, fontWeight: 700}}>₦50,656</Mono>} divider={false} />
          <div style={{paddingTop: 12, marginTop: 8, borderTop: `1px solid ${T.line}`}}>
            <Button variant="accent" full icon="coin">Pay outstanding</Button>
          </div>
        </Card>

        <Card>
          <SectionHead title="Documents" />
          <div style={{height: 12}} />
          <DocLink icon="file" name="Packing list" sub="PL-20260415-001 · 4 cartons · 12 KB" />
          <DocLink icon="card" name="Release note" sub="Generated when payment is settled" disabled />
        </Card>
      </div>
    </div>

    {/* File a claim */}
    <Card padding={16} style={{background: T.warningSoft + '55', borderColor: T.warning + '33', display: 'flex', alignItems: 'center', gap: 14}}>
      <div style={{width: 40, height: 40, borderRadius: 10, background: T.warningSoft, color: T.warning, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
        <Icon name="warn" size={18} stroke={2.2} />
      </div>
      <div style={{flex: 1}}>
        <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink}}>Notice damage when your cargo arrives?</div>
        <div style={{fontSize: 12, color: T.ink3, marginTop: 2}}>File a claim within 7 days of receiving your shipment. We'll inspect and respond within 48 hours.</div>
      </div>
      <Button variant="secondary" size="sm" icon="plus">File a claim</Button>
    </Card>
  </CustShell>
);

const DocLink = ({icon, name, sub, disabled}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '10px 0', borderBottom: `1px dashed ${T.line}`,
    opacity: disabled ? 0.55 : 1, cursor: disabled ? 'not-allowed' : 'pointer',
  }}>
    <div style={{width: 32, height: 32, borderRadius: 8, background: T.muted, color: T.ink3, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
      <Icon name={icon} size={14} />
    </div>
    <div style={{flex: 1}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>{name}</div>
      <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{sub}</div>
    </div>
    {!disabled && <Icon name="download" size={14} color={T.green} />}
  </div>
);

// ============================================================
// 10.3 — BILLING (Customer)
// ============================================================
const CustomerBilling = () => (
  <CustShell active="billing">
    <div style={{marginBottom: 24}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.copper, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Billing</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>One bill to settle.</h2>
      <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>1 outstanding · 13 settled across all your shipments</p>
    </div>

    {/* Outstanding banner */}
    <Card padding={24} style={{
      marginBottom: 24,
      background: `linear-gradient(135deg, ${T.warningSoft} 0%, #fff 100%)`,
      border: `1px solid ${T.warning}33`,
      borderLeft: `4px solid ${T.warning}`,
    }}>
      <div style={{display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap'}}>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{fontSize: 11, color: T.warningStrong, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6}}>You owe</div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 40, color: T.warningStrong, letterSpacing: '-0.02em', lineHeight: 1}}>₦50,656</div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 8}}>
            Pay this to receive your cargo on container <Mono color={T.ink}>MSCU1234567</Mono>. Goods are held until full settlement.
          </div>
        </div>
        <div style={{display: 'flex', gap: 10}}>
          <Button variant="secondary" icon="phone">Support</Button>
          <Button variant="accent" icon="coin">Pay now</Button>
        </div>
      </div>
    </Card>

    {/* Active billing card */}
    <SectionHead title="Active billing" />
    <div style={{height: 12}} />
    <Card padding={20} style={{marginBottom: 24}}>
      <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 12}}>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4}}>
            <Mono color={T.ink} style={{fontWeight: 700}}>BL-20260728-001</Mono>
            <Badge variant="warning">Partially paid</Badge>
          </div>
          <div style={{fontSize: 12, color: T.ink3}}>Container <Mono color={T.ink2}>MSCU1234567</Mono> · billed 28 July 2026</div>
        </div>
        <Button variant="ghost" trailing="arrowright" size="sm">View detail</Button>
      </div>
      <div className="sx-grid3" style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12}}>
        <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 8}}>
          <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Total</div>
          <div style={{fontFamily: T.mono, fontWeight: 700, fontSize: 18, color: T.ink, marginTop: 4}}>₦100,008</div>
        </div>
        <div style={{padding: 14, background: T.successSoft + '66', border: `1px solid ${T.success}33`, borderRadius: 8}}>
          <div style={{fontSize: 11, color: T.successStrong, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Paid</div>
          <div style={{fontFamily: T.mono, fontWeight: 700, fontSize: 18, color: T.successStrong, marginTop: 4}}>₦49,352</div>
        </div>
        <div style={{padding: 14, background: T.errorSoft + '66', border: `1px solid ${T.error}33`, borderRadius: 8}}>
          <div style={{fontSize: 11, color: T.errorStrong, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Outstanding</div>
          <div style={{fontFamily: T.mono, fontWeight: 700, fontSize: 18, color: T.errorStrong, marginTop: 4}}>₦50,656</div>
        </div>
      </div>
    </Card>

    {/* Settled billing accordion */}
    <Card padding={0}>
      <div style={{padding: '14px 20px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer'}}>
        <Icon name="chevdown" size={14} color={T.ink3} />
        <span style={{fontSize: 14, fontWeight: 600, color: T.ink, flex: 1}}>13 settled billing records</span>
        <span style={{fontSize: 12, color: T.ink4, fontFamily: T.mono}}>₦1,810,000 total paid · all time</span>
      </div>
      <Table
        dense
        columns={[
          {title: 'Reference'},
          {title: 'Container'},
          {title: 'Total', align: 'right'},
          {title: 'Status'},
          {title: 'Billed'},
          {title: '', width: 80},
        ]}
        rows={[
          {cells: [<Mono>BL-20260402-018</Mono>, <Mono>COSU7194820</Mono>, <Mono>₦110,880</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>02 Apr 2026</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260314-008</Mono>, <Mono>ONEU2847510</Mono>, <Mono>₦42,240</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 Mar 2026</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260228-022</Mono>, <Mono>MAEU4729183</Mono>, <Mono>₦147,840</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>28 Feb 2026</span>, <ViewLink />]},
          {cells: [<Mono>BL-20260214-031</Mono>, <Mono>HLBU8473892</Mono>, <Mono>₦97,680</Mono>, <Badge variant="success">Paid</Badge>, <span style={{fontSize: 12, color: T.ink3}}>14 Feb 2026</span>, <ViewLink />]},
        ]}
      />
    </Card>
  </CustShell>
);

// ============================================================
// 10.4 — BILLING DETAIL (Customer) + Payment Form
// ============================================================
const CustomerBillingDetail = ({withDisputeModal} = {}) => (
  <CustShell active="billing">
    <a style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: T.green, fontWeight: 600, fontSize: 13, marginBottom: 16, cursor: 'pointer'}}>
      <Icon name="arrowleft" size={14} stroke={2.5} /> Billing
    </a>

    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div>
        <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
          <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 22, color: T.ink, margin: 0}}>BL-20260728-001</h1>
          <Badge variant="warning">Partially paid</Badge>
        </div>
        <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>Container <Mono color={T.ink}>MSCU1234567</Mono> · billed 28 July 2026</div>
      </div>
    </div>

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Breakdown */}
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Cost breakdown" sub="What you're paying for" />
        </div>
        <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: T.body, fontSize: 13}}>
          <tbody>
            <BreakdownRow
              label={<>
                <div style={{fontWeight: 700, color: T.ink}}>Shipping (CBM)</div>
                <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>0.93 cubic meters at your tenant's CBM rate</div>
              </>}
              amount="₦73,656"
              accent
            />
            <BreakdownRow
              label={<div style={{color: T.ink2}}>Customs Examination fee</div>}
              amount="₦15,000"
            />
            <BreakdownRow
              label={<div style={{color: T.ink2}}>Port Handling Surcharge</div>}
              amount="₦8,500"
            />
            <BreakdownRow
              label={<div style={{color: T.ink2}}>Carryover from previous billing</div>}
              amount="₦8,500"
              note="Outstanding from BL-20260712-031"
            />
            <BreakdownRow
              label={<span style={{color: T.success, fontWeight: 600}}>CBM dispute adjustment</span>}
              amount={<span style={{color: T.success}}>−₦5,648</span>}
              note="Your dispute was approved — measurement corrected"
            />
            <BreakdownRow
              label={<strong style={{color: T.ink, fontSize: 14}}>Total due</strong>}
              amount={<strong style={{color: T.ink, fontSize: 16}}>₦100,008</strong>}
              total
            />
            <BreakdownRow
              label={<span style={{color: T.success}}>Already paid · 28 Jul</span>}
              amount={<span style={{color: T.success}}>−₦49,352</span>}
            />
            <BreakdownRow
              label={<strong style={{color: T.error, fontSize: 15}}>Outstanding</strong>}
              amount={<strong style={{color: T.error, fontSize: 22, fontFamily: T.display, letterSpacing: '-0.01em'}}>₦50,656</strong>}
              outstanding
            />
          </tbody>
        </table>
      </Card>

      {/* Pay panel */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
        <Card padding={20} style={{background: `linear-gradient(135deg, ${T.greenForest} 0%, ${T.greenDeep} 100%)`, color: '#fff', border: 'none'}}>
          <div style={{fontSize: 11, color: 'rgba(255,255,255,0.7)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Pay now to collect your cargo</div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 32, color: '#fff', marginTop: 6, letterSpacing: '-0.02em'}}>₦50,656</div>
          <Button variant="accent" full size="lg" icon="coin" style={{marginTop: 16}}>Pay with Paystack</Button>
          <div style={{textAlign: 'center', fontSize: 11, color: 'rgba(255,255,255,0.55)', marginTop: 10}}>Card · Bank transfer · USSD · Mobile money</div>
        </Card>

        <Card>
          <SectionHead title="Already paid by bank transfer?" sub="Notify our team — we'll confirm within 2 hours" />
          <div style={{height: 12}} />
          <Field label="Amount paid" prefix="₦" value="50,656" />
          <Field label="Bank reference" value="" placeholder="e.g. ZNB-2026-04792" />
          <Field label="Notes" multiline value="" placeholder="Any extra info…" optional />
          <Button variant="secondary" full icon="mail">Notify our team</Button>
        </Card>

        <Card padding={16} style={{background: T.muted}}>
          <div style={{display: 'flex', alignItems: 'flex-start', gap: 10}}>
            <Icon name="warn" size={16} color={T.warning} />
            <div style={{flex: 1}}>
              <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Think your CBM is wrong?</div>
              <div style={{fontSize: 12, color: T.ink3, margin: '4px 0 8px'}}>If you measured your cartons yourself and they don't match what we charged, file a dispute and we'll re-measure.</div>
              <Button variant="ghost" size="sm" icon="warn">File CBM dispute</Button>
            </div>
          </div>
        </Card>
      </div>
    </div>

    {withDisputeModal && <CbmDisputeModal />}
  </CustShell>
);

const CbmDisputeModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Dispute your CBM measurement</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>BL-20260728-001 · MSCU1234567</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 16}}>
          <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, textAlign: 'center'}}>
            <div style={{fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>We measured</div>
            <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 28, color: T.ink, letterSpacing: '-0.02em'}}>0.93</div>
            <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>CBM (China warehouse)</div>
          </div>
          <div style={{padding: 14, background: T.errorSoft, border: `2px solid ${T.error}`, borderRadius: 10, textAlign: 'center', boxShadow: `0 0 0 4px ${T.error}22`}}>
            <div style={{fontSize: 10, fontWeight: 700, color: T.errorStrong, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>You measured</div>
            <Field>
              <input type="number" defaultValue="0.86" style={{
                width: '100%', textAlign: 'center', fontFamily: T.display, fontWeight: 800, fontSize: 28,
                color: T.errorStrong, letterSpacing: '-0.02em',
                border: 'none', background: 'transparent', outline: 'none',
              }} />
            </Field>
            <div style={{fontSize: 11, color: T.errorStrong, marginTop: 2}}>CBM (your measurement)</div>
          </div>
        </div>

        <Field label="Why do you think the measurement is wrong?" required multiline value="" placeholder="Describe how you measured (e.g. tape measure, dimensions per carton) and why the difference matters." />
        <Field label="Photos of your cartons (recommended)" optional>
          <div style={{border: `1.5px dashed ${T.lineStrong}`, borderRadius: 10, padding: 20, textAlign: 'center', background: T.muted}}>
            <Icon name="upload" size={24} color={T.ink3} stroke={2} />
            <div style={{fontSize: 13, color: T.ink, fontWeight: 600, marginTop: 8}}>Drag photos here or click to browse</div>
            <div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>JPG · PNG · up to 10MB each · max 6 photos</div>
          </div>
        </Field>

        <Banner variant="info" title="What happens next">
          The Nigeria office acknowledges your dispute within 24 hours. If they can't resolve it, they escalate to the China office to re-measure. Typical resolution: <strong>2–4 business days</strong>.
        </Banner>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="check">Submit dispute</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 10.5 — CLAIMS (Customer)
// ============================================================
const CustomerClaims = () => (
  <CustShell active="claims">
    <div style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div>
        <div style={{fontSize: 12, fontWeight: 700, color: T.copper, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Claims</div>
        <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>2 active, 8 resolved.</h2>
        <p style={{fontSize: 14, color: T.ink3, margin: '6px 0 0'}}>File a damage claim within 7 days of pickup. We investigate and respond within 48 hours.</p>
      </div>
      <Button variant="accent" icon="plus">File a claim</Button>
    </div>

    {/* Filter chips + count */}
    <div style={{display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
        <Chip active>All <span style={{opacity: 0.5}}>10</span></Chip>
        <Chip count={1}>Filed</Chip>
        <Chip count={1}>Under inspection</Chip>
        <Chip count={8}>Resolved</Chip>
      </div>
      <div style={{flex: 1, minWidth: 200}}>
        <div style={{position: 'relative', height: 36, background: '#fff', border: `1px solid ${T.line}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
          <Icon name="search" size={14} color={T.ink4} />
          <input placeholder="Search by reference, container, description…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
        </div>
      </div>
      <span style={{fontSize: 12, color: T.ink4}}>Showing <strong style={{color: T.ink2}}>6</strong> of <strong style={{color: T.ink2}}>10</strong></span>
    </div>

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginBottom: 20}}>
      <ClaimCard
        refId="DC-20260728-001" container="HLBU9384712"
        cartons={['SHX-00051']} desc="Water damage to bottom of carton — contents soaked"
        status="filed" filed="Today, 12:14" hint="Inspection scheduled · we'll update you within 24 hours"
      />
      <ClaimCard
        refId="DC-20260720-004" container="ONEU2847510"
        cartons={['SHX-00094']} desc="Crushed corner — visible dent on the box"
        status="inspection" filed="20 July" hint="Delegate visit in progress · Adesoji Akinyemi assigned"
      />
      <ClaimCard
        refId="DC-20260612-001" container="MAEU4729183"
        cartons={['SHX-00118']} desc="Liquid spillage damaged 2 items inside"
        status="resolved" filed="12 June" hint="Resolved with refund · ₦24,000 issued to your account"
      />
      <ClaimCard
        refId="DC-20260514-007" container="HLBU8473892"
        cartons={['SHX-00154']} desc="Cosmetic dent on outer carton"
        status="resolved" filed="14 May" hint="Inspected · no compensation (cosmetic only)"
      />
      <ClaimCard
        refId="DC-20260428-012" container="COSU7194820"
        cartons={['SHX-00203', 'SHX-00204']} desc="Two cartons arrived with torn packaging"
        status="resolved" filed="28 April" hint="Resolved with discount · ₦12,000 off next shipment"
      />
      <ClaimCard
        refId="DC-20260402-009" container="ONEU2847510"
        cartons={['SHX-00188']} desc="Electronics not working on arrival"
        status="resolved" filed="2 April" hint="Resolved with refund · ₦38,500 issued to your account"
      />
    </div>

    {/* Load more */}
    <div style={{display: 'flex', justifyContent: 'center', marginBottom: 8}}>
      <Button variant="secondary" icon="chevdown">Load 4 more resolved claims</Button>
    </div>
  </CustShell>
);

const ClaimCard = ({refId, container, cartons, desc, status, filed, hint}) => {
  const badge = {
    filed: <Badge variant="warning">Filed · awaiting inspection</Badge>,
    inspection: <Badge variant="info">Under inspection</Badge>,
    resolved: <Badge variant="success">Resolved</Badge>,
  }[status];
  return (
    <Card padding={20}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10}}>
        <Mono color={T.ink}>{refId}</Mono>
        {badge}
      </div>
      <div style={{fontSize: 13, color: T.ink2, marginBottom: 12, fontStyle: 'italic'}}>"{desc}"</div>
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12}}>
        <div>
          <div style={{fontSize: 10, color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Container</div>
          <Mono color={T.ink} style={{fontSize: 12, marginTop: 2}}>{container}</Mono>
        </div>
        <div>
          <div style={{fontSize: 10, color: T.ink4, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Cartons</div>
          <div style={{display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 2}}>
            {cartons.map(c => <span key={c} style={{fontFamily: T.mono, fontSize: 10, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>{c}</span>)}
          </div>
        </div>
      </div>
      <div style={{padding: 10, background: T.muted, borderRadius: 8, fontSize: 12, color: T.ink2, marginBottom: 12, lineHeight: 1.45}}>
        <strong style={{color: T.green}}>Status:</strong> {hint}
      </div>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <span style={{fontSize: 11, color: T.ink4}}>Filed {filed}</span>
        <Button variant="ghost" size="sm" trailing="arrowright">View detail</Button>
      </div>
    </Card>
  );
};

// ============================================================
// 10.6 — FILE A DAMAGE CLAIM (3-step)
// ============================================================
const CustomerFileClaim = ({step = 1}) => (
  <CustShell active="claims">
    <a style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: T.green, fontWeight: 600, fontSize: 13, marginBottom: 16, cursor: 'pointer'}}>
      <Icon name="arrowleft" size={14} stroke={2.5} /> My claims
    </a>

    <div style={{maxWidth: 720, margin: '0 auto'}}>
      <PageHeader
        eyebrow="File a damage claim"
        title="Tell us what's damaged."
        subtitle="We'll inspect within 24 hours and respond with a resolution within 48."
      />

      <WizardSteps current={step} />
      <div style={{height: 20}} />

      {step === 1 && (
        <Card padding={28}>
          <SectionHead title="Step 1 · Damage details" sub="Help us understand what happened" />
          <div style={{height: 16}} />
          <Field label="Which shipment?" required>
            <div style={{
              height: 56, background: '#fff', border: `2px solid ${T.green}`, borderRadius: 8,
              display: 'flex', alignItems: 'center', padding: '0 14px', gap: 12,
              boxShadow: `0 0 0 3px rgba(45,196,56,0.15)`, cursor: 'pointer',
            }}>
              <Icon name="container" size={18} color={T.info} />
              <div style={{flex: 1}}>
                <Mono color={T.ink} style={{fontSize: 13, fontWeight: 700}}>MSCU1234567</Mono>
                <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>Delivered 28 July · 4 cartons · still within claim window</div>
              </div>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>

          <Field label="Which cartons are damaged?" required helper="Select all that apply">
            <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8}}>
              <CartonCheck tag="SHX-00001" desc="Electronics (mixed)" selected />
              <CartonCheck tag="SHX-00002" desc="Clothing (assorted)" />
              <CartonCheck tag="SHX-00003" desc="Phone accessories" selected />
              <CartonCheck tag="SHX-00004" desc="Spare parts (auto)" />
            </div>
          </Field>

          <Field label="Describe the damage" required multiline value="The bottom of carton SHX-00001 was wet through and several phones inside were exposed to moisture. SHX-00003 has a crushed corner and the items inside are dented." helper="Minimum 20 characters — be specific. Mention how/when you noticed it." />

          <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 16}}>
            <Button variant="ghost">Cancel</Button>
            <Button variant="primary" trailing="arrowright">Next · upload photos</Button>
          </div>
        </Card>
      )}

      {step === 2 && (
        <Card padding={28}>
          <SectionHead title="Step 2 · Upload evidence" sub="Photos help us resolve faster" />
          <div style={{height: 16}} />

          <Banner variant="info" title="Tip: Take clear photos">
            Photograph the damage from multiple angles, include the carton tag in the frame, and show the contents inside if possible. Photos taken within 24 hours of pickup carry the most weight.
          </Banner>
          <div style={{height: 16}} />

          {/* Upload zone */}
          <div style={{
            border: `2px dashed ${T.green}55`, borderRadius: 12, padding: '40px 20px',
            background: T.greenTint, textAlign: 'center', marginBottom: 14,
          }}>
            <div style={{width: 56, height: 56, margin: '0 auto 14px', borderRadius: 14, background: T.green, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
              <Icon name="upload" size={24} stroke={2.5} />
            </div>
            <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, color: T.ink}}>Drop photos here or click to browse</div>
            <div style={{fontSize: 13, color: T.ink3, marginTop: 4}}>JPG · PNG · max 10MB each · up to 10 photos</div>
          </div>

          {/* Uploaded thumbnails */}
          <div style={{fontSize: 11, color: T.ink3, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>4 photos uploaded</div>
          <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10}}>
            {[
              {tag: 'SHX-00001', side: 'Bottom of carton'},
              {tag: 'SHX-00001', side: 'Contents soaked'},
              {tag: 'SHX-00003', side: 'Crushed corner'},
              {tag: 'SHX-00003', side: 'Dented items'},
            ].map((p, i) => (
              <div key={i} style={{position: 'relative', borderRadius: 8, overflow: 'hidden', background: `linear-gradient(135deg, ${T.line}, ${T.lineStrong})`, aspectRatio: '1', border: `1px solid ${T.lineStrong}`}}>
                <div style={{height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4}}>
                  <Icon name="package" size={32} stroke={1.5} />
                </div>
                <button style={{position: 'absolute', top: 4, right: 4, width: 22, height: 22, borderRadius: '50%', background: 'rgba(0,0,0,0.55)', border: 0, color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                  <Icon name="x" size={11} stroke={2.5} />
                </button>
                <div style={{position: 'absolute', bottom: 4, left: 4, right: 4, background: 'rgba(0,0,0,0.7)', color: '#fff', padding: '4px 6px', borderRadius: 4, fontSize: 9}}>
                  <div style={{fontFamily: T.mono, fontWeight: 700}}>{p.tag}</div>
                  <div style={{opacity: 0.8, marginTop: 1}}>{p.side}</div>
                </div>
              </div>
            ))}
          </div>

          <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 24}}>
            <Button variant="ghost" icon="arrowleft">Back</Button>
            <Button variant="primary" trailing="arrowright">Next · review</Button>
          </div>
        </Card>
      )}

      {step === 3 && (
        <Card padding={28}>
          <SectionHead title="Step 3 · Review & submit" />
          <div style={{height: 16}} />
          <Banner variant="success" title="Looks good. Here's a summary of what you're filing:">
            We'll send you SMS + WhatsApp confirmation right after you submit. Inspection starts within 24 hours.
          </Banner>
          <div style={{height: 16}} />
          <Kvp label="Shipment" value={<Mono color={T.ink}>MSCU1234567</Mono>} />
          <Kvp label="Affected cartons" value={
            <div style={{display: 'inline-flex', gap: 4}}>
              <span style={{fontFamily: T.mono, fontSize: 11, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>SHX-00001</span>
              <span style={{fontFamily: T.mono, fontSize: 11, padding: '2px 6px', background: T.errorSoft, color: T.errorStrong, borderRadius: 4, fontWeight: 700}}>SHX-00003</span>
            </div>
          } />
          <Kvp label="Description" value={<span style={{fontSize: 12, fontStyle: 'italic'}}>"Bottom of carton wet through, phones exposed to moisture. Crushed corner on second carton."</span>} />
          <Kvp label="Photos attached" value="4 photos" />
          <Kvp label="Filed by" value="Ngozi Okonkwo · today at 14:32" divider={false} />

          <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 16}}>
            <Button variant="ghost" icon="arrowleft">Back · edit photos</Button>
            <Button variant="accent" icon="check">Submit claim</Button>
          </div>
        </Card>
      )}
    </div>
  </CustShell>
);

const CartonCheck = ({tag, desc, selected}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    border: `${selected ? 2 : 1}px solid ${selected ? T.green : T.line}`,
    borderRadius: 8, padding: '10px 12px',
    background: selected ? T.greenTint : '#fff', cursor: 'pointer',
  }}>
    <Check checked={selected} />
    <div style={{flex: 1, minWidth: 0}}>
      <Mono color={T.ink} style={{fontSize: 12, fontWeight: 700}}>{tag}</Mono>
      <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>{desc}</div>
    </div>
  </div>
);

// ============================================================
// 10.7 — ACCOUNT (Customer)
// ============================================================
const CustomerAccount = ({tab = 'profile'}) => (
  <CustShell active="account">
    <PageHeader
      eyebrow="Account"
      title="Your details and preferences"
      subtitle="Update your contact info, notification channels, and privacy choices."
    />

    <Tabs tabs={['Profile', 'Notifications', 'Privacy']} active={
      tab === 'profile' ? 'Profile' :
      tab === 'notifications' ? 'Notifications' : 'Privacy'
    } />

    {tab === 'profile' && <CustomerProfileTab2 />}
    {tab === 'notifications' && <CustomerNotificationsTab />}
    {tab === 'privacy' && <CustomerPrivacyTab />}
  </CustShell>
);

const CustomerProfileTab2 = () => (
  <Card padding={28}>
    <div style={{display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24}}>
      <Avatar size={72} name="Ngozi Okonkwo" color={T.copper} />
      <div>
        <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, color: T.ink}}>Ngozi Okonkwo</div>
        <div style={{fontSize: 13, color: T.ink3}}>Customer since 14 February 2026 · 14 shipments</div>
      </div>
    </div>

    <SectionHead title="Contact info" sub="Email is locked once an account is created. Other fields can be updated." />
    <div style={{height: 16}} />
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
      <Field label="Full name" value="Ngozi Okonkwo" disabled />
      <Field label="Email address" value="ngozi.okonkwo@gmail.com" disabled icon="mail" helper="Contact support to change your email." />
    </div>
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
      <Field label="Phone number" required value="+234 801 234 5678" icon="phone" />
      <Field label="WhatsApp number" value="+234 801 234 5678" optional icon="phone" helper="Leave blank to use your phone number." />
    </div>
    <Field label="Pickup address" multiline value={"14 Adeniran Ogunsanya St\nSurulere, Lagos 101241\nNigeria"} helper="Used if you choose home delivery as an add-on service." />

    <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
      <Button variant="ghost">Discard</Button>
      <Button variant="primary" icon="check">Update profile</Button>
    </div>
  </Card>
);

const CustomerNotificationsTab = () => (
  <Card padding={28}>
    <SectionHead title="How would you like updates?" sub="Choose which channels we use to keep you informed" />
    <div style={{height: 20}} />

    <NotifChannelRow
      icon="phone" channel="SMS" sub="Important transactional alerts only — payment due, status changes, claims"
      enabled deliveryRate="96% delivery rate" cost="Standard SMS rates"
    />
    <NotifChannelRow
      icon="phone" channel="WhatsApp" sub="Richer formatting with carton details and photos · most reliable"
      enabled deliveryRate="99% delivery rate" cost="Free over Wi-Fi or data" recommended
    />
    <NotifChannelRow
      icon="mail" channel="Email" sub="Receipts, invoices, monthly statements"
      enabled deliveryRate="94% delivery rate" cost="No extra cost" last
    />

    <div style={{marginTop: 16, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
      <SectionHead title="Notify me when…" />
      <div style={{height: 12}} />
      <NotifTypeRow label="My cargo arrives in Nigeria" />
      <NotifTypeRow label="Customs clearance completes" />
      <NotifTypeRow label="My release note is issued" />
      <NotifTypeRow label="Payment is due" />
      <NotifTypeRow label="A claim or dispute updates" />
      <NotifTypeRow label="Marketing offers from Acme Logistics" disabled last />
    </div>

    <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 24, paddingTop: 16, borderTop: `1px solid ${T.line}`}}>
      <Button variant="primary" icon="check">Save preferences</Button>
    </div>
  </Card>
);

const NotifChannelRow = ({icon, channel, sub, enabled, deliveryRate, cost, recommended, last}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 16,
    padding: '16px 0', borderBottom: last ? 'none' : `1px solid ${T.line}`,
  }}>
    <div style={{
      width: 40, height: 40, borderRadius: 10,
      background: enabled ? T.greenSoft : T.line, color: enabled ? T.green : T.ink4,
      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
    }}>
      <Icon name={icon} size={16} stroke={2} />
    </div>
    <div style={{flex: 1, minWidth: 0}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink}}>{channel}</span>
        {recommended && <Badge variant="primary" size="sm" dot={false}>Recommended</Badge>}
      </div>
      <div style={{fontSize: 12, color: T.ink3, marginTop: 3}}>{sub}</div>
      <div style={{fontSize: 11, color: T.ink4, marginTop: 4, display: 'flex', gap: 10}}>
        <span><span style={{color: T.success, fontWeight: 600}}>●</span> {deliveryRate}</span>
        <span>· {cost}</span>
      </div>
    </div>
    <ToggleSwitch on={enabled} />
  </div>
);

const NotifTypeRow = ({label, disabled, last}) => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '10px 0', borderBottom: last ? 'none' : `1px dashed ${T.line}`,
    opacity: disabled ? 0.55 : 1,
  }}>
    <span style={{fontSize: 13, color: T.ink2, fontWeight: 500}}>{label}</span>
    <ToggleSwitch on={!disabled} />
  </div>
);

const CustomerPrivacyTab = () => (
  <Card padding={28}>
    <SectionHead title="Your data, your choice" sub="Under Nigeria's NDPR + EU's GDPR, you have full control over your personal data." />
    <div style={{height: 20}} />

    <Banner variant="success" title="Consent on file">
      You consented to data processing on <strong>14 February 2026</strong>. Lawful basis: <strong>Contract performance (NDPR Art. 2.2)</strong>. You can withdraw this at any time below.
    </Banner>
    <div style={{height: 24}} />

    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24}}>
      <PrivacyCard
        icon="download" title="Download your data"
        sub="Get a JSON export of everything we hold — profile, shipments, billings, claims, consents."
        cta="Request my data export"
      />
      <PrivacyCard
        icon="settings" title="Update consent preferences"
        sub="Change which channels you've consented to. Affects marketing only — transactional messages always go through."
        cta="Manage consent →"
      />
    </div>

    <Card padding={20} style={{background: '#fff8f6', border: `1px solid ${T.error}33`, borderLeft: `4px solid ${T.error}`}}>
      <div style={{display: 'flex', alignItems: 'flex-start', gap: 14}}>
        <div style={{width: 40, height: 40, borderRadius: 10, background: T.errorSoft, color: T.error, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          <Icon name="suspend" size={18} stroke={2.2} />
        </div>
        <div style={{flex: 1}}>
          <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 15, color: T.error}}>Delete my account</div>
          <p style={{fontSize: 13, color: T.ink2, margin: '6px 0 12px', lineHeight: 1.55}}>
            Permanently delete your personal data — your name, phone, email and address are erased from Acme Logistics. Your <strong>billing and shipment records are kept</strong> as required by law, but they'll no longer be linked to you. <strong>This cannot be undone.</strong>
          </p>
          <Button variant="danger-outline" icon="suspend">Delete my account</Button>
        </div>
      </div>
    </Card>
  </Card>
);

const PrivacyCard = ({icon, title, sub, cta}) => (
  <div style={{
    background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10,
    padding: 18,
  }}>
    <div style={{width: 36, height: 36, borderRadius: 10, background: T.greenSoft, color: T.green, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12}}>
      <Icon name={icon} size={16} />
    </div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.ink, marginBottom: 4}}>{title}</div>
    <div style={{fontSize: 12, color: T.ink3, lineHeight: 1.5, marginBottom: 12}}>{sub}</div>
    <a style={{color: T.green, fontWeight: 700, fontSize: 12, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4}}>
      {cta} <Icon name="arrowright" size={11} stroke={2.5} />
    </a>
  </div>
);

Object.assign(window, {
  CustomerShipments, CustomerShipmentDetail,
  CustomerBilling, CustomerBillingDetail,
  CustomerClaims, CustomerFileClaim, CustomerAccount,
  CustomerTopNav,
});
