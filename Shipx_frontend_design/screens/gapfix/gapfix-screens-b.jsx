// ============================================================
// Shipx — Gap-Fix Screens (Part B)
//   B1  RefundApproveThreshold — threshold-aware approve modal (within / over)  [P2]
//   B2  WebhookConfig          — outbound webhook configuration                 [P2]
//   B3  StorageFeeBanners      — 14-day grace countdown / accruing states        [P2]
//   B4  WeightDiscrepancy      — manifest weight reconciliation report           [P3]
//   B5  DisputeSLA             — CBM dispute SLA countdown + auto-escalation      [P3]
//   B6  ReleaseNoteExpired     — expired release-note state                      [P3]
// ============================================================

// ============================================================
// B1 — Refund approve modal, threshold aware  [P2]
// ============================================================
const RefundApproveThreshold = ({state = 'within'}) => {
  const over = state === 'over';
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{width: 560}}>
        <Card padding={28} radius={14}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18}}>
            <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 19, margin: 0}}>Approve refund</h3>
            <Icon name="x" size={18} color={T.ink4} />
          </div>

          <div style={{background: T.muted, borderRadius: 10, padding: 16, marginBottom: 18}}>
            <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 8}}>
              <span style={{fontSize: 13, color: T.ink3}}>Refund</span>
              <Mono color={T.ink}>RF-20260730-014</Mono>
            </div>
            <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 8}}>
              <span style={{fontSize: 13, color: T.ink3}}>Customer</span>
              <span style={{fontSize: 13, fontWeight: 600, color: T.ink}}>Ngozi Okonkwo</span>
            </div>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline'}}>
              <span style={{fontSize: 13, color: T.ink3}}>Amount approved</span>
              <span style={{fontFamily: T.display, fontWeight: 800, fontSize: 22, color: T.ink}}>
                {over ? '₦123,750' : '₦66,000'} <span style={{fontSize: 13, color: T.ink4, fontWeight: 600}}>≈ ${over ? '75.00' : '40.00'}</span>
              </span>
            </div>
          </div>

          {/* Threshold meter */}
          <div style={{marginBottom: 6, display: 'flex', justifyContent: 'space-between', fontSize: 12, color: T.ink4}}>
            <span>Staff approval limit</span>
            <span><Mono color={T.ink3}>$50.00</Mono> · ₦82,500</span>
          </div>
          <div style={{height: 8, borderRadius: 999, background: T.line, overflow: 'hidden', marginBottom: 16, position: 'relative'}}>
            <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: over ? '100%' : '80%', background: over ? T.error : T.success, borderRadius: 999}} />
            <div style={{position: 'absolute', left: '66.6%', top: -2, bottom: -2, width: 2, background: T.ink3}} />
          </div>

          {over ? (
            <Banner variant="warning" title="Exceeds your approval limit" icon="warn">
              This refund of <strong>$75.00</strong> is above the <strong>$50.00</strong> staff limit. It must be approved by a Tenant Admin. You can forward it for escalation.
            </Banner>
          ) : (
            <Banner variant="success" title="Within your approval limit" icon="check">
              $40.00 is within the $50.00 staff limit. You can approve this refund directly.
            </Banner>
          )}

          <div style={{marginTop: 18}}>
            <Field label="Approval note" multiline placeholder="Reason / reference for this decision…" />
          </div>

          <div style={{display: 'flex', justifyContent: 'flex-end', gap: 10}}>
            <Button variant="secondary">Cancel</Button>
            {over
              ? <Button variant="accent" icon="arrowright">Escalate to Tenant Admin</Button>
              : <Button variant="success" icon="check">Approve refund</Button>}
          </div>
          {over && (
            <div style={{marginTop: 12, textAlign: 'right', fontSize: 11.5, color: T.ink4, fontFamily: T.mono}}>
              Direct approval blocked · APPROVAL_THRESHOLD_EXCEEDED (403)
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

// ============================================================
// B2 — Outbound webhook configuration  [P2]
// ============================================================
const WebhookConfig = () => {
  const ConfigNav = ({label, active, badge}) => (
    <div style={{display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', borderRadius: 8, cursor: 'pointer',
      background: active ? T.greenSoft : 'transparent', color: active ? T.greenDeep : T.ink2, fontWeight: active ? 600 : 500, fontSize: 14}}>
      <span style={{flex: 1}}>{label}</span>
      {badge && <Badge variant="accent" size="sm">{badge}</Badge>}
    </div>
  );
  const EventToggle = ({label, code, on}) => (
    <div style={{display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: `1px solid ${T.line}`}}>
      <div style={{width: 36, height: 20, borderRadius: 999, background: on ? T.green : T.lineStrong, position: 'relative', flexShrink: 0}}>
        <div style={{position: 'absolute', top: 2, left: on ? 18 : 2, width: 16, height: 16, borderRadius: '50%', background: '#fff', transition: 'left .15s'}} />
      </div>
      <div style={{flex: 1}}>
        <div style={{fontSize: 13.5, fontWeight: 600, color: T.ink}}>{label}</div>
        <Mono color={T.ink4}><span style={{fontSize: 11}}>{code}</span></Mono>
      </div>
    </div>
  );
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%'}}>
      <PageHeader title="Company settings" subtitle="Configure integrations and outbound data flow." />
      <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '220px 1fr', gap: 24, alignItems: 'start'}}>
        <Card padding={10} radius={12}>
          <ConfigNav label="General" />
          <ConfigNav label="Dollar rate" />
          <ConfigNav label="CBM rate" />
          <ConfigNav label="Charge types" />
          <ConfigNav label="Notification templates" />
          <ConfigNav label="Webhooks" active badge="New" />
        </Card>

        <div>
          <Card padding={24} radius={12} style={{marginBottom: 16}}>
            <SectionHead title="Outbound webhook" sub="Push domain events to your ERP / WMS in real time." action={
              <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                <span style={{fontSize: 12, color: T.success, fontWeight: 600}}>Enabled</span>
                <div style={{width: 40, height: 22, borderRadius: 999, background: T.green, position: 'relative'}}>
                  <div style={{position: 'absolute', top: 2, left: 20, width: 18, height: 18, borderRadius: '50%', background: '#fff'}} />
                </div>
              </div>
            } />
            <Field label="Endpoint URL" icon="map" value="https://erp.acmelogistics.com/hooks/shipx" helper="We POST a JSON payload signed with HMAC-SHA256." />
            <div style={{marginBottom: 16}}>
              <label style={{display: 'block', fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>Signing secret</label>
              <div style={{display: 'flex', gap: 8}}>
                <div style={{flex: 1, display: 'flex', alignItems: 'center', gap: 8, height: 40, padding: '0 14px', background: T.muted, borderRadius: 8, border: `1px solid ${T.line}`}}>
                  <Icon name="shield" size={15} color={T.ink4} />
                  <Mono color={T.ink2}>whsec_••••••••••••••••3f9a</Mono>
                </div>
                <Button variant="secondary" icon="eye">Reveal</Button>
                <Button variant="secondary" icon="refresh">Rotate</Button>
              </div>
              <div style={{marginTop: 6, fontSize: 12, color: T.ink4}}>Sent as header <Mono color={T.ink3}>X-ShipX-Signature-256: sha256=…</Mono></div>
            </div>
          </Card>

          <Card padding={24} radius={12} style={{marginBottom: 16}}>
            <SectionHead title="Subscribed events" sub="Choose which events fire a webhook." />
            <EventToggle label="Container status updated" code="container.status_updated" on />
            <EventToggle label="Billing generated" code="billing.generated" on />
            <EventToggle label="Payment confirmed" code="payment.confirmed" on />
            <EventToggle label="Release note issued" code="release_note.issued" />
            <EventToggle label="Claim filed" code="claim.filed" />
          </Card>

          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <Button variant="secondary" icon="bell">Send test event</Button>
            <Button variant="primary">Save webhook</Button>
          </div>
        </div>
      </div>
    </div>
  );
};

// ============================================================
// B3 — Storage fee grace-period banners  [P2]
// ============================================================
const StorageFeeBanners = () => (
  <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 720}}>
      <PageHeader title="Storage fee states" subtitle="14-day grace period from release-note issue, then ₦500/day/carton (PRD Q7). These banners attach to billing detail, release-note detail & the customer shipment view." />

      <div style={{marginBottom: 14}}>
        <div style={{fontSize: 12, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>① Grace — comfortably within (day 3 of 14)</div>
        <Banner variant="info" title="Free storage until 12 Jul" icon="clock">
          Pickup is free for <strong>11 more days</strong>. After the grace period, storage accrues at ₦500/day per carton (4 cartons).
        </Banner>
      </div>

      <div style={{marginBottom: 14}}>
        <div style={{fontSize: 12, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>② Grace — ending soon (day 13 of 14, reminder fired)</div>
        <Banner variant="warning" title="Storage fees begin tomorrow" icon="warn" action={<Button variant="accent" size="sm">Pay & collect</Button>}>
          Grace period ends <strong>12 Jul</strong>. From day 15, ₦2,000/day will accrue (4 cartons × ₦500). A reminder was sent to the customer today.
        </Banner>
      </div>

      <div style={{marginBottom: 14}}>
        <div style={{fontSize: 12, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8}}>③ Accruing (day 18 — 4 days past grace)</div>
        <Banner variant="error" title="Storage fees are accruing" icon="alert" action={<Button variant="danger" size="sm">View charges</Button>}>
          <strong>₦8,000</strong> accrued so far (4 days × ₦2,000). This is added to the outstanding balance daily until pickup.
        </Banner>
      </div>

      <Card padding={20} radius={12} style={{marginTop: 8}}>
        <SectionHead title="Accrual log (billing detail)" sub="Backed by scheduled/storage_fee.py" />
        <Table
          columns={[{title: 'Day'}, {title: 'Date'}, {title: 'Cartons', align: 'right'}, {title: 'Rate', align: 'right'}, {title: 'Fee', align: 'right'}]}
          rows={[
            {cells: ['Day 15', '13 Jul', '4', <Mono>₦500</Mono>, <Mono color={T.error}>₦2,000</Mono>]},
            {cells: ['Day 16', '14 Jul', '4', <Mono>₦500</Mono>, <Mono color={T.error}>₦2,000</Mono>]},
            {cells: ['Day 17', '15 Jul', '4', <Mono>₦500</Mono>, <Mono color={T.error}>₦2,000</Mono>]},
            {cells: ['Day 18', '16 Jul', '4', <Mono>₦500</Mono>, <Mono color={T.error}>₦2,000</Mono>]},
          ]}
          dense
        />
      </Card>
    </div>
  </div>
);

// ============================================================
// B4 — Manifest weight reconciliation  [P3]
// ============================================================
const WeightDiscrepancy = () => (
  <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 760}}>
      <PageHeader eyebrow="Manifest verification" title="MF-20260415-001" subtitle="Container MSKU7654321 · verifying on arrival" actions={<Button variant="primary" icon="check">Submit verification</Button>} />

      <Banner variant="warning" title="3 items flagged for weight discrepancy" icon="warn">
        Actual weight diverges from dispatch weight by more than the 5% / 0.1kg threshold. Review before verifying — these may indicate missing contents or repacking.
      </Banner>

      <Card padding={20} radius={12} style={{marginTop: 16}}>
        <SectionHead title="Weight discrepancies" sub="Returned by PATCH /v1/manifests/{id}/verify → weight_discrepancies" />
        <Table
          columns={[
            {title: 'Carton tag'}, {title: 'Customer'},
            {title: 'Dispatch (kg)', align: 'right'}, {title: 'Actual (kg)', align: 'right'},
            {title: 'Δ', align: 'right'}, {title: 'Flag', align: 'right'},
          ]}
          rows={[
            {cells: [<Mono>SHX-00012</Mono>, 'Ngozi Okonkwo', '14.500', '11.200', <Mono color={T.error}>−3.300</Mono>, <Badge variant="error" size="sm">−22.8%</Badge>]},
            {cells: [<Mono>SHX-00031</Mono>, 'Chidi Okeke', '8.000', '9.450', <Mono color={T.warning}>+1.450</Mono>, <Badge variant="warning" size="sm">+18.1%</Badge>]},
            {cells: [<Mono>SHX-00044</Mono>, 'Amaka Obi', '22.000', '20.100', <Mono color={T.warning}>−1.900</Mono>, <Badge variant="warning" size="sm">−8.6%</Badge>]},
          ]}
          dense
        />
        <div style={{marginTop: 16, display: 'flex', gap: 12, alignItems: 'flex-start'}}>
          <div style={{flex: 1}}>
            <Field label="Resolution notes" multiline placeholder="Explain how each discrepancy was handled (recount, repack, missing contents logged as claim…)" />
          </div>
        </div>
        <div style={{display: 'flex', gap: 10, justifyContent: 'flex-end'}}>
          <Button variant="secondary" icon="package">Log missing-item claim</Button>
          <Button variant="primary" icon="check">Verify with notes</Button>
        </div>
      </Card>
    </div>
  </div>
);

// ============================================================
// B5 — CBM dispute SLA countdown + auto-escalation  [P3]
// ============================================================
const DisputeSLA = ({state = 'ticking'}) => {
  const escalated = state === 'escalated';
  return (
    <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{width: 720}}>
        <PageHeader eyebrow="CBM dispute" title="DSP-20260712-003"
          subtitle="Filed by Ngozi Okonkwo · billing BL-20260728-001"
          actions={escalated ? <Button variant="primary" icon="check">Resolve dispute</Button> : <Button variant="primary" icon="check">Acknowledge</Button>} />

        {/* SLA strip */}
        <Card padding={20} radius={12} style={{marginBottom: 16}}>
          <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12}}>
            <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
              <div style={{width: 40, height: 40, borderRadius: 10, background: escalated ? T.errorSoft : T.warningSoft, display: 'flex', alignItems: 'center', justifyContent: 'center'}}>
                <Icon name="clock" size={20} color={escalated ? T.error : T.warning} />
              </div>
              <div>
                <div style={{fontWeight: 700, fontSize: 15, color: T.ink}}>
                  {escalated ? 'Auto-escalated to Tenant Admin' : 'SLA: resolve within 7 days'}
                </div>
                <div style={{fontSize: 13, color: T.ink3}}>
                  {escalated
                    ? 'China Office did not respond within 5 days — escalated automatically on 17 Jul.'
                    : 'Acknowledged 12 Jul · investigation due by 17 Jul · resolution by 19 Jul.'}
                </div>
              </div>
            </div>
            {escalated
              ? <Badge variant="error">Escalated · system</Badge>
              : <Badge variant="warning">2 days left</Badge>}
          </div>
          {/* timeline bar */}
          <div style={{marginTop: 16, height: 8, borderRadius: 999, background: T.line, overflow: 'hidden', position: 'relative'}}>
            <div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: escalated ? '100%' : '64%', background: escalated ? T.error : T.warning, borderRadius: 999}} />
          </div>
          <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: T.ink4}}>
            <span>Filed 12 Jul</span><span>Investigate by 17 Jul</span><span>Resolve by 19 Jul</span>
          </div>
        </Card>

        <Card padding={20} radius={12}>
          <SectionHead title="Dispute timeline" />
          {[
            {ic: 'file', c: T.info, t: 'Dispute filed', d: 'Customer: "Carton SHX-00012 measured larger than actual size."', time: '12 Jul, 10:04'},
            {ic: 'check', c: T.success, t: 'Acknowledged by Nigeria Office', d: 'Adaeze Eze', time: '12 Jul, 11:20'},
            ...(escalated ? [{ic: 'arrowup', c: T.error, t: 'Auto-escalated to Tenant Admin', d: 'System · no China Office response within 5 days', time: '17 Jul, 00:00', system: true}] : []),
          ].map((e, i, arr) => (
            <div key={i} style={{display: 'flex', gap: 12, paddingBottom: i < arr.length - 1 ? 18 : 0, position: 'relative'}}>
              {i < arr.length - 1 && <div style={{position: 'absolute', left: 13, top: 28, bottom: 0, width: 2, background: T.line}} />}
              <div style={{width: 28, height: 28, borderRadius: '50%', background: e.c + '1a', border: `1px solid ${e.c}55`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, zIndex: 1}}>
                <Icon name={e.ic} size={14} color={e.c} />
              </div>
              <div style={{flex: 1}}>
                <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
                  <span style={{fontWeight: 600, fontSize: 14, color: T.ink}}>{e.t}</span>
                  {e.system && <Badge variant="error" size="sm">Automated</Badge>}
                  <span style={{marginLeft: 'auto', fontSize: 12, color: T.ink4}}>{e.time}</span>
                </div>
                <div style={{fontSize: 13, color: T.ink3, marginTop: 2}}>{e.d}</div>
              </div>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
};

// ============================================================
// B6 — Release note expired state  [P3]
// ============================================================
const ReleaseNoteExpired = () => (
  <div style={{padding: 32, background: T.page, minHeight: '100%', display: 'flex', justifyContent: 'center'}}>
    <div style={{width: 760}}>
      <PageHeader eyebrow="Release note" title="RN-20260728-ABC123"
        subtitle="Ngozi Okonkwo · Container MSKU7654321"
        actions={<><Button variant="secondary" icon="download">Print</Button><Button variant="accent" icon="refresh">Re-issue release note</Button></>} />

      <Banner variant="error" title="This release note has expired" icon="alert">
        Issued 28 Jun, expired 12 Jul after the 14-day pickup window. It can no longer authorize collection. Re-issue a new release note to continue — any storage fees accrued will be carried onto the new note.
      </Banner>

      <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16, marginTop: 16}}>
        {/* expired document */}
        <Card padding={0} radius={12} style={{overflow: 'hidden'}}>
          <div style={{position: 'relative', padding: 24, background: '#fff'}}>
            <div style={{position: 'absolute', top: 28, right: 28, border: `3px solid ${T.error}`, color: T.error, fontFamily: T.display, fontWeight: 800, fontSize: 20, letterSpacing: '0.1em', padding: '4px 14px', borderRadius: 6, transform: 'rotate(-10deg)', opacity: 0.85}}>EXPIRED</div>
            <GFLogoRow />
            <div style={{marginTop: 18, fontSize: 12, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700}}>Release note</div>
            <Mono color={T.ink}><span style={{fontSize: 16, fontWeight: 600}}>RN-20260728-ABC123</span></Mono>
            <div style={{marginTop: 16, opacity: 0.5}}>
              {[['Customer', 'Ngozi Okonkwo'], ['Cartons', '4'], ['Payment ref', 'PAY-99812'], ['Authorized', '28 Jun 2026']].map(([k, v], i) => (
                <div key={i} style={{display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: `1px solid ${T.line}`, fontSize: 13}}>
                  <span style={{color: T.ink4}}>{k}</span><span style={{color: T.ink, fontWeight: 600}}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>

        {/* status / action side */}
        <div>
          <Card padding={20} radius={12} style={{marginBottom: 16}}>
            <SectionHead title="Status" />
            <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12}}>
              <Badge variant="error">Expired</Badge>
              <span style={{fontSize: 13, color: T.ink4}}>via scheduled/release_expiry.py</span>
            </div>
            <div style={{fontSize: 13, color: T.ink3, lineHeight: 1.6}}>
              Outstanding balance: <strong style={{color: T.ink}}>₦8,000</strong> (storage). The customer must settle this before a new note is issued.
            </div>
          </Card>
          <Card padding={20} radius={12}>
            <SectionHead title="Warehouse note" />
            <Banner variant="warning" icon="warn">
              If a customer presents this code at the warehouse, the scanner shows <strong>EXPIRED — do not release</strong>. Direct them to settle &amp; re-issue.
            </Banner>
          </Card>
        </div>
      </div>
    </div>
  </div>
);

Object.assign(window, {
  RefundApproveThreshold, WebhookConfig, StorageFeeBanners,
  WeightDiscrepancy, DisputeSLA, ReleaseNoteExpired,
});
