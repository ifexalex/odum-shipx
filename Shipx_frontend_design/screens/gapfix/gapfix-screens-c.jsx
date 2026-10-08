// ============================================================
// Shipx — Gap-Fix Screens (Part C)  ·  Round 2
//   C1  ImpersonationBanner  — sticky read-only session banner            [P0/UI]
//   C2  ImpersonatedPortal   — tenant portal under impersonation
//                              (banner + countdown + disabled write actions)
// Pairs with backend Task 1 (enforce read-only impersonation). The backend
// returns impersonated_by / read_only / session_id; this is what the platform
// admin sees and uses to exit.
// ============================================================

// Sticky banner shown at the very top of every page during an impersonated session.
const ImpersonationBanner = ({tenant = 'Acme Logistics', admin = 'platform@shipx.co', remaining = '28:14'}) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 14, padding: '10px 20px',
    background: T.copperDeep, color: '#fff', fontFamily: T.body, flexShrink: 0,
    borderBottom: `1px solid rgba(0,0,0,0.15)`,
  }}>
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 7,
      background: 'rgba(255,255,255,0.16)', padding: '4px 10px', borderRadius: 999,
      fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', flexShrink: 0,
    }}>
      <Icon name="eye" size={13} color="#fff" /> Impersonating
    </span>
    <span style={{fontSize: 13, lineHeight: 1.3, flex: 1, minWidth: 0}}>
      Viewing <strong>{tenant}</strong> as Tenant Admin · <strong>read-only</strong>. All editing is disabled.
      <span style={{opacity: 0.7, marginLeft: 8}}>Started by {admin}</span>
    </span>
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600,
      background: 'rgba(0,0,0,0.18)', padding: '4px 10px', borderRadius: 7, fontFamily: T.mono, flexShrink: 0,
    }}>
      <Icon name="clock" size={13} color="#fff" /> Ends in {remaining}
    </span>
    <button style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, flexShrink: 0,
      background: '#fff', color: T.copperDeep, border: 0, borderRadius: 7,
      padding: '7px 14px', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: T.body,
    }}>
      <Icon name="logout" size={14} color={T.copperDeep} /> Exit impersonation
    </button>
  </div>
);

// A "disabled because read-only" pill used in place of primary/destructive actions.
const ReadOnlyAction = ({label}) => (
  <span title="Disabled during read-only impersonation" style={{
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '8px 14px', borderRadius: 8, border: `1px dashed ${T.lineStrong}`,
    background: T.muted, color: T.ink4, fontSize: 13, fontWeight: 600, cursor: 'not-allowed',
  }}>
    <Icon name="suspend" size={13} color={T.ink4} /> {label}
  </span>
);

// Full demo: the Tenant Admin customer-detail page, viewed under impersonation.
const ImpersonatedPortal = () => {
  const adminU = {name: 'Platform Support', role: 'Platform · viewing as Acme Admin'};
  const tenantBrand = <TenantBrand name="Acme Logistics" logo="AL" />;
  return (
    <div style={{display: 'flex', flexDirection: 'column', height: '100%', fontFamily: T.body}}>
      <ImpersonationBanner />
      <div style={{flex: 1, minHeight: 0}}>
        <PageShell
          sidebar={<Sidebar role="admin" brand={tenantBrand} items={[
            {items: [
              {icon: 'grid', label: 'Dashboard'},
              {icon: 'users', label: 'Customers', active: true},
              {icon: 'package', label: 'Containers'},
              {icon: 'receipt', label: 'Billing'},
              {icon: 'settings', label: 'Configuration'},
            ]},
          ]} user={adminU} />}
          topbar={<TopBar role="admin" title="Customer · Ngozi Okonkwo" breadcrumb={['Admin', 'Customers', 'Ngozi Okonkwo']} user={adminU}
            search={false}
            actions={<>
              <ReadOnlyAction label="Send notification" />
              <ReadOnlyAction label="Edit" />
            </>} />}
        >
          <Banner variant="warning" icon="eye" title="Read-only session">
            You're viewing this tenant as their Tenant Admin for support. Data is fully visible, but every create, edit, approve, and delete action is disabled. The session ends automatically after 30 minutes or when you exit.
          </Banner>

          <div style={{height: 16}} />

          <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16}}>
            <Card padding={24} radius={12}>
              <SectionHead title="Profile" />
              {[['Name', 'Ngozi Okonkwo'], ['Email', 'ngozi.o@example.com'], ['Phone', '+234 801 234 5678'], ['Customer since', '12 Jan 2026'], ['Locale', 'English (EN)']].map(([k, v], i) => (
                <div key={i} style={{display: 'flex', justifyContent: 'space-between', padding: '9px 0', borderBottom: i < 4 ? `1px solid ${T.line}` : 'none', fontSize: 13.5}}>
                  <span style={{color: T.ink4}}>{k}</span><span style={{color: T.ink, fontWeight: 600}}>{v}</span>
                </div>
              ))}
            </Card>
            <Card padding={24} radius={12}>
              <SectionHead title="Actions" sub="Disabled under impersonation" />
              <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
                <ReadOnlyAction label="Reset password" />
                <ReadOnlyAction label="Export customer data" />
                <ReadOnlyAction label="Deactivate account" />
              </div>
              <Banner variant="info" icon="info">
                Need to make a change? Ask the tenant's own admin, or end impersonation — write access is intentionally blocked.
              </Banner>
            </Card>
          </div>

          <div style={{height: 16}} />
          <Card padding={0} radius={12}>
            <div style={{padding: '18px 20px'}}>
              <SectionHead title="Recent shipments" sub="Read-only" />
            </div>
            <Table
              columns={[{title: 'Tracking'}, {title: 'Container'}, {title: 'Status'}, {title: 'CBM', align: 'right'}, {title: 'Updated', align: 'right'}]}
              rows={[
                {cells: [<Mono>SHX-2026-NGOZI-014</Mono>, <Mono>MSKU7654321</Mono>, <Badge variant="info" size="sm">In transit</Badge>, <Mono>0.84</Mono>, '16 Jun']},
                {cells: [<Mono>SHX-2026-NGOZI-009</Mono>, <Mono>TCLU1122334</Mono>, <Badge variant="success" size="sm">Delivered</Badge>, <Mono>1.20</Mono>, '02 Jun']},
              ]}
              dense
            />
          </Card>
        </PageShell>
      </div>
    </div>
  );
};

Object.assign(window, { ImpersonationBanner, ReadOnlyAction, ImpersonatedPortal });
