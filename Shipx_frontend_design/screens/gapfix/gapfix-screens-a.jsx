// ============================================================
// Shipx — Gap-Fix Screens (Part A)
// Closes design gaps from the Gap Analysis. Reuses shared primitives
// (T, Button, Badge, Card, Field, Table, Banner, Icon, Mono, Sidebar, etc.)
//   A1  PublicTracking        — public, no-login tracking (PRD Q2)        [P1]
//   A2  OffboardedScreen      — tenant offboarded (410) state             [P3]
//   A3  ContainerStatusUpdate — China Office status transitions           [P1]
//   A4  CreateContainerFixed  — container-number format hint              [P2]
//   A5  BulkResultState       — bulk approve/reject partial failure       [P2]
//   A6  LocalePreference      — staff language (EN / 中文)                 [P3]
// ============================================================

// ---- small local helpers -------------------------------------------------
const GFLogoRow = ({name = 'Acme Logistics', mark}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
    <div style={{width: 34, height: 34, borderRadius: 9, background: T.copperSoft, color: T.copperDeep,
      display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 15, fontFamily: T.display}}>
      {mark || name.slice(0, 2).toUpperCase()}
    </div>
    <span style={{fontFamily: T.display, fontWeight: 800, fontSize: 18, color: T.ink}}>{name}</span>
  </div>
);

// Customer-friendly tracking stepper (vertical)
const TrackStepper = ({stages, currentIndex}) => (
  <div style={{position: 'relative'}}>
    {stages.map((s, i) => {
      const done = i < currentIndex;
      const current = i === currentIndex;
      const color = done ? T.success : current ? T.green : T.lineStrong;
      return (
        <div key={i} style={{display: 'flex', gap: 16, position: 'relative', paddingBottom: i === stages.length - 1 ? 0 : 26}}>
          {i < stages.length - 1 && (
            <div style={{position: 'absolute', left: 13, top: 28, bottom: 0, width: 2, background: done ? T.success : T.line}} />
          )}
          <div style={{
            width: 28, height: 28, borderRadius: '50%', flexShrink: 0, zIndex: 1,
            background: done ? T.success : current ? '#fff' : '#fff',
            border: `2px solid ${color}`,
            boxShadow: current ? '0 0 0 4px rgba(28,121,34,0.15)' : 'none',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {done ? <Icon name="check" size={14} color="#fff" stroke={3} />
                  : <div style={{width: 8, height: 8, borderRadius: '50%', background: current ? T.green : T.lineStrong}} />}
          </div>
          <div style={{paddingTop: 3}}>
            <div style={{fontWeight: current ? 700 : 600, fontSize: 14, color: current ? T.ink : done ? T.ink2 : T.ink4}}>{s.label}</div>
            {s.time && <div style={{fontSize: 12, color: T.ink4, marginTop: 2}}>{s.time}</div>}
            {current && <div style={{marginTop: 4}}><Badge variant="primary" size="sm">Current stage</Badge></div>}
          </div>
        </div>
      );
    })}
  </div>
);

// ============================================================
// A1 — Public Tracking (no login)  [P1]
// ============================================================
const PublicTracking = ({state = 'result'}) => {
  const stages = [
    {label: 'Received at China warehouse', time: '12 Jun, 09:20'},
    {label: 'Packed in container', time: '14 Jun, 16:40'},
    {label: 'In transit', time: '16 Jun, 02:10'},
    {label: 'Arrived in Nigeria', time: 'Est. 02 Jul'},
    {label: 'Customs clearance', time: ''},
    {label: 'Cleared', time: ''},
    {label: 'Ready for pickup', time: ''},
    {label: 'Picked up', time: ''},
  ];
  return (
    <div style={{minHeight: '100%', background: T.greenTint, fontFamily: T.body, display: 'flex', flexDirection: 'column'}}>
      {/* tenant-branded top strip — no app sidebar */}
      <div style={{background: '#fff', borderBottom: `1px solid ${T.line}`, padding: '16px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <GFLogoRow />
        <span style={{fontSize: 12, color: T.ink4, display: 'inline-flex', alignItems: 'center', gap: 6}}>
          <Icon name="shield" size={13} color={T.ink4} /> Public tracking · no login required
        </span>
      </div>

      <div style={{flex: 1, display: 'flex', justifyContent: 'center', padding: '40px 24px'}}>
        <div style={{width: '100%', maxWidth: 560}}>
          {state === 'entry' ? (
            <Card padding={32} radius={14}>
              <h1 style={{fontFamily: T.display, fontWeight: 800, fontSize: 26, margin: '0 0 6px', color: T.ink, letterSpacing: '-0.02em'}}>Track your shipment</h1>
              <p style={{margin: '0 0 24px', fontSize: 14, color: T.ink3}}>Enter your tracking code and the phone number on your account. No account needed.</p>
              <Field label="Tracking code" icon="package" placeholder="SHX-2026-NGOZI-014" value="SHX-2026-NGOZI-014" />
              <Field label="Phone number" icon="phone" placeholder="+234 801 234 5678" helper="The mobile number registered with your shipment, for verification." />
              <Button variant="accent" size="lg" full trailing="arrowright">Track shipment</Button>
              <p style={{margin: '18px 0 0', fontSize: 12.5, color: T.ink4, textAlign: 'center'}}>
                Have an account? <span style={{color: T.green, fontWeight: 600, cursor: 'pointer'}}>Sign in</span> for billing &amp; claims.
              </p>
            </Card>
          ) : (
            <>
              <Card padding={24} radius={14} style={{marginBottom: 16}}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12}}>
                  <div>
                    <div style={{fontSize: 12, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700, marginBottom: 6}}>Tracking code</div>
                    <Mono color={T.ink}><span style={{fontSize: 18, fontWeight: 600}}>SHX-2026-NGOZI-014</span></Mono>
                    <div style={{fontSize: 13, color: T.ink3, marginTop: 8}}>Container <Mono>MSKU7654321</Mono> · 4 cartons</div>
                  </div>
                  <Badge variant="info">In transit</Badge>
                </div>
              </Card>
              <Card padding={28} radius={14}>
                <div style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, marginBottom: 20, color: T.ink}}>Shipment progress</div>
                <TrackStepper stages={stages} currentIndex={2} />
              </Card>
              <div style={{textAlign: 'center', marginTop: 20, fontSize: 12.5, color: T.ink4}}>
                Updates are sent to your phone by SMS &amp; WhatsApp. Powered by <span style={{fontWeight: 700}}>ship<span style={{color: T.copper}}>x</span></span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// ============================================================
// A2 — Tenant Offboarded (410) state  [P3]
// ============================================================
const OffboardedScreen = () => (
  <div style={{minHeight: '100%', background: T.greenForest, fontFamily: T.body, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24}}>
    <div style={{maxWidth: 480, textAlign: 'center', color: '#fff'}}>
      <div style={{display: 'inline-flex', marginBottom: 24}}>
        <KolaMark size={40} color={T.greenFlash} />
      </div>
      <div style={{
        width: 64, height: 64, borderRadius: '50%', margin: '0 auto 24px',
        background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Icon name="suspend" size={28} color="#fca5a5" />
      </div>
      <h1 style={{fontFamily: T.display, fontWeight: 800, fontSize: 26, margin: '0 0 12px', letterSpacing: '-0.02em'}}>This account has been closed</h1>
      <p style={{margin: '0 0 8px', fontSize: 15, color: 'rgba(255,255,255,0.75)', lineHeight: 1.6}}>
        Acme Logistics is no longer active on Shipx. Your data has been exported and is retained for 90 days per the data-retention policy.
      </p>
      <p style={{margin: '0 0 28px', fontSize: 13, color: 'rgba(255,255,255,0.5)'}}>
        If you believe this is an error, contact ShipX support.
      </p>
      <div style={{display: 'flex', gap: 10, justifyContent: 'center'}}>
        <a href="mailto:support@shipx.co" style={{textDecoration: 'none'}}>
          <Button variant="accent" size="lg" icon="mail">Contact support</Button>
        </a>
      </div>
      <div style={{marginTop: 28, fontSize: 11, color: 'rgba(255,255,255,0.35)', fontFamily: T.mono}}>HTTP 410 · TENANT_OFFBOARDED</div>
    </div>
  </div>
);

// ============================================================
// A3 — Container Status Update (China Office)  [P1]
// ============================================================
const ContainerStatusUpdate = () => {
  const ChinaStage = ({label, code, state}) => {
    const map = {done: {bg: T.successSoft, fg: T.successStrong, dot: T.success, tag: 'Completed'},
                 current: {bg: T.greenSoft, fg: T.greenDeep, dot: T.green, tag: 'Current'},
                 next: {bg: '#fff', fg: T.ink, dot: T.green, tag: 'Select'},
                 locked: {bg: T.muted, fg: T.ink4, dot: T.lineStrong, tag: 'Nigeria Office'}};
    const c = map[state];
    return (
      <label style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
        border: `1px solid ${state === 'next' ? T.green : T.line}`,
        borderRadius: 10, background: c.bg, marginBottom: 8,
        cursor: state === 'next' ? 'pointer' : 'default',
        boxShadow: state === 'next' ? '0 0 0 3px rgba(28,121,34,0.12)' : 'none',
      }}>
        <span style={{width: 18, height: 18, borderRadius: '50%', border: `2px solid ${c.dot}`, background: state === 'done' ? c.dot : '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
          {state === 'done' && <Icon name="check" size={10} color="#fff" stroke={3} />}
          {state === 'next' && <span style={{width: 8, height: 8, borderRadius: '50%', background: T.green}} />}
        </span>
        <div style={{flex: 1}}>
          <div style={{fontWeight: 600, fontSize: 14, color: c.fg}}>{label}</div>
          <Mono color={c.fg}><span style={{fontSize: 11, opacity: 0.7}}>{code}</span></Mono>
        </div>
        <Badge variant={state === 'done' ? 'success' : state === 'current' ? 'primary' : state === 'locked' ? 'neutral' : 'accent'} size="sm">{c.tag}</Badge>
      </label>
    );
  };
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{width: 560}}>
        <Card padding={24} radius={14}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4}}>
            <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0}}>Update container status</h3>
            <Icon name="x" size={18} color={T.ink4} />
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginBottom: 6}}>Container <Mono>MSKU7654321</Mono></div>
          <Banner variant="info" icon="info">
            China Office can advance China-side stages. Arrival-onward stages are handled by Nigeria Office.
          </Banner>
          <div style={{marginTop: 16}}>
            <ChinaStage label="Received at China warehouse" code="received_at_china_warehouse" state="done" />
            <ChinaStage label="Packed in container" code="packed_in_container" state="current" />
            <ChinaStage label="In transit" code="in_transit" state="next" />
            <ChinaStage label="Arrived in Nigeria" code="arrived_nigeria" state="locked" />
            <ChinaStage label="Customs clearance" code="customs_clearance" state="locked" />
          </div>
          <div style={{marginTop: 16}}>
            <Field label="Ship date" icon="calendar" placeholder="Select date" value="16 Jun 2026" helper="Required when moving to In transit." />
            <Field label="Notes" multiline placeholder="Optional notes for this status change…" />
          </div>
          <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8}}>
            <Button variant="secondary">Cancel</Button>
            <Button variant="primary" icon="check">Move to In transit</Button>
          </div>
        </Card>
      </div>
    </div>
  );
};

// ============================================================
// A4 — Create Container with format hint  [P2]
// ============================================================
const CreateContainerFixed = ({state = 'valid'}) => (
  <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 600}}>
      <PageHeader title="Create container" subtitle="China Office · new container" />
      <Card padding={28} radius={14}>
        <div style={{marginBottom: 16}}>
          <label style={{display: 'block', fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>
            Container number <span style={{color: T.error}}>*</span>
          </label>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, height: 44, padding: '0 14px',
            background: '#fff', borderRadius: 8,
            border: `${state === 'error' ? 2 : 2}px solid ${state === 'error' ? T.error : T.green}`,
            boxShadow: state === 'error' ? '0 0 0 3px rgba(220,38,38,0.18)' : '0 0 0 3px rgba(45,196,56,0.30)',
          }}>
            <input defaultValue={state === 'error' ? 'msk 76' : 'MSKU7654321'} style={{
              flex: 1, border: 0, outline: 0, background: 'transparent',
              fontFamily: T.mono, fontSize: 15, letterSpacing: '0.04em', color: T.ink, textTransform: 'uppercase',
            }} />
            {state === 'valid' && <Icon name="check" size={16} color={T.success} stroke={3} />}
            {state === 'error' && <Icon name="alert" size={16} color={T.error} />}
          </div>
          {state === 'error' ? (
            <div style={{display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12, color: T.error, fontWeight: 500}}>
              <Icon name="alert" size={12} color={T.error} />Use ISO 6346 format: 4 letters + 7 digits (e.g. MSKU7654321).
            </div>
          ) : (
            <div style={{marginTop: 6, fontSize: 12, color: T.ink4}}>
              ISO 6346 format — <Mono color={T.ink3}>4 letters + 7 digits</Mono>, e.g. <Mono color={T.ink3}>MSKU7654321</Mono>.
            </div>
          )}
        </div>
        <Field label="Vessel name" placeholder="e.g. Maersk Hangzhou" value="Maersk Hangzhou" />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16}}>
          <Field label="Origin port" trailing="chevdown" value="Guangzhou" />
          <Field label="Destination port" trailing="chevdown" value="Apapa, Lagos" />
        </div>
        <Field label="Expected arrival date" icon="calendar" value="02 Jul 2026" />
        <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 8}}>
          <Button variant="secondary">Cancel</Button>
          <Button variant="primary" disabled={state === 'error'}>Create container</Button>
        </div>
      </Card>
    </div>
  </div>
);

// ============================================================
// A5 — Bulk approve/reject partial result  [P2]
// ============================================================
const BulkResultState = () => {
  const failed = [
    {ref: 'PL-20260728-009', customer: 'Chidi Okeke', reason: 'You cannot approve your own submission'},
    {ref: 'PL-20260728-014', customer: 'Amaka Obi', reason: 'Not in pending_approval state (already approved)'},
  ];
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{width: 640}}>
        <Card padding={28} radius={14}>
          <div style={{display: 'flex', gap: 14, alignItems: 'flex-start', marginBottom: 20}}>
            <div style={{width: 44, height: 44, borderRadius: 12, background: T.warningSoft, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
              <Icon name="alert" size={22} color={T.warning} />
            </div>
            <div>
              <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 19, margin: '0 0 4px'}}>Bulk approval finished with issues</h3>
              <p style={{margin: 0, fontSize: 13.5, color: T.ink3}}>18 of 20 packing lists were approved. 2 could not be processed and were left unchanged.</p>
            </div>
          </div>

          <div style={{display: 'flex', gap: 12, marginBottom: 20}}>
            <div style={{flex: 1, background: T.successSoft, borderRadius: 10, padding: '14px 16px'}}>
              <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 26, color: T.successStrong, lineHeight: 1}}>18</div>
              <div style={{fontSize: 12, color: T.successStrong, fontWeight: 600, marginTop: 4}}>Approved</div>
            </div>
            <div style={{flex: 1, background: T.errorSoft, borderRadius: 10, padding: '14px 16px'}}>
              <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 26, color: T.errorStrong, lineHeight: 1}}>2</div>
              <div style={{fontSize: 12, color: T.errorStrong, fontWeight: 600, marginTop: 4}}>Failed</div>
            </div>
          </div>

          <SectionHead title="Failed items" sub="Resolve each individually, then retry." />
          <div style={{border: `1px solid ${T.line}`, borderRadius: 10, overflow: 'hidden'}}>
            {failed.map((f, i) => (
              <div key={i} style={{display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px', borderBottom: i < failed.length - 1 ? `1px solid ${T.line}` : 'none'}}>
                <Icon name="x" size={16} color={T.error} stroke={2.5} />
                <div style={{flex: 1}}>
                  <Mono color={T.ink}>{f.ref}</Mono>
                  <span style={{fontSize: 13, color: T.ink3, marginLeft: 10}}>{f.customer}</span>
                  <div style={{fontSize: 12.5, color: T.error, marginTop: 2}}>{f.reason}</div>
                </div>
                <Button variant="ghost" size="sm" trailing="arrowright">Open</Button>
              </div>
            ))}
          </div>
          <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20}}>
            <Button variant="secondary">Done</Button>
            <Button variant="primary" icon="refresh">Retry 2 failed</Button>
          </div>
        </Card>
      </div>
    </div>
  );
};

// ============================================================
// A6 — Locale / language preference  [P3]
// ============================================================
const LocalePreference = () => {
  const Lang = ({label, sub, active}) => (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px', borderRadius: 10,
      border: `1px solid ${active ? T.green : T.line}`, background: active ? T.greenSoft : '#fff',
      boxShadow: active ? '0 0 0 3px rgba(28,121,34,0.12)' : 'none', cursor: 'pointer', flex: 1,
    }}>
      <span style={{width: 18, height: 18, borderRadius: '50%', border: `2px solid ${active ? T.green : T.lineStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0}}>
        {active && <span style={{width: 8, height: 8, borderRadius: '50%', background: T.green}} />}
      </span>
      <div>
        <div style={{fontWeight: 600, fontSize: 14, color: T.ink}}>{label}</div>
        <div style={{fontSize: 12, color: T.ink4}}>{sub}</div>
      </div>
    </label>
  );
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{width: 600}}>
        <PageHeader eyebrow="Staff profile" title="Wei Chen" subtitle="China Office Staff" />
        <Card padding={24} radius={14} style={{marginBottom: 16}}>
          <SectionHead title="Notification language" sub="Controls the language of SMS, WhatsApp & email this user receives." />
          <div style={{display: 'flex', gap: 12}}>
            <Lang label="English" sub="EN — default" />
            <Lang label="中文 (简体)" sub="ZH — Simplified Chinese" active />
          </div>
          <Banner variant="info" icon="info">
            <span>Maps to <Mono color={T.infoStrong}>tenant_user.locale</Mono>. Notification templates render in the selected language where a ZH template exists.</span>
          </Banner>
        </Card>
        <div style={{display: 'flex', justifyContent: 'flex-end'}}>
          <Button variant="primary">Save changes</Button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, {
  PublicTracking, OffboardedScreen, ContainerStatusUpdate, CreateContainerFixed,
  BulkResultState, LocalePreference, TrackStepper,
});
