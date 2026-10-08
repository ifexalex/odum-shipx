// ============================================================
// Shipx — Billing Management Screens (Section 7)
// 7.1 Billing List · 7.2 Billing Detail (+ Record Payment, Add Charge modals)
// 7.3 CBM Disputes (+ Dispute Detail panel) · 7.4 Carryovers
// ============================================================

// ============================================================
// 7.1 — BILLING LIST
// ============================================================
const BillingList = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('billing')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Billing" breadcrumb={['Billing', 'All records']} user={ngUser} actions={
      <>
        <Button variant="secondary" icon="download">Export</Button>
        <Button variant="primary" icon="plus">Generate billing</Button>
      </>
    } />}
  >
    {/* Summary strip */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Outstanding" value="₦4.21" suffix="M" sublabel="across 42 records"
        accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Paid this month" value="₦14.8" suffix="M" trend="+18%" trendDir="up" sublabel="148 records"
        accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Overdue (30+ days)" value="₦642k" sublabel="6 records flagged"
        accent={<Icon name="clock" size={15} stroke={2.2} />} />
      <StatCard label="Avg. collection time" value="4.2" suffix="days" trend="−0.8d" trendDir="down" sublabel="faster vs Q1"
        accent={<Icon name="refresh" size={15} stroke={2.2} />} />
    </div>

    {/* Filter bar */}
    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>284</span></Chip>
          <Chip count={42}>Unpaid</Chip>
          <Chip count={18}>Partial</Chip>
          <Chip count={218}>Paid</Chip>
          <Chip count={4}>Overpaid</Chip>
          <Chip count={2}>Waived</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Reference, customer, container…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
        <Button variant="secondary" size="md" icon="calendar">Jul 2026</Button>
        <Button variant="secondary" size="md" icon="filter">Filters</Button>
      </div>
    </Card>

    {/* Active filter chips */}
    <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap', fontSize: 12, color: T.ink3}}>
      <span style={{fontWeight: 600, color: T.ink2}}>Active filters:</span>
      <Chip dismissible active>Container: MSCU1234567</Chip>
      <Chip dismissible active>Date: Jul 2026</Chip>
      <a style={{color: T.green, fontWeight: 600, cursor: 'pointer', marginLeft: 4}}>Clear all</a>
      <span style={{flex: 1}} />
      <span>Showing <strong style={{color: T.ink}}>1–10</strong> of <strong style={{color: T.ink}}>62</strong> records</span>
    </div>

    <Card padding={0}>
      <Table
        selectable
        columns={[
          {title: 'Reference', sortable: true},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'CBM', align: 'right'},
          {title: 'Total NGN', align: 'right'},
          {title: 'Paid', align: 'right'},
          {title: 'Outstanding', align: 'right'},
          {title: 'Status'},
          {title: 'Billed', sortable: true},
          {title: '', width: 130},
        ]}
        rows={[
          blRow({ref: 'BL-20260728-001', cust: 'Ngozi Okonkwo', container: 'MSCU1234567', cbm: '1.84', total: 73704, paid: 49352, status: 'partial', billed: '28 Jul'}),
          blRow({ref: 'BL-20260728-002', cust: 'Emeka Eze', container: 'MSCU1234567', cbm: '2.14', total: 187400, paid: 187400, status: 'paid', billed: '28 Jul'}),
          blRow({ref: 'BL-20260728-003', cust: 'Funmilayo Adeyemi', container: 'MSCU1234567', cbm: '1.42', total: 97680, paid: 0, status: 'unpaid', billed: '28 Jul'}),
          blRow({ref: 'BL-20260728-004', cust: 'Ibrahim Musa', container: 'MSCU1234567', cbm: '1.18', total: 92280, paid: 0, status: 'unpaid', billed: '28 Jul', overdue: false}),
          blRow({ref: 'BL-20260727-005', cust: 'Adaeze Nwosu', container: 'MSCU1234567', cbm: '0.94', total: 78540, paid: 78540, status: 'paid', billed: '27 Jul'}),
          blRow({ref: 'BL-20260727-006', cust: 'Bola Adesina', container: 'MSCU1234567', cbm: '0.72', total: 56880, paid: 56880, status: 'paid', billed: '27 Jul'}),
          blRow({ref: 'BL-20260626-019', cust: 'Olufemi Adetunji', container: 'COSU7194820', cbm: '0.86', total: 42230, paid: 18000, status: 'overdue', billed: '26 Jun', overdue: true}),
          blRow({ref: 'BL-20260615-042', cust: 'Aisha Lawar', container: 'HLBU9384712', cbm: '1.04', total: 88560, paid: 95000, status: 'overpaid', billed: '15 Jun'}),
          blRow({ref: 'BL-20260612-051', cust: 'Yusuf Garba', container: 'HLBU9384712', cbm: '0.42', total: 32420, paid: 0, status: 'waived', billed: '12 Jun'}),
          blRow({ref: 'BL-20260601-068', cust: 'Chukwuemeka Nwogu', container: 'ONEU2847510', cbm: '0.18', total: 14820, paid: 8000, status: 'released_outstanding', billed: '01 Jun'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const blRow = ({ref, cust, container, cbm, total, paid, status, billed, overdue}) => {
  const out = total - paid;
  const badge = {
    paid: <Badge variant="success">Paid</Badge>,
    partial: <Badge variant="warning">Partial</Badge>,
    unpaid: <Badge variant="error">Unpaid</Badge>,
    overdue: <Badge variant="error">Overdue · 32d</Badge>,
    overpaid: <Badge variant="info">Overpaid</Badge>,
    waived: <Badge variant="neutral">Waived</Badge>,
    released_outstanding: <Badge variant="purple">Released w/ outstanding</Badge>,
  }[status];
  return {
    suspended: status === 'overdue',
    cells: [
      <Mono color={T.ink}>{ref}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <Mono>{cbm}</Mono>,
      <Mono>₦{total.toLocaleString()}</Mono>,
      <Mono color={paid > 0 ? T.success : T.ink4}>{paid > 0 ? `₦${paid.toLocaleString()}` : '—'}</Mono>,
      <Mono color={out > 0 ? T.error : out < 0 ? T.info : T.success}>{out === 0 ? '—' : out > 0 ? `₦${out.toLocaleString()}` : `(₦${Math.abs(out).toLocaleString()})`}</Mono>,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{billed}</span>,
      <div style={{display: 'flex', gap: 6, justifyContent: 'flex-end'}}>
        {status === 'unpaid' || status === 'partial' || status === 'overdue' ?
          <Button variant="accent" size="sm" icon="coin">Record payment</Button> :
          status === 'paid' ?
          <Button variant="secondary" size="sm" icon="card">Release</Button> :
          <Button variant="ghost" size="sm">View</Button>
        }
      </div>,
    ],
  };
};

// ============================================================
// 7.2 — BILLING DETAIL
// ============================================================
const BillingDetail = ({withPaymentModal, withChargeModal, withCarryoverModal, withReleaseModal, storage} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('billing')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="" breadcrumb={['Billing', 'BL-20260728-001']} user={ngUser} />}
  >
    {/* Hero */}
    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, marginBottom: 24, flexWrap: 'wrap'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 16, minWidth: 0}}>
        <div style={{
          width: 64, height: 64, borderRadius: 14,
          background: T.warningSoft, color: T.warning,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon name="coin" size={28} stroke={2} />
        </div>
        <div>
          <div style={{display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap'}}>
            <h1 style={{fontFamily: T.mono, fontWeight: 700, fontSize: 26, color: T.ink, margin: 0, letterSpacing: '-0.01em', lineHeight: 1.15}}>BL-20260728-001</h1>
            <Badge variant="warning">Partially paid · ₦24,352 outstanding</Badge>
          </div>
          <div style={{fontSize: 13, color: T.ink3, marginTop: 4, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'}}>
            <a style={{color: T.green, fontWeight: 600}}>Ngozi Okonkwo</a>
            <span style={{color: T.lineStrong}}>·</span>
            <a style={{color: T.green, fontWeight: 600}}><Mono>MSCU1234567</Mono></a>
            <span style={{color: T.lineStrong}}>·</span>
            <span>Billed 28 Jul 2026 by Ifeoma Uche</span>
          </div>
        </div>
      </div>
      <div style={{display: 'flex', gap: 8}}>
        <Button variant="secondary" icon="download">Export invoice</Button>
        <Button variant="secondary" icon="plus">Add charge</Button>
        <Button variant="danger-outline">Cancel billing</Button>
        <Button variant="accent" icon="coin">Record payment</Button>
      </div>
    </div>

    <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 20, marginBottom: 20}}>
      {/* Billing breakdown card */}
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Billing breakdown" sub="CBM-based calculation + miscellaneous charges" action={
            <a style={{color: T.green, fontWeight: 600, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 4}}>Show CBM math <Icon name="chevdown" size={12} /></a>
          } />
        </div>
        <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: T.body, fontSize: 13}}>
          <tbody>
            <BreakdownRow
              label={<>
                <div style={{fontWeight: 700, color: T.ink}}>CBM calculation</div>
                <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono, marginTop: 2}}>0.93 CBM × $48.00 × ₦1,650</div>
              </>}
              amount="₦73,656"
              accent
            />
            <BreakdownRow
              label={<>
                <div style={{color: T.ink2}}>Misc fee: Customs Examination</div>
                <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>Added by Ifeoma Uche on 28 Jul</div>
              </>}
              amount="₦15,000"
              removable
            />
            <BreakdownRow
              label={<>
                <div style={{color: T.ink2}}>Misc fee: Port Handling Surcharge</div>
                <div style={{fontSize: 11, color: T.ink4, marginTop: 1}}>Added by Ifeoma Uche on 28 Jul</div>
              </>}
              amount="₦8,500"
              removable
            />
            <BreakdownRow
              label={<div style={{display: 'inline-flex', alignItems: 'center', gap: 6}}>
                <span style={{color: T.ink2}}>Carryover from BL-20260712-031</span>
                <Badge variant="purple" size="sm" dot={false}>Applied</Badge>
              </div>}
              amount="₦8,500"
              note="Outstanding rolled forward"
            />
            <BreakdownRow
              label={<span style={{color: T.success, fontWeight: 600}}>CBM dispute adjustment</span>}
              amount={<span style={{color: T.success}}>−₦5,648</span>}
              note="Resolved 27 Jul · CBM corrected to 0.86"
            />
            <BreakdownRow
              label={<strong style={{color: T.ink, fontSize: 14}}>Total due</strong>}
              amount={<strong style={{color: T.ink, fontSize: 16}}>₦100,008</strong>}
              total
            />
            <BreakdownRow
              label={<span style={{color: T.success}}>Total paid</span>}
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

      {/* Right column: meta + dispute + carryover */}
      <div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
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
          <Kvp label="Customer since" value="14 Feb 2026" />
          <Kvp label="Total shipments" value="14" />
          <Kvp label="Outstanding (all)" value={<Mono color={T.error}>₦50,656</Mono>} divider={false} />
        </Card>

        <Card>
          <SectionHead title="CBM dispute" />
          <div style={{height: 12}} />
          <Banner variant="success" title="Resolved · CBM corrected">
            Customer claimed 0.86 CBM (vs original 0.93). China Office re-measured and confirmed adjustment.
          </Banner>
          <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 14}}>
            <SummaryTile label="Original CBM" value="0.93" sub="China measurement" />
            <SummaryTile label="Corrected CBM" value="0.86" sub="−0.07 saved" color={T.success} />
          </div>
        </Card>
      </div>
    </div>

    {/* Payment history */}
    <Card padding={0} style={{marginBottom: 20}}>
      <div style={{padding: '18px 20px'}}>
        <SectionHead title="Payment history" sub="1 payment recorded" action={
          <Button variant="accent" size="sm" icon="coin">Record payment</Button>
        } />
      </div>
      <Table
        dense
        columns={[
          {title: 'Payment ID'},
          {title: 'Amount', align: 'right'},
          {title: 'Method'},
          {title: 'Reference'},
          {title: 'Confirmed by'},
          {title: 'Confirmed at'},
          {title: '', width: 40},
        ]}
        rows={[
          {cells: [
            <Mono color={T.ink}>PAY-20260728-001</Mono>,
            <Mono color={T.success}>₦49,352</Mono>,
            <div style={{display: 'inline-flex', alignItems: 'center', gap: 6}}><Icon name="card" size={13} color={T.info} /><span style={{fontSize: 12, color: T.ink}}>Bank transfer</span></div>,
            <Mono color={T.ink3}>ZNB-2026-04792</Mono>,
            <UserCell name="Ifeoma Uche" email="Nigeria Office" />,
            <Mono color={T.ink3}>28 Jul, 14:32</Mono>,
            <KebabBtn />,
          ]},
        ]}
        emptyState={null}
      />
    </Card>

    {/* Misc charges + carryover sections */}
    <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Miscellaneous charges" sub="2 charges totalling ₦23,500" action={
            <Button variant="secondary" size="sm" icon="plus">Add charge</Button>
          } />
        </div>
        <Table
          dense
          columns={[
            {title: 'Charge'},
            {title: 'Amount', align: 'right'},
            {title: 'Added by'},
            {title: '', width: 40},
          ]}
          rows={[
            {cells: [<div><div style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Customs Examination</div><div style={{fontSize: 11, color: T.ink4}}>Tin Can Port inspection · 28 Jul</div></div>, <Mono>₦15,000</Mono>, <UserCell name="Ifeoma Uche" email="Nigeria Office" />, <button style={{background: 'transparent', border: 0, color: T.error, padding: 4, cursor: 'pointer', display: 'flex'}}><Icon name="x" size={13} /></button>]},
            {cells: [<div><div style={{fontWeight: 600, color: T.ink, fontSize: 13}}>Port Handling Surcharge</div><div style={{fontSize: 11, color: T.ink4}}>Apapa handling fee · 28 Jul</div></div>, <Mono>₦8,500</Mono>, <UserCell name="Ifeoma Uche" email="Nigeria Office" />, <button style={{background: 'transparent', border: 0, color: T.error, padding: 4, cursor: 'pointer', display: 'flex'}}><Icon name="x" size={13} /></button>]},
          ]}
        />
      </Card>

      <Card padding={0}>
        <div style={{padding: '18px 20px'}}>
          <SectionHead title="Carryovers" sub="Outstanding balances applied to this billing" />
        </div>
        <Table
          dense
          columns={[
            {title: 'Source'},
            {title: 'Amount', align: 'right'},
            {title: 'Status'},
            {title: '', width: 90},
          ]}
          rows={[
            {cells: [
              <div><Mono color={T.ink}>BL-20260712-031</Mono><div style={{fontSize: 11, color: T.ink4, marginTop: 2}}>Outstanding from 12 Jul</div></div>,
              <Mono>₦8,500</Mono>,
              <Badge variant="purple" size="sm">Applied</Badge>,
              <Button variant="ghost" size="sm">Exempt</Button>,
            ]},
          ]}
          emptyState={null}
        />
      </Card>
    </div>

    {/* Storage fees section (shown when storage prop set) */}
    {storage && (
      <Card padding={0} style={{marginTop: 20}}>
        <div style={{padding: '18px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <SectionHead title="Storage fees" sub="Accrue daily after the free-storage period expires" />
          <span style={{display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.ink4}}>
            <Icon name="info" size={13} color={T.ink4} /> Added to total outstanding
          </span>
        </div>
        <div style={{padding: '0 20px 16px'}}>
          <Banner variant="warning" title="₦12,000 in storage fees have accrued">
            ₦2,000/day × 6 days. Free-storage period expired 19 Apr 2026. Fees stop accruing once the customer collects their goods.
          </Banner>
        </div>
        <Table
          dense
          columns={[
            {title: 'Period'},
            {title: 'Days', align: 'right'},
            {title: 'Rate/day', align: 'right'},
            {title: 'Amount', align: 'right'},
            {title: 'Status'},
            {title: 'Notes'},
          ]}
          rows={[
            {cells: [<span style={{fontSize: 12, color: T.ink2}}>20 – 25 Apr 2026</span>, <Mono>5</Mono>, <Mono>₦2,000</Mono>, <Mono>₦10,000</Mono>, <Badge variant="error" size="sm">Unpaid</Badge>, <span style={{fontSize: 12, color: T.ink4}}>Free period expired 19 Apr</span>]},
            {cells: [<span style={{fontSize: 12, color: T.ink2}}>26 Apr 2026</span>, <Mono>1</Mono>, <Mono>₦2,000</Mono>, <Mono>₦2,000</Mono>, <Badge variant="warning" size="sm">Accruing</Badge>, <span style={{fontSize: 12, color: T.ink4}}>Today</span>], suspended: true},
          ]}
        />
        <div style={{padding: '14px 20px', borderTop: `2px solid ${T.line}`, background: T.warningSoft + '55', display: 'flex', justifyContent: 'flex-end', gap: 8, fontSize: 14, fontWeight: 700}}>
          <span style={{color: T.ink3, fontWeight: 500}}>Total storage fees:</span> <Mono color={T.warningStrong}>₦12,000</Mono>
        </div>
      </Card>
    )}

    {withPaymentModal && <RecordPaymentModal />}
    {withChargeModal && <AddChargeModal />}
    {withCarryoverModal && <ApplyCarryoverModal />}
    {withReleaseModal && <ReleaseWithOutstandingModal />}
  </PageShell>
);

// ============================================================
// 14.5 — APPLY CARRYOVER MODAL
// ============================================================
const ApplyCarryoverModal = () => (
  <ModalOverlay>
    <div style={{width: 480, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Apply outstanding carryover</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>BL-20260728-001 · Ngozi Okonkwo</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        {/* Carryover detail card */}
        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, padding: 16, marginBottom: 16}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10}}>Carryover detail</div>
          <Kvp label="Amount" value={<Mono color={T.ink} style={{fontWeight: 700}}>₦8,500.00</Mono>} />
          <Kvp label="Source billing" value={<Mono>BL-20260201-003</Mono>} />
          <Kvp label="Created" value="1 Feb 2026" />
          <Kvp label="Status" value={<Badge variant="warning" size="sm">Outstanding</Badge>} divider={false} />
        </div>

        {/* Effect preview */}
        <div style={{background: '#fff', border: `1px solid ${T.line}`, borderRadius: 10, padding: 16, marginBottom: 16, fontFamily: T.mono, fontSize: 13}}>
          <div style={{display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: T.ink2}}>
            <span>Current total due</span><span>₦49,352.00</span>
          </div>
          <div style={{display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: T.warningStrong}}>
            <span>Carryover applied</span><span>+ ₦8,500.00</span>
          </div>
          <div style={{borderTop: `1px solid ${T.line}`, margin: '6px 0'}} />
          <div style={{display: 'flex', justifyContent: 'space-between', padding: '4px 0', color: T.ink, fontWeight: 700}}>
            <span>New total due</span><span>₦57,852.00</span>
          </div>
        </div>

        <Banner variant="warning" title="This increases the customer's debt">
          Applying this carryover raises the amount owed on this billing. This action cannot be undone.
        </Banner>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="danger-outline" icon="check">Apply carryover</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 14.6 — RELEASE WITH OUTSTANDING BALANCE
// ============================================================
const ReleaseWithOutstandingModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Generate release note</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>BL-20260728-001 · Ngozi Okonkwo · partially paid</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        {/* Disabled normal path */}
        <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, marginBottom: 16, opacity: 0.8}}>
          <Button variant="primary" full disabled icon="card">Generate release note</Button>
          <div style={{fontSize: 12, color: T.ink4, textAlign: 'center', marginTop: 8}}>
            Billing must be fully paid to release goods. <strong style={{color: T.error}}>₦24,352 outstanding.</strong>
          </div>
        </div>

        {/* Expander — expanded state */}
        <div style={{border: `2px solid ${T.warning}`, borderRadius: 10, overflow: 'hidden'}}>
          <div style={{padding: '12px 16px', background: T.warningSoft, display: 'flex', alignItems: 'center', gap: 8}}>
            <Icon name="warn" size={16} color={T.warning} stroke={2.5} />
            <span style={{fontFamily: T.display, fontWeight: 700, fontSize: 14, color: T.warningStrong, flex: 1}}>Release with outstanding balance?</span>
            <Icon name="chevup" size={14} color={T.warningStrong} />
          </div>
          <div style={{padding: 16}}>
            <p style={{fontSize: 13, color: T.ink2, margin: '0 0 12px', lineHeight: 1.55}}>
              You're about to release goods to a customer who has <strong>not fully paid</strong>. Outstanding amount: <strong style={{color: T.error}}>₦24,352.00</strong>. This action is logged and audited.
            </p>
            <Field label="Approval notes" required multiline value="Long-standing customer (42 shipments). Tenant Admin Amara approved release on credit — settlement agreed by 05 Aug." />
            <label style={{display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, color: T.ink2, fontWeight: 500, cursor: 'pointer', marginBottom: 4}}>
              <Check checked /> I confirm this release is authorized by Tenant Admin
            </label>
          </div>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="danger" icon="card">Release anyway</Button>
      </div>
    </div>
  </ModalOverlay>
);

const BreakdownRow = ({label, amount, accent, removable, total, outstanding, note}) => (
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
      {removable && (
        <button style={{marginLeft: 8, background: 'transparent', border: 0, color: T.ink4, padding: 2, cursor: 'pointer', display: 'inline-flex', verticalAlign: 'middle'}}>
          <Icon name="x" size={13} />
        </button>
      )}
    </td>
  </tr>
);

// ============================================================
// 7.2a — RECORD PAYMENT MODAL
// ============================================================
const RecordPaymentModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Record payment</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>BL-20260728-001 · Ngozi Okonkwo</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        {/* Outstanding summary */}
        <div style={{
          padding: 16, background: T.errorSoft + '88', border: `1px solid ${T.error}33`,
          borderRadius: 10, marginBottom: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <div style={{fontSize: 11, fontWeight: 700, color: T.errorStrong, textTransform: 'uppercase', letterSpacing: '0.06em'}}>Outstanding</div>
            <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 26, color: T.errorStrong, letterSpacing: '-0.02em', marginTop: 2}}>₦50,656</div>
          </div>
          <div style={{textAlign: 'right', fontSize: 11, color: T.ink3}}>
            <div>Total due: <strong style={{color: T.ink}}>₦100,008</strong></div>
            <div style={{marginTop: 2}}>Paid: <strong style={{color: T.success}}>₦49,352</strong></div>
          </div>
        </div>

        <Field label="Amount paid (NGN)" required prefix="₦" value="50,656" focused helper="Pre-filled with outstanding amount. Editable for partial or over-payment." />
        <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
          <Field label="Payment method" required>
            <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, cursor: 'pointer'}}>
              <Icon name="card" size={15} color={T.info} />
              <span style={{flex: 1, fontSize: 14, color: T.ink}}>Bank transfer</span>
              <Icon name="chevdown" size={14} color={T.ink4} />
            </div>
          </Field>
          <Field label="Confirmed at" required icon="calendar" value="28 Jul 2026, 14:32" />
        </div>
        <Field label="Payment reference" required value="ZNB-2026-04792" placeholder="Bank ref, USSD ref, etc." helper="Transaction reference number from the bank or gateway." />
        <Field label="Notes" optional multiline value="" placeholder="Anything to flag about this payment (e.g. partial, third-party transfer)…" />

        {/* Effect preview */}
        <div style={{background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, padding: 14, marginTop: 8}}>
          <div style={{fontSize: 11, fontWeight: 700, color: T.ink3, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10}}>After this payment</div>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13}}>
            <span style={{color: T.ink2}}>Outstanding becomes</span>
            <Mono color={T.success} style={{fontSize: 16, fontWeight: 700}}>₦0 · Paid in full</Mono>
          </div>
          <div style={{fontSize: 12, color: T.ink3, marginTop: 6, padding: '8px 10px', background: T.greenTint, borderRadius: 6, display: 'flex', alignItems: 'center', gap: 6}}>
            <Icon name="check" size={13} color={T.success} stroke={2.5} /> Customer becomes eligible for release note generation.
          </div>
        </div>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="accent" icon="check">Confirm payment</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 7.2b — ADD CHARGE MODAL
// ============================================================
const AddChargeModal = () => (
  <ModalOverlay>
    <div style={{width: 560, background: '#fff', borderRadius: 14, boxShadow: T.shadowModal, fontFamily: T.body}}>
      <div style={{padding: '20px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
        <div>
          <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 18, margin: 0, color: T.ink, letterSpacing: '-0.01em'}}>Add miscellaneous charge</h3>
          <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>BL-20260728-001 · Ngozi Okonkwo</p>
        </div>
        <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, borderRadius: 6, display: 'flex'}}>
          <Icon name="x" size={18} />
        </button>
      </div>
      <div style={{padding: '20px 24px'}}>
        <Field label="Charge type" required>
          <div style={{height: 40, background: '#fff', border: `1px solid ${T.lineStrong}`, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 14px', gap: 10, cursor: 'pointer'}}>
            <span style={{fontSize: 14, color: T.ink, fontWeight: 500}}>Customs Examination</span>
            <span style={{fontFamily: T.mono, fontSize: 11, color: T.ink4, padding: '2px 6px', background: T.muted, borderRadius: 4}}>default ₦15,000</span>
            <span style={{flex: 1}} />
            <Icon name="chevdown" size={14} color={T.ink4} />
          </div>
        </Field>
        <Field label="Description override" optional value="" placeholder="Defaults to: Physical inspection at Tin Can Port" />
        <Field label="Amount (NGN)" required prefix="₦" value="15,000" helper="Pre-filled with default. Editable for one-off variations." />

        <Banner variant="info" title="This charge will be added to BL-20260728-001">
          Total due increases from ₦100,008 to ₦115,008. Outstanding increases from ₦50,656 to ₦65,656.
        </Banner>
      </div>
      <div style={{padding: '14px 24px', borderTop: `1px solid ${T.line}`, display: 'flex', justifyContent: 'flex-end', gap: 10, background: T.muted, borderRadius: '0 0 14px 14px'}}>
        <Button variant="ghost">Cancel</Button>
        <Button variant="primary" icon="plus">Add charge</Button>
      </div>
    </div>
  </ModalOverlay>
);

// ============================================================
// 7.3 — CBM DISPUTES
// ============================================================
const CbmDisputes = ({withDetail} = {}) => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('disputes')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="CBM disputes" breadcrumb={['Billing', 'CBM disputes']} user={ngUser} />}
  >
    {/* Stats */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Open" value="2" sublabel="awaiting your response" accent={<Icon name="warn" size={15} stroke={2.2} />} />
      <StatCard label="Investigating" value="3" sublabel="China re-measuring" accent={<Icon name="refresh" size={15} stroke={2.2} />} />
      <StatCard label="Resolved (30d)" value="18" trend="+6" trendDir="up" sublabel="61% adjusted · 39% no change" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Avg resolution time" value="2.4" suffix="days" trend="−0.6d" trendDir="down" sublabel="faster vs Q1" accent={<Icon name="clock" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6, flexWrap: 'wrap'}}>
          <Chip active>All <span style={{opacity: 0.5}}>32</span></Chip>
          <Chip count={2}>Submitted</Chip>
          <Chip count={1}>Acknowledged</Chip>
          <Chip count={3}>Investigating</Chip>
          <Chip count={4}>Escalated to China</Chip>
          <Chip count={14}>Resolved · adjusted</Chip>
          <Chip count={8}>Resolved · no change</Chip>
        </div>
        <div style={{flex: 1}} />
        <Button variant="secondary" size="md" icon="filter">More filters</Button>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Dispute ID', sortable: true},
          {title: 'Customer'},
          {title: 'Container'},
          {title: 'Billing'},
          {title: 'Original CBM', align: 'right'},
          {title: "Customer's CBM", align: 'right'},
          {title: 'Diff', align: 'right'},
          {title: 'Status'},
          {title: 'Filed', sortable: true},
          {title: '', width: 110},
        ]}
        rows={[
          disputeRow({id: 'CBM-20260728-001', cust: 'Ngozi Okonkwo', container: 'MSCU1234567', bl: 'BL-20260728-001', orig: '0.93', claimed: '0.56', status: 'submitted', filed: '12 min ago'}),
          disputeRow({id: 'CBM-20260728-002', cust: 'Adaeze Nwosu', container: 'MSCU1234567', bl: 'BL-20260728-008', orig: '0.42', claimed: '0.34', status: 'submitted', filed: '1 hr ago', selected: true}),
          disputeRow({id: 'CBM-20260727-003', cust: 'Funmilayo Adeyemi', container: 'HLBU9384712', bl: 'BL-20260727-014', orig: '1.42', claimed: '1.20', status: 'acknowledged', filed: 'Yesterday'}),
          disputeRow({id: 'CBM-20260726-004', cust: 'Emeka Eze', container: 'HLBU9384712', bl: 'BL-20260726-021', orig: '2.14', claimed: '1.84', status: 'investigating', filed: '26 Jul'}),
          disputeRow({id: 'CBM-20260725-005', cust: 'Ibrahim Musa', container: 'COSU7194820', bl: 'BL-20260725-008', orig: '1.18', claimed: '1.10', status: 'escalated', filed: '25 Jul'}),
          disputeRow({id: 'CBM-20260722-006', cust: 'Bola Adesina', container: 'COSU7194820', bl: 'BL-20260722-024', orig: '0.72', claimed: '0.68', status: 'resolved_adjusted', filed: '22 Jul'}),
          disputeRow({id: 'CBM-20260718-007', cust: 'Aisha Lawal', container: 'ONEU2847510', bl: 'BL-20260718-011', orig: '0.94', claimed: '0.70', status: 'resolved_no_change', filed: '18 Jul'}),
        ]}
      />
      <TablePagination />
    </Card>

    {withDetail && <DisputeDetailPanel />}
  </PageShell>
);

const disputeRow = ({id, cust, container, bl, orig, claimed, status, filed, selected}) => {
  const diff = (parseFloat(orig) - parseFloat(claimed)).toFixed(2);
  const badge = {
    submitted: <Badge variant="error">Submitted</Badge>,
    acknowledged: <Badge variant="warning">Acknowledged</Badge>,
    investigating: <Badge variant="info">Investigating</Badge>,
    escalated: <Badge variant="purple">Escalated to China</Badge>,
    resolved_adjusted: <Badge variant="success">Resolved · adjusted</Badge>,
    resolved_no_change: <Badge variant="neutral">Resolved · no change</Badge>,
  }[status];
  return {
    selected,
    cells: [
      <Mono color={T.ink}>{id}</Mono>,
      <UserCell name={cust} email={''} />,
      <Mono>{container}</Mono>,
      <Mono color={T.ink3}>{bl}</Mono>,
      <Mono>{orig}</Mono>,
      <Mono>{claimed}</Mono>,
      <Mono color={diff > 0 ? T.error : T.success}>{diff > 0 ? `−${diff}` : `+${Math.abs(diff).toFixed(2)}`}</Mono>,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{filed}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        {status === 'submitted' && <Button variant="accent" size="sm">Acknowledge</Button>}
        {status === 'acknowledged' && <Button variant="primary" size="sm">Investigate</Button>}
        {status === 'investigating' && <Button variant="primary" size="sm">Resolve</Button>}
        {status === 'escalated' && <Button variant="ghost" size="sm">View</Button>}
        {(status === 'resolved_adjusted' || status === 'resolved_no_change') && <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

const DisputeDetailPanel = () => (
  <div style={{
    position: 'absolute', top: 0, right: 0, bottom: 0,
    width: 540, background: '#fff',
    boxShadow: '-12px 0 32px rgba(11,47,13,0.18)',
    display: 'flex', flexDirection: 'column',
    fontFamily: T.body, zIndex: 50,
  }}>
    {/* Header */}
    <div style={{padding: '18px 24px', borderBottom: `1px solid ${T.line}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
      <div>
        <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4}}>
          <Mono color={T.ink} style={{fontSize: 14, fontWeight: 700}}>CBM-20260728-002</Mono>
          <Badge variant="error">Submitted</Badge>
        </div>
        <div style={{fontSize: 13, color: T.ink3}}>Adaeze Nwosu · BL-20260728-008</div>
      </div>
      <button style={{background: 'transparent', border: 0, padding: 6, cursor: 'pointer', color: T.ink4, display: 'flex'}}>
        <Icon name="x" size={18} />
      </button>
    </div>
    {/* Body */}
    <div style={{flex: 1, overflowY: 'auto', padding: 24}}>
      {/* CBM compare */}
      <div className="sx-cols" style={{display: 'grid', gridTemplateColumns: '1fr 24px 1fr', gap: 12, marginBottom: 20}}>
        <div style={{padding: 16, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, textAlign: 'center'}}>
          <div style={{fontSize: 10, fontWeight: 700, color: T.ink4, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>Original</div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 32, color: T.ink, letterSpacing: '-0.02em', lineHeight: 1}}>0.42</div>
          <div style={{fontSize: 11, color: T.ink4, marginTop: 4}}>China measurement</div>
        </div>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4}}>
          <Icon name="arrowright" size={18} stroke={2.5} />
        </div>
        <div style={{padding: 16, background: T.errorSoft, border: `1px solid ${T.error}33`, borderRadius: 10, textAlign: 'center'}}>
          <div style={{fontSize: 10, fontWeight: 700, color: T.errorStrong, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4}}>Customer claims</div>
          <div style={{fontFamily: T.display, fontWeight: 800, fontSize: 32, color: T.errorStrong, letterSpacing: '-0.02em', lineHeight: 1}}>0.34</div>
          <div style={{fontSize: 11, color: T.errorStrong, marginTop: 4}}>−0.08 (₦6,336 less)</div>
        </div>
      </div>

      {/* Customer statement */}
      <SectionHead title="Customer's reason" />
      <div style={{padding: 14, background: T.muted, border: `1px solid ${T.line}`, borderRadius: 10, marginTop: 8, marginBottom: 20}}>
        <p style={{margin: 0, fontSize: 13, color: T.ink2, lineHeight: 1.55, fontStyle: 'italic'}}>
          "I personally measured all my cartons before they shipped — the measurements I have differ from what the China warehouse logged. Attaching photos of each carton with a tape measure."
        </p>
      </div>

      {/* Evidence */}
      <SectionHead title="Photo evidence" sub="4 photos uploaded by customer" />
      <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 8, marginBottom: 20}}>
        {[1,2,3,4].map(i => (
          <div key={i} style={{
            aspectRatio: '1', borderRadius: 8, background: T.line,
            border: `1px solid ${T.lineStrong}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.ink4,
          }}>
            <Icon name="package" size={24} stroke={1.5} />
          </div>
        ))}
      </div>

      {/* Status timeline */}
      <SectionHead title="Status timeline" />
      <div style={{marginTop: 12, marginBottom: 20}}>
        <DispEvent icon="warn" color={T.error} title="Submitted" sub="By Adaeze Nwosu" when="1 hour ago" current />
        <DispEvent icon="check" color={T.ink4} title="Acknowledge by Nigeria" sub="Pending action from you" />
        <DispEvent icon="refresh" color={T.ink4} title="Investigate" sub="Review evidence + decide" />
        <DispEvent icon="check" color={T.ink4} title="Resolve or escalate" sub="Adjust CBM, no change, or send to China" last />
      </div>

      {/* Actions */}
      <Card style={{background: T.warningSoft, border: `1px solid ${T.warning}55`}}>
        <SectionHead title="Action required" sub="Acknowledge this dispute to move it forward" />
        <div style={{height: 12}} />
        <Field label="Internal notes (optional)" multiline value="" placeholder="Notes for your team — visible internally only" />
        <div style={{display: 'flex', gap: 8}}>
          <Button variant="ghost" full>Reject claim</Button>
          <Button variant="accent" full icon="check">Acknowledge dispute</Button>
        </div>
      </Card>
    </div>
  </div>
);

const DispEvent = ({icon, color, title, sub, when, current, last}) => (
  <div style={{display: 'flex', gap: 12, paddingBottom: last ? 0 : 12, position: 'relative'}}>
    {!last && <div style={{position: 'absolute', left: 13, top: 28, bottom: 0, width: 2, background: T.line}} />}
    <div style={{
      width: 28, height: 28, borderRadius: '50%',
      background: current ? color + '22' : '#fff',
      border: `2px solid ${color}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0, zIndex: 1,
      boxShadow: current ? `0 0 0 5px ${color}22` : 'none',
    }}>
      <Icon name={icon} size={12} color={color} stroke={2.5} />
    </div>
    <div style={{flex: 1, paddingTop: 3}}>
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8}}>
        <div style={{fontSize: 13, fontWeight: 600, color: current ? T.ink : T.ink3}}>{title}</div>
        {when && <div style={{fontSize: 11, color: T.ink4, fontFamily: T.mono}}>{when}</div>}
      </div>
      <div style={{fontSize: 12, color: T.ink4, marginTop: 1}}>{sub}</div>
    </div>
  </div>
);

// ============================================================
// 7.4 — CARRYOVERS
// ============================================================
const CarryoverLedger = () => (
  <PageShell
    sidebar={<Sidebar role="nigeria" brand={tenantBrand} items={ngSidebarItems('carryovers')} user={ngUser} />}
    topbar={<TopBar role="nigeria" title="Carryover ledger" breadcrumb={['Billing', 'Carryovers']} user={ngUser} actions={
      <Button variant="secondary" icon="download">Export ledger</Button>
    } />}
  >
    <Banner variant="info" title="What's a carryover?">
      When a billing record closes with an outstanding balance, that amount becomes a <strong>carryover</strong> and is automatically applied to the customer's next billing. You can exempt specific carryovers if the customer has reached an alternate settlement (e.g. a refund offset, a written-off small balance).
    </Banner>
    <div style={{height: 20}} />

    {/* Stats */}
    <div className="sx-grid4" style={{display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 20}}>
      <StatCard label="Active carryovers" value="14" sublabel="not yet applied" accent={<Icon name="refresh" size={15} stroke={2.2} />} />
      <StatCard label="Total active value" value="₦284k" sublabel="across 11 customers" accent={<Icon name="coin" size={15} stroke={2.2} />} />
      <StatCard label="Applied this month" value="9" trend="+3" trendDir="up" sublabel="settled forward" accent={<Icon name="check" size={15} stroke={2.2} />} />
      <StatCard label="Exempted (all time)" value="6" sublabel="₦42k written off" accent={<Icon name="x" size={15} stroke={2.2} />} />
    </div>

    <Card padding={16} style={{marginBottom: 16}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap'}}>
        <div style={{display: 'flex', gap: 6}}>
          <Chip active>All <span style={{opacity: 0.5}}>24</span></Chip>
          <Chip count={14}>Active</Chip>
          <Chip count={4}>Applied</Chip>
          <Chip count={6}>Exempted</Chip>
        </div>
        <div style={{flex: 1, minWidth: 240}}>
          <div style={{position: 'relative', height: 36, background: T.page, borderRadius: 8, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8}}>
            <Icon name="search" size={14} color={T.ink4} />
            <input placeholder="Customer name, source billing…" style={{flex: 1, border: 0, outline: 0, background: 'transparent', fontFamily: T.body, fontSize: 13, color: T.ink}} />
          </div>
        </div>
      </div>
    </Card>

    <Card padding={0}>
      <Table
        columns={[
          {title: 'Customer'},
          {title: 'Source billing'},
          {title: 'Amount', align: 'right'},
          {title: 'Applied to'},
          {title: 'Status'},
          {title: 'Created', sortable: true},
          {title: 'Notes'},
          {title: '', width: 90},
        ]}
        rows={[
          coRow({cust: 'Ngozi Okonkwo', src: 'BL-20260712-031', amount: 8500, applied: 'BL-20260728-001', status: 'active', when: '12 Jul', note: 'Partial payment rolled forward'}),
          coRow({cust: 'Emeka Eze', src: 'BL-20260620-018', amount: 24000, applied: '—', status: 'active', when: '20 Jun', note: 'Awaiting next billing'}),
          coRow({cust: 'Funmilayo Adeyemi', src: 'BL-20260615-044', amount: 5680, applied: 'BL-20260727-014', status: 'active', when: '15 Jun', note: 'Late fee not paid'}),
          coRow({cust: 'Adaeze Nwosu', src: 'BL-20260610-019', amount: 3200, applied: 'BL-20260728-008', status: 'active', when: '10 Jun', note: ''}),
          coRow({cust: 'Ibrahim Musa', src: 'BL-20260605-051', amount: 12800, applied: 'BL-20260725-008', status: 'applied', when: '05 Jun', note: 'Settled in July billing'}),
          coRow({cust: 'Bola Adesina', src: 'BL-20260528-068', amount: 4200, applied: '—', status: 'exempted', when: '28 May', note: 'Goodwill — small amount written off'}),
        ]}
      />
      <TablePagination />
    </Card>
  </PageShell>
);

const coRow = ({cust, src, amount, applied, status, when, note}) => {
  const badge = {
    active: <Badge variant="warning">Active</Badge>,
    applied: <Badge variant="success">Applied</Badge>,
    exempted: <Badge variant="neutral">Exempted</Badge>,
  }[status];
  return {
    suspended: status === 'exempted',
    cells: [
      <UserCell name={cust} email={''} />,
      <Mono color={T.ink3}>{src}</Mono>,
      <Mono color={status === 'exempted' ? T.ink4 : T.warningStrong}>₦{amount.toLocaleString()}</Mono>,
      <Mono color={applied === '—' ? T.ink4 : T.green}>{applied}</Mono>,
      badge,
      <span style={{fontSize: 12, color: T.ink3}}>{when}</span>,
      <span style={{fontSize: 12, color: T.ink3, fontStyle: note ? 'italic' : 'normal'}}>{note || '—'}</span>,
      <div style={{display: 'flex', justifyContent: 'flex-end'}}>
        {status === 'active' && <Button variant="ghost" size="sm">Exempt</Button>}
        {status !== 'active' && <Button variant="ghost" size="sm">View</Button>}
      </div>,
    ],
  };
};

Object.assign(window, {
  BillingList, BillingDetail, CbmDisputes, CarryoverLedger,
  RecordPaymentModal, AddChargeModal, ApplyCarryoverModal, ReleaseWithOutstandingModal,
  DispEvent,
});
