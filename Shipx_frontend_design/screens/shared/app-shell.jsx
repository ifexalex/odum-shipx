// ============================================================
// Shipx — App Shell (Sidebar + TopBar + Page)
// Reusable across all portals (Platform, Tenant Admin, China, Nigeria, etc.)
// ============================================================

const ROLE_CONFIG = {
  platform: {label: 'Platform', color: T.rolePlatform, badgeColor: '#fff', badgeBg: T.rolePlatform},
  admin: {label: 'Admin', color: T.green, badgeBg: T.green, badgeColor: '#fff'},
  china: {label: 'China Office', color: T.roleChina, badgeBg: T.roleChina, badgeColor: '#fff'},
  nigeria: {label: 'Nigeria Office', color: T.copper, badgeBg: T.copper, badgeColor: '#fff'},
  warehouse: {label: 'Warehouse', color: T.warning, badgeBg: T.warning, badgeColor: '#fff'},
  customer: {label: '', color: T.greenFlash, badgeBg: T.greenFlash, badgeColor: T.greenForest},
};

// ============================================================
// SIDEBAR
// ============================================================
const Sidebar = ({role = 'platform', brand, items = [], user, width = 248}) => {
  const cfg = ROLE_CONFIG[role];
  return (
    <aside className="sx-sidebar" style={{
      width, flexShrink: 0,
      background: 'linear-gradient(180deg, #0b2f0d 0%, #0d3810 62%, #10431a 100%)',
      color: 'rgba(255,255,255,0.85)',
      display: 'flex', flexDirection: 'column',
      fontFamily: T.body,
      height: '100%',
    }}>
      {/* Brand area */}
      <div style={{padding: '20px 20px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)'}}>
        {brand ? brand : <DefaultBrand />}
      </div>
      {/* Role badge */}
      {cfg.label && (
        <div style={{padding: '14px 20px 4px'}}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            background: cfg.badgeBg, color: cfg.badgeColor,
            padding: '3px 10px', borderRadius: 9999,
            fontSize: 10, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase',
          }}>
            <Icon name="shield" size={10} fill={cfg.badgeColor} color={cfg.badgeColor} stroke={0} /> {cfg.label}
          </span>
        </div>
      )}
      {/* Nav */}
      <nav style={{flex: 1, padding: '8px 12px', overflowY: 'auto'}}>
        {items.map((sec, i) => (
          <div key={i} style={{marginTop: i === 0 ? 8 : 18}}>
            {sec.group && (
              <div style={{
                padding: '6px 10px', fontSize: 10, letterSpacing: '0.14em',
                textTransform: 'uppercase', fontWeight: 700,
                color: 'rgba(255,255,255,0.42)',
              }}>{sec.group}</div>
            )}
            {sec.items.map((it, j) => (
              <NavItem key={j} {...it} role={role} />
            ))}
          </div>
        ))}
      </nav>
      {/* User footer */}
      <div style={{padding: 12, borderTop: '1px solid rgba(255,255,255,0.06)'}}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '8px 10px', borderRadius: 12, background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.08)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.05)',
        }}>
          <Avatar size={32} name={user?.name || 'User'} role={role} />
          <div style={{flex: 1, minWidth: 0}}>
            <div style={{color: '#fff', fontWeight: 600, fontSize: 13, lineHeight: 1.2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{user?.name || 'Joe Operator'}</div>
            <div style={{color: 'rgba(255,255,255,0.5)', fontSize: 11, lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{user?.role || cfg.label}</div>
          </div>
          <button style={{background: 'transparent', border: 0, padding: 6, color: 'rgba(255,255,255,0.6)', cursor: 'pointer', borderRadius: 6, display: 'flex'}}>
            <Icon name="logout" size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
};

const DefaultBrand = () => (
  <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
    <KolaMark size={28} color={T.greenFlash} />
    <ShipxWordmark size={22} color="#fff" xColor={T.copper} />
  </div>
);

const TenantBrand = ({name, logo}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 10}}>
    <div style={{width: 32, height: 32, borderRadius: 8, background: T.copperSoft, color: T.copperDeep, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 14, fontFamily: T.display, flexShrink: 0}}>
      {logo || name.slice(0, 2).toUpperCase()}
    </div>
    <div style={{minWidth: 0}}>
      <div style={{color: '#fff', fontWeight: 700, fontSize: 14, fontFamily: T.display, lineHeight: 1.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{name}</div>
      <div style={{color: 'rgba(255,255,255,0.45)', fontSize: 10, letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600, marginTop: 1}}>on Shipx</div>
    </div>
  </div>
);

const NavItem = ({icon, label, active, badge, count, sub, role}) => {
  const accentBright = role === 'platform' ? T.rolePlatform : role === 'china' ? T.roleChina : role === 'nigeria' ? T.copper : role === 'warehouse' ? T.warning : T.greenFlash;
  return (
    <div>
      <div className={active ? undefined : 'sx-nav'} style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '8px 12px', borderRadius: 10,
        background: active ? 'linear-gradient(180deg, rgba(255,255,255,0.10), rgba(255,255,255,0.06))' : 'transparent',
        boxShadow: active ? 'inset 0 1px 0 rgba(255,255,255,0.08), 0 1px 3px rgba(0,0,0,0.18)' : 'none',
        transition: 'background .15s, color .15s',
        color: active ? '#fff' : 'rgba(255,255,255,0.7)',
        fontWeight: active ? 600 : 500,
        fontSize: 13.5,
        cursor: 'pointer',
        position: 'relative',
      }}>
        {active && <div style={{position: 'absolute', left: -12, top: 6, bottom: 6, width: 3, background: accentBright, borderRadius: 2}} />}
        {icon && <Icon name={icon} size={16} stroke={2} />}
        <span style={{flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{label}</span>
        {badge && <span style={{background: badge.color, color: '#fff', borderRadius: 999, padding: '1px 7px', fontSize: 10, fontWeight: 700, minWidth: 18, textAlign: 'center'}}>{badge.count}</span>}
        {count && <span style={{color: 'rgba(255,255,255,0.4)', fontSize: 11, fontFamily: T.mono}}>{count}</span>}
      </div>
    </div>
  );
};

// ============================================================
// TOPBAR
// ============================================================
const TopBar = ({title, breadcrumb, search = true, role = 'platform', user, actions, notifications = 3}) => (
  <header className="sx-topbar" style={{
    height: 64, background: 'rgba(255,255,255,0.82)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
    borderBottom: `1px solid ${T.line}`, position: 'relative', zIndex: 5,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0 32px', flexShrink: 0, fontFamily: T.body,
  }}>
    <div style={{display: 'flex', alignItems: 'center', gap: 12, minWidth: 0}}>
      <button className="sx-hamburger sx-icbtn" aria-label="Open menu" style={{
        width: 38, height: 38, borderRadius: 10, background: T.page, border: 'none',
        alignItems: 'center', justifyContent: 'center', cursor: 'pointer', color: T.ink2, padding: 0, flexShrink: 0,
      }}>
        <Icon name="menu" size={18} stroke={2} />
      </button>
      <div style={{display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0}}>
      {breadcrumb && (
        <div style={{display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.ink4}}>
          {breadcrumb.map((b, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span style={{color: T.lineStrong}}>/</span>}
              <span style={{color: i === breadcrumb.length - 1 ? T.ink2 : T.green, fontWeight: i === breadcrumb.length - 1 ? 500 : 600, cursor: i === breadcrumb.length - 1 ? 'default' : 'pointer'}}>{b}</span>
            </React.Fragment>
          ))}
        </div>
      )}
      {title && <h1 style={{fontFamily: T.display, fontWeight: 700, fontSize: 20, color: T.ink, margin: 0, letterSpacing: '-0.01em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{title}</h1>}
      </div>
    </div>
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      {search && (
        <div className="sx-search" style={{position: 'relative', width: 320}}>
          <div style={{position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: T.ink4, display: 'flex', pointerEvents: 'none'}}>
            <Icon name="search" size={15} />
          </div>
          <input placeholder="Search tenants, users, containers…" style={{
            width: '100%', height: 38, paddingLeft: 36, paddingRight: 48,
            background: T.page, border: `1px solid transparent`, borderRadius: 10,
            boxShadow: 'inset 0 1px 2px rgba(11,47,13,0.04)',
            fontFamily: T.body, fontSize: 13, color: T.ink, outline: 'none',
            boxSizing: 'border-box',
          }} />
          <span style={{
            position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
            color: T.ink3, fontSize: 11, fontFamily: T.body,
            background: '#fff', border: `1px solid ${T.line}`, borderRadius: 4,
            padding: '2px 7px', lineHeight: 1, fontWeight: 700,
          }}>/</span>
        </div>
      )}
      {actions}
      <div style={{position: 'relative', display: 'inline-flex'}}>
        <button className="sx-icbtn" style={{
          width: 38, height: 38, borderRadius: 9999,
          background: T.page, border: 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', color: T.ink2, padding: 0,
        }}>
          <Icon name="bell" size={17} stroke={2} />
        </button>
        {notifications > 0 && (
          <span style={{
            position: 'absolute', top: -2, right: -2,
            background: T.error, color: '#fff',
            borderRadius: 999, fontSize: 10, fontWeight: 700,
            minWidth: 18, height: 18, padding: '0 5px',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: `2px solid #fff`, lineHeight: 1,
          }}>{notifications}</span>
        )}
      </div>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, padding: '4px 14px 4px 4px', borderRadius: 9999, background: T.page, cursor: 'pointer'}}>
        <Avatar size={30} name={user?.name || 'Adaeze Eze'} role={role} />
        <div className="sx-userchip-meta" style={{fontSize: 13}}>
          <div style={{fontWeight: 600, color: T.ink, lineHeight: 1.15, whiteSpace: 'nowrap'}}>{user?.name || 'Adaeze Eze'}</div>
          <div style={{fontSize: 11, color: T.ink4, lineHeight: 1.25, whiteSpace: 'nowrap'}}>{user?.role || ROLE_CONFIG[role]?.label}</div>
        </div>
        <Icon name="chevdown" size={13} color={T.ink4} />
      </div>
    </div>
  </header>
);

// ============================================================
// PAGE SHELL — combines sidebar + topbar + content area
// ============================================================
const PageShell = ({sidebar, topbar, children, bg = T.page, contentPadding = 32}) => (
  <div className="sx-appframe" style={{display: 'flex', height: '100%', background: bg, fontFamily: T.body, color: T.ink}}>
    {sidebar}
    <div style={{flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0}}>
      {topbar}
      <main className="sx-main" style={{flex: 1, overflowY: 'auto', padding: contentPadding}}>
        {children}
      </main>
    </div>
  </div>
);

// Tab strip — used for tabs within pages
const Tabs = ({tabs, active}) => (
  <div style={{display: 'flex', gap: 4, borderBottom: `1px solid ${T.line}`, marginBottom: 24}}>
    {tabs.map((t, i) => (
      <button key={i} className="sx-tab" style={{
        padding: '12px 16px',
        background: 'transparent', border: 0,
        fontFamily: T.body, fontWeight: t === active ? 700 : 500,
        fontSize: 14, color: t === active ? T.green : T.ink3,
        borderBottom: t === active ? `2px solid ${T.green}` : '2px solid transparent',
        marginBottom: -1, cursor: 'pointer',
      }}>{t}</button>
    ))}
  </div>
);

const PageHeader = ({title, subtitle, actions, eyebrow}) => (
  <div className="sx-pagehead" style={{display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24, gap: 16}}>
    <div style={{flex: 1, minWidth: 0}}>
      {eyebrow && <div style={{fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600, color: T.green, marginBottom: 6}}>{eyebrow}</div>}
      <h2 style={{fontFamily: T.display, fontWeight: 700, fontSize: 26, margin: 0, color: T.ink, letterSpacing: '-0.015em', lineHeight: 1.15}}>{title}</h2>
      {subtitle && <p style={{margin: '6px 0 0', fontSize: 14, color: T.ink3}}>{subtitle}</p>}
    </div>
    {actions && <div style={{display: 'flex', gap: 8, flexShrink: 0}}>{actions}</div>}
  </div>
);

// Section heading (for cards within a page)
const SectionHead = ({title, action, sub}) => (
  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12}}>
    <div>
      <h3 style={{fontFamily: T.display, fontWeight: 700, fontSize: 16, margin: 0, color: T.ink, letterSpacing: '-0.005em'}}>{title}</h3>
      {sub && <p style={{margin: '2px 0 0', fontSize: 12, color: T.ink4}}>{sub}</p>}
    </div>
    {action}
  </div>
);

Object.assign(window, {
  Sidebar, TopBar, PageShell, Tabs, PageHeader, SectionHead, DefaultBrand, TenantBrand, ROLE_CONFIG,
});
