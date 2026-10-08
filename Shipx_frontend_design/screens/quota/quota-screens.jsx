// ============================================================
// Shipx — Usage Quota Alerts & Limit Enforcement (Section 15.4)
// A. Approaching-limit banner · B. Limit-reached blocking modal
// C. Platform Admin quota progress bars
// ============================================================

const ModalOverlay = ({children}) => (
  <div style={{position: 'absolute', inset: 0, background: 'rgba(11,47,13,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 32}}>{children}</div>
);

const adminNavQ = (active) => [
  {group: 'Overview', items: [
    {icon: 'grid', label: 'Dashboard', active: active === 'dashboard'},
    {icon: 'chart', label: 'Reports'},
  ]},
  {group: 'Operations', items: [
    {icon: 'users', label: 'Customers', count: '142'},
    {icon: 'user', label: 'Staff users', count: '24'},
  ]},
  {group: 'Configuration', items: [
    {icon: 'settings', label: 'Company settings'},
    {icon: 'bell', label: 'Notifications'},
  ]},
];
const adminUserQ = {name: 'Amara Okafor', role: 'Tenant Admin'};

// ============================================================
// A — APPROACHING LIMIT (Tenant Admin dashboard w/ banner)
// ============================================================
const QuotaWarningDashboard = ({withModal} = {}) => (
  <PageShell
    sidebar={<Sidebar role="admin" brand={<TenantBrand name="Eze Freight" logo="EF" />} items={adminNavQ('dashboard')} user={adminUserQ} />}
    topbar={<TopBar role="admin" title="" user={adminUserQ} actions={<DateRangeButton />} />}
  >
    {/* Approaching-limit banner */}
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      background: T.warningSoft, border: `1px solid ${T.warning}55`, borderLeft: `4px solid ${T.warning}`,
      borderRadius: 10, padding: '14px 18px', marginBottom: 20,
    }}>
      <div style={{width: 36, height: 36, borderRadius: 9, background: T.warning, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
        <Icon name="warn" size={18} stroke={2.3} />
      </div>
      <div style={{flex: 1, minWidth: 0}}>
        <div style={{fontSize: 14, fontWeight: 700, color: T.warningStrong}}>You've used 84% of your monthly API calls (4,200 / 5,000)</div>
        <div style={{fontSize: 13, color: T.ink3, marginTop: 2}}>Your <strong>Starter</strong> plan resets on 1 June 2026. Upgrade to avoid service interruption.</div>
      </div>
      <Button variant="accent" size="sm" trailing="arrowright">Upgrade plan</Button>
      <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.warningStrong, display: 'flex'}}>
        <Icon name="x" size={16} />
      </button>
    </div>

    {/* Greeting */}
    <div style={{marginBottom: 20}}>
      <div style={{fontSize: 12, fontWeight: 700, color: T.green, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4}}>Good morning</div>
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 28, color: T.ink, margin: 0, letterSpacing: '-0.02em', lineHeight: 1.15}}>Lead every shipment, Amara.</h2>
    </div>

    {/* Stats with one at-limit */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24}}>
      <StatCard label="Active customers" value="38" sublabel="of 40 max" accent={<Icon name="users" size={15} stroke={2.2} />} />
      <QuotaStatCard label="API calls (mo)" value="4,200" max="5,000" pct={84} />
      <QuotaStatCard label="Containers (mo)" value="20" max="20" pct={100} atLimit />
      <StatCard label="Storage" value="4.1" suffix="/ 5 GB" sublabel="82% used" accent={<Icon name="file" size={15} stroke={2.2} />} />
    </div>

    {/* Usage panel */}
    <Card style={{marginBottom: 24}}>
      <SectionHead title="Plan usage · Starter" sub="Resets 1 June 2026 · upgrade anytime for higher limits" action={
        <Button variant="primary" size="sm" trailing="arrowright">Upgrade plan</Button>
      } />
      <div style={{height: 16}} />
      <QuotaBarRow label="API calls" used="4,200" limit="5,000" pct={84} />
      <QuotaBarRow label="Containers / month" used="20" limit="20" pct={100} atLimit />
      <QuotaBarRow label="SMS sent" used="1,840" limit="2,000" pct={92} />
      <QuotaBarRow label="Active users" used="10" limit="10" pct={100} atLimit />
      <QuotaBarRow label="Storage" used="4.1 GB" limit="5 GB" pct={82} />
    </Card>

    <Card padding={0}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Recent containers" sub="Last 5 processed" />
      </div>
      <Table
        dense
        columns={[{title: 'Container'}, {title: 'Status'}, {title: 'Customers', align: 'right'}, {title: 'Created'}]}
        rows={[
          {cells: [<Mono>EZEU1029384</Mono>, <Badge variant="info">In transit</Badge>, <Mono>6</Mono>, <span style={{fontSize: 12, color: T.ink3}}>28 May</span>]},
          {cells: [<Mono>EZEU8473920</Mono>, <Badge variant="warning">Customs</Badge>, <Mono>4</Mono>, <span style={{fontSize: 12, color: T.ink3}}>24 May</span>]},
          {cells: [<Mono>EZEU2940184</Mono>, <Badge variant="success">Cleared</Badge>, <Mono>8</Mono>, <span style={{fontSize: 12, color: T.ink3}}>20 May</span>]},
        ]}
      />
    </Card>

    {withModal && <LimitReachedModal />}
  </PageShell>
);

const QuotaStatCard = ({label, value, max, pct, atLimit}) => (
  <Card padding={20} radius={12} style={{borderColor: atLimit ? T.error + '55' : pct >= 80 ? T.warning + '55' : T.line, borderWidth: atLimit || pct >= 80 ? 1.5 : 1}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14}}>
      <div style={{width: 28, height: 28, borderRadius: 8, background: atLimit ? T.errorSoft : pct >= 80 ? T.warningSoft : T.greenSoft, color: atLimit ? T.error : pct >= 80 ? T.warning : T.green, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
        <Icon name={atLimit ? 'x' : 'chart'} size={15} stroke={2.2} />
      </div>
      <div style={{fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', fontWeight: 700, color: T.ink3, flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{label}</div>
    </div>
    <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 30, letterSpacing: '-0.02em', color: T.ink, marginBottom: 8, lineHeight: 1}}>
      {value}<span style={{fontSize: 15, color: T.ink4, fontWeight: 600}}> / {max}</span>
    </div>
    <div style={{height: 5, background: T.line, borderRadius: 3, overflow: 'hidden'}}>
      <div style={{height: '100%', width: pct + '%', background: atLimit ? T.error : pct >= 80 ? T.warning : T.green, borderRadius: 3}} />
    </div>
    {atLimit && <div style={{marginTop: 8}}><Badge variant="error" size="sm">At limit</Badge></div>}
  </Card>
);

const QuotaBarRow = ({label, used, limit, pct, atLimit}) => {
  const color = atLimit || pct >= 100 ? T.error : pct >= 80 ? T.warning : T.green;
  return (
    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '160px 1fr 130px 90px', gap: 16, alignItems: 'center', padding: '11px 0', borderBottom: `1px solid ${T.line}`}}>
      <div style={{fontSize: 13, fontWeight: 600, color: T.ink}}>{label}</div>
      <div style={{height: 8, background: T.line, borderRadius: 4, overflow: 'hidden'}}>
        <div style={{height: '100%', width: pct + '%', background: color, borderRadius: 4}} />
      </div>
      <Mono color={T.ink2}>{used} / {limit}</Mono>
      <div style={{textAlign: 'right'}}>
        {pct >= 100 ? <Badge variant="error" size="sm">At limit</Badge> :
         pct >= 80 ? <Badge variant="warning" size="sm">{pct}%</Badge> :
         <span style={{fontSize: 12, color: T.ink4, fontFamily: T.mono}}>{pct}%</span>}
      </div>
    </div>
  );
};

// ============================================================
// B — LIMIT REACHED (blocking modal)
// ============================================================
const LimitReachedModal = () => (
  <ModalOverlay>
    <div style={{width: 520, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '32px 32px 24px', textAlign: 'center'}}>
        <div style={{width: 72, height: 72, borderRadius: '50%', background: T.errorSoft, color: T.error, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginBottom: 18}}>
          <Icon name="warn" size={32} stroke={2} />
        </div>
        <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 22, margin: '0 0 8px', color: T.ink, letterSpacing: '-0.015em'}}>Monthly container limit reached</h3>
        <p style={{fontSize: 14, color: T.ink3, margin: 0, lineHeight: 1.6, maxWidth: 380, marginLeft: 'auto', marginRight: 'auto'}}>
          Your <strong style={{color: T.ink}}>Starter</strong> plan allows <strong style={{color: T.ink}}>20 containers per month</strong>. You've processed all 20 for this billing period.
        </p>
      </div>

      <div style={{margin: '0 32px', padding: 16, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10}}>
          <span style={{fontSize: 13, color: T.ink2, fontWeight: 600}}>Containers this month</span>
          <Mono color={T.error} style={{fontWeight: 700}}>20 / 20</Mono>
        </div>
        <div style={{height: 8, background: T.line, borderRadius: 4, overflow: 'hidden', marginBottom: 10}}>
          <div style={{height: '100%', width: '100%', background: T.error, borderRadius: 4}} />
        </div>
        <div style={{fontSize: 12, color: T.ink3, display: 'flex', alignItems: 'center', gap: 6}}>
          <Icon name="refresh" size={13} color={T.ink4} /> New containers can be created from <strong style={{color: T.ink}}>1 June 2026</strong>.
        </div>
      </div>

      <div style={{padding: '20px 32px 8px'}}>
        <div style={{display: 'flex', gap: 12, alignItems: 'center', padding: 14, background: T.greenTint, border: `1px solid ${T.green}33`, borderRadius: 10}}>
          <div style={{width: 36, height: 36, borderRadius: 9, background: T.green, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
            <Icon name="arrowup" size={16} stroke={2.5} />
          </div>
          <div style={{flex: 1}}>
            <div style={{fontSize: 13, fontWeight: 700, color: T.greenDeep}}>Upgrade to Professional</div>
            <div style={{fontSize: 12, color: T.ink3}}>200 containers/month · 50 users · ₦480k/mo</div>
          </div>
        </div>
      </div>

      <div style={{padding: '16px 32px 24px', display: 'flex', gap: 10}}>
        <Button variant="secondary" full>Contact support</Button>
        <Button variant="primary" full trailing="arrowright">Upgrade plan</Button>
      </div>
    </div>
  </ModalOverlay>
);

Object.assign(window, {
  QuotaWarningDashboard, LimitReachedModal,
});
