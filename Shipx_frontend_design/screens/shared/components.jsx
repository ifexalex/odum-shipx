// ============================================================
// Shipx — Shared UI primitives
// Tokens, Icon, Button, Badge, StatCard, Field, Table cells, etc.
// Used across all portal sections.
// ============================================================

// Inject shared micro-interaction styles once
(() => {
  if (!document.getElementById('shipx-micro')) {
    const s = document.createElement('style');
    s.id = 'shipx-micro';
    s.textContent = `
      .sx-btn { transition: transform .16s cubic-bezier(.2,.7,.3,1), box-shadow .16s, filter .16s; }
      .sx-btn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); box-shadow: 0 6px 14px rgba(11,47,13,0.18); }
      .sx-btn:active:not(:disabled) { transform: translateY(0); filter: brightness(0.97); }
      tr.sx-row { transition: background .12s; }
      tr.sx-row.sx-plain:hover { background: #f6faf6 !important; }
      .sx-nav { transition: background .14s, color .14s; }
      .sx-nav:hover { background: rgba(255,255,255,0.05); color: #fff !important; }
      .sx-chip { transition: border-color .14s, background .14s, transform .14s; }
      .sx-chip:hover { border-color: rgba(28,121,34,0.55); transform: translateY(-1px); }
      .sx-icbtn { transition: background .14s, color .14s, transform .14s; }
      .sx-icbtn:hover { background: #e8ebe8 !important; transform: scale(1.05); }
      .sx-tab { transition: color .14s, border-color .14s; }
      .sx-tab:hover { color: #1c7922 !important; }
      .sx-kanban { transition: transform .16s cubic-bezier(.2,.7,.3,1), box-shadow .16s, border-color .16s; }
      .sx-kanban:hover { transform: translateY(-2px); box-shadow: 0 2px 6px rgba(11,47,13,0.08), 0 10px 24px -8px rgba(11,47,13,0.18); border-color: rgba(28,121,34,0.35) !important; }

      /* ---- responsive foundation (container queries) ---- */
      .sx-appframe { container-type: inline-size; container-name: sxapp; }
      .sx-hamburger { display: none !important; }
      .sx-tablewrap { overflow-x: auto; }
      .sx-tablewrap table { min-width: 720px; }
      @container sxapp (max-width: 1080px) {
        .sx-grid4 { grid-template-columns: repeat(2, 1fr) !important; }
        .sx-grid3 { grid-template-columns: repeat(2, 1fr) !important; }
        .sx-search { width: 200px !important; }
      }
      @container sxapp (max-width: 860px) {
        .sx-sidebar { display: none !important; }
        .sx-hamburger { display: inline-flex !important; }
        .sx-topbar { padding: 0 16px !important; }
        .sx-main { padding: 16px !important; }
        .sx-cols { grid-template-columns: 1fr !important; }
        .sx-grid3 { grid-template-columns: 1fr !important; }
        .sx-search { display: none !important; }
        .sx-userchip-meta { display: none !important; }
        .sx-tablewrap th:first-child, .sx-tablewrap td:first-child { position: sticky; left: 0; background: #fff; z-index: 2; box-shadow: 2px 0 4px rgba(11,47,13,0.06); }
      }
      @container sxapp (max-width: 560px) {
        .sx-grid4, .sx-grid2 { grid-template-columns: 1fr !important; }
        .sx-pagehead { flex-direction: column !important; }
      }
    `;
    document.head.appendChild(s);
  }
})();

const T = {
  green: '#1c7922',
  greenStrong: '#155f1b',
  greenDeep: '#14471a',
  greenForest: '#0b2f0d',
  greenFlash: '#2dc438',
  greenSoft: '#d6f5da',
  greenTint: '#f3fcf4',
  copper: '#9a3412',
  copperHover: '#c2410c',
  copperDeep: '#7c2d12',
  copperSoft: '#fed7aa',
  ink: '#1c1b1c',
  ink2: '#374151',
  ink3: '#666666',
  ink4: '#6b7280',
  line: '#e5e7eb',
  lineStrong: '#cccccc',
  page: '#f3f4f6',
  muted: '#f9fafb',
  surface: '#ffffff',
  success: '#16a34a',
  successStrong: '#14532d',
  successSoft: '#dcfce7',
  warning: '#d97706',
  warningStrong: '#7c2d0e',
  warningSoft: '#fef3c7',
  error: '#dc2626',
  errorStrong: '#991b1b',
  errorSoft: '#fee2e2',
  info: '#2563eb',
  infoStrong: '#1e3a8a',
  infoSoft: '#dbeafe',
  rolePlatform: '#7c3aed',
  roleChina: '#4f46e5',
  rolePurpleSoft: '#ede9fe',
  display: '"Manrope", "Averta", system-ui, sans-serif',
  body: '"Kumbh Sans", system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',
  shadowRest: '0 1px 2px rgba(11,47,13,0.04), 0 4px 16px rgba(11,47,13,0.06)',
  shadowHover: '0 2px 6px rgba(11,47,13,0.08), 0 12px 32px rgba(11,47,13,0.10)',
  shadowModal: '0 8px 24px rgba(11,47,13,0.12), 0 28px 64px rgba(11,47,13,0.22)',
};

// ============================================================
// KOLA MARK (Shipx symbol)
// ============================================================
const KolaMark = ({size = 32, color = T.green}) => (
  <svg width={size} height={size} viewBox="0 0 100 100" fill={color}>
    <g transform="rotate(0 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
    <g transform="rotate(120 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
    <g transform="rotate(240 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
  </svg>
);

const ShipxWordmark = ({size = 22, color = '#fff', xColor = T.copper}) => (
  <span style={{fontFamily: T.display, fontWeight: 800, fontSize: size, letterSpacing: '-0.022em', color, lineHeight: 1}}>
    ship<span style={{color: xColor}}>x</span>
  </span>
);

// ============================================================
// ICON — single-component library, line icons
// ============================================================
const Icon = ({name, size = 16, color = 'currentColor', stroke = 2, fill = 'none'}) => {
  const props = {width: size, height: size, viewBox: '0 0 24 24', fill, stroke: color, strokeWidth: stroke, strokeLinecap: 'round', strokeLinejoin: 'round'};
  const P = {
    // nav
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    building: <><path d="M3 21V7l9-4 9 4v14M9 9h.01M15 9h.01M9 13h.01M15 13h.01M9 17h.01M15 17h.01"/></>,
    users: <><circle cx="9" cy="8" r="4"/><path d="M3 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M17 11a4 4 0 1 0 0-8M22 21v-2a4 4 0 0 0-3-3.87"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    settings: <><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8L4.2 7a2 2 0 0 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5h0a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8h0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/><circle cx="12" cy="12" r="3"/></>,
    log: <><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
    home: <><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2h-4v-7H10v7H6a2 2 0 0 1-2-2z"/></>,
    container: <><rect x="3" y="6" width="18" height="13" rx="1"/><path d="M7 6v13M11 6v13M15 6v13M19 6v13"/></>,
    package: <><path d="M21 16V8a2 2 0 0 0-1-1.73L13 2.27a2 2 0 0 0-2 0L4 6.27A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.27 7L12 12l8.73-5M12 22V12"/></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></>,
    truck: <><rect x="1" y="6" width="14" height="11" rx="1"/><path d="M15 9h4l3 4v4h-7M5.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/></>,
    coin: <><circle cx="12" cy="12" r="9"/><path d="M12 6v12M9 9.5a2.5 2.5 0 0 1 5 0M9 14.5a2.5 2.5 0 0 0 5 0"/></>,
    card: <><rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/></>,
    bell: <><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10 21a2 2 0 0 0 4 0"/></>,
    menu: <><path d="M3 6h18M3 12h18M3 18h18"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    minus: <><path d="M5 12h14"/></>,
    chevdown: <polyline points="6 9 12 15 18 9"/>,
    chevup: <polyline points="18 15 12 9 6 15"/>,
    chevleft: <polyline points="15 18 9 12 15 6"/>,
    chevright: <polyline points="9 18 15 12 9 6"/>,
    arrowup: <><path d="M12 19V5M5 12l7-7 7 7"/></>,
    arrowdown: <><path d="M12 5v14M5 12l7 7 7-7"/></>,
    arrowleft: <><path d="M19 12H5M12 19l-7-7 7-7"/></>,
    arrowright: <><path d="M5 12h14M12 5l7 7-7 7"/></>,
    download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></>,
    upload: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></>,
    check: <polyline points="20 6 9 17 4 12"/>,
    x: <><path d="M18 6L6 18M6 6l12 12"/></>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></>,
    warn: <><path d="M12 2L2 22h20L12 2zM12 9v5M12 18h.01"/></>,
    dot3: <><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></>,
    logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 9h18M8 3v4M16 3v4"/></>,
    filter: <><path d="M3 6h18M7 12h10M11 18h2"/></>,
    edit: <><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"/></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></>,
    mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></>,
    phone: <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>,
    pause: <><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></>,
    refresh: <><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5"/></>,
    map: <><polygon points="1 6 8 3 16 6 23 3 23 18 16 21 8 18 1 21 1 6"/><line x1="8" y1="3" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="21"/></>,
    chart: <><path d="M3 3v18h18M7 15l4-4 4 4 5-7"/></>,
    pie: <><path d="M21 12a9 9 0 1 1-9-9v9z"/><path d="M21 12a9 9 0 0 0-9-9"/></>,
    ship: <><path d="M3 16l1-2h16l1 2M5 16v2c0 1 1 2 2 2h10c1 0 2-1 2-2v-2M12 4v8M8 8h8M9 12V8M15 12V8"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    qr: <><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3M17 17v3h3M20 14h-3"/></>,
    flag: <><path d="M4 21V4M4 4h13l-2 4 2 4H4"/></>,
    shield: <path d="M12 2l9 4v6c0 5-3.5 9-9 10-5.5-1-9-5-9-10V6l9-4z"/>,
    star: <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9 12 2"/>,
    suspend: <><circle cx="12" cy="12" r="9"/><path d="M9 9v6M15 9v6"/></>,
  };
  return <svg {...props} style={{flexShrink: 0, display: 'block'}}>{P[name]}</svg>;
};

// ============================================================
// BUTTON
// ============================================================
const Button = ({variant = 'primary', size = 'md', icon, trailing, full, children, disabled, onClick}) => {
  const heights = {sm: 30, md: 38, lg: 44};
  const paddings = {sm: '0 12px', md: '0 16px', lg: '0 20px'};
  const fontSize = {sm: 13, md: 14, lg: 15};
  const styles = {
    primary: {bg: 'linear-gradient(180deg, #229329 0%, #1c7922 100%)', color: '#fff', border: 'none', shadow: '0 1px 2px rgba(11,47,13,0.3), inset 0 1px 0 rgba(255,255,255,0.14)'},
    accent: {bg: 'linear-gradient(180deg, #b13e15 0%, #9a3412 100%)', color: '#fff', border: 'none', shadow: '0 1px 2px rgba(124,45,18,0.3), inset 0 1px 0 rgba(255,255,255,0.14)'},
    secondary: {bg: '#fff', color: T.ink, border: `1px solid ${T.lineStrong}`, shadow: '0 1px 2px rgba(11,47,13,0.05)'},
    ghost: {bg: 'transparent', color: T.green, border: 'none'},
    danger: {bg: 'linear-gradient(180deg, #e33434 0%, #dc2626 100%)', color: '#fff', border: 'none', shadow: '0 1px 2px rgba(153,27,27,0.3), inset 0 1px 0 rgba(255,255,255,0.14)'},
    'danger-outline': {bg: '#fff', color: T.error, border: `1px solid ${T.error}`},
    success: {bg: 'linear-gradient(180deg, #1cb254 0%, #16a34a 100%)', color: '#fff', border: 'none', shadow: '0 1px 2px rgba(20,83,45,0.3), inset 0 1px 0 rgba(255,255,255,0.14)'},
  }[variant];
  return (
    <button onClick={onClick} disabled={disabled} className="sx-btn" style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'center',
      width: full ? '100%' : 'auto',
      height: heights[size], padding: paddings[size],
      background: styles.bg, color: styles.color, border: styles.border,
      boxShadow: styles.shadow || 'none',
      borderRadius: 10, fontFamily: T.body, fontWeight: 600, fontSize: fontSize[size],
      cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1,
      whiteSpace: 'nowrap', transition: 'all .15s',
    }}>
      {icon && <Icon name={icon} size={size === 'sm' ? 13 : 15} stroke={2.2} />}
      {children}
      {trailing && <Icon name={trailing} size={size === 'sm' ? 13 : 15} stroke={2.2} />}
    </button>
  );
};

// ============================================================
// BADGE
// ============================================================
const Badge = ({variant = 'neutral', children, dot = true, size = 'md'}) => {
  const palette = {
    success: {bg: T.successSoft, color: T.successStrong, dot: T.success},
    warning: {bg: T.warningSoft, color: T.warningStrong, dot: T.warning},
    error: {bg: T.errorSoft, color: T.errorStrong, dot: T.error},
    info: {bg: T.infoSoft, color: T.infoStrong, dot: T.info},
    accent: {bg: T.copperSoft, color: T.copperDeep, dot: T.copper},
    purple: {bg: T.rolePurpleSoft, color: T.rolePlatform, dot: T.rolePlatform},
    neutral: {bg: T.line, color: T.ink3, dot: T.ink4},
    primary: {bg: T.greenSoft, color: T.greenDeep, dot: T.green},
  }[variant];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: size === 'sm' ? 4 : 6,
      background: palette.bg, color: palette.color,
      padding: size === 'sm' ? '2px 8px' : '4px 10px',
      borderRadius: 9999,
      fontFamily: T.body, fontWeight: 600,
      fontSize: size === 'sm' ? 10 : 11, letterSpacing: '0.06em', textTransform: 'uppercase',
      whiteSpace: 'nowrap',
    }}>
      {dot && <span style={{width: 6, height: 6, borderRadius: '50%', background: palette.dot, flexShrink: 0}} />}
      {children}
    </span>
  );
};

// ============================================================
// CARD
// ============================================================
const Card = ({children, padding = 24, radius = 14, style = {}}) => (
  <div style={{
    background: '#fff',
    border: `1px solid ${T.line}`,
    borderRadius: radius,
    padding,
    boxShadow: T.shadowRest,
    ...style,
  }}>{children}</div>
);

const StatCard = ({label, value, suffix, trend, trendDir, sublabel, accent}) => (
  <Card padding={20} radius={16}>
    <div style={{display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14}}>
      {accent && (
        <div style={{
          width: 28, height: 28, borderRadius: 9,
          background: 'linear-gradient(135deg, #d6f5da 0%, #f3fcf4 100%)', color: T.green,
          boxShadow: 'inset 0 0 0 1px rgba(28,121,34,0.14)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>{accent}</div>
      )}
      <div style={{
        fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
        fontWeight: 700, color: T.ink3, lineHeight: 1.2,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0,
      }}>{label}</div>
    </div>
    <div style={{
      fontFamily: T.display, fontWeight: 700, fontSize: 30, letterSpacing: '-0.02em',
      color: T.ink, marginBottom: 8, lineHeight: 1, whiteSpace: 'nowrap',
    }}>
      {value}{suffix && <span style={{fontSize: 15, color: T.ink3, marginLeft: 4, fontWeight: 600}}>{suffix}</span>}
    </div>
    {(trend || sublabel) && (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
        whiteSpace: 'nowrap', overflow: 'hidden',
      }}>
        {trend && (
          <span style={{
            color: trendDir === 'down' ? T.error : T.success,
            display: 'inline-flex', alignItems: 'center', gap: 3, fontWeight: 700, flexShrink: 0,
          }}>
            <Icon name={trendDir === 'down' ? 'arrowdown' : 'arrowup'} size={11} stroke={2.8} />
            {trend}
          </span>
        )}
        {sublabel && (
          <span style={{
            color: T.ink4, fontWeight: 500, minWidth: 0,
            overflow: 'hidden', textOverflow: 'ellipsis',
          }}>{sublabel}</span>
        )}
      </div>
    )}
  </Card>
);

// ============================================================
// FIELD / INPUT
// ============================================================
const Field = ({label, type = 'text', icon, trailing, placeholder, value, error, helper, optional, required, focused, disabled, multiline, prefix, suffix, children}) => {
  const borderColor = error ? T.error : focused ? T.green : T.lineStrong;
  return (
    <div style={{marginBottom: 16}}>
      {label && (
        <label style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', fontFamily: T.body, fontWeight: 500, fontSize: 13, color: T.ink2, marginBottom: 6}}>
          <span>{label}{required && <span style={{color: T.error, marginLeft: 2}}>*</span>}</span>
          {optional && <span style={{fontWeight: 400, color: T.ink4, fontSize: 12}}>Optional</span>}
        </label>
      )}
      {children ? children : (
        <div style={{
          position: 'relative', display: 'flex', alignItems: multiline ? 'flex-start' : 'center',
          minHeight: multiline ? 88 : 40,
          background: disabled ? T.page : '#fff',
          border: `${focused || error ? 2 : 1}px solid ${borderColor}`,
          borderRadius: 8,
          padding: multiline ? '10px 14px' : '0 14px',
          boxShadow: focused ? `0 0 0 3px rgba(45,196,56,0.35)` : 'none',
          gap: 8,
        }}>
          {icon && <Icon name={icon} size={16} color={T.ink4} />}
          {prefix && <span style={{color: T.ink4, fontFamily: T.mono, fontSize: 13}}>{prefix}</span>}
          {multiline ? (
            <textarea defaultValue={value} placeholder={placeholder} style={{
              flex: 1, border: 0, outline: 0, background: 'transparent', resize: 'vertical',
              fontFamily: T.body, fontSize: 14, color: T.ink, padding: 0, minHeight: 64,
            }} />
          ) : (
            <input type={type} defaultValue={value} placeholder={placeholder} style={{
              flex: 1, border: 0, outline: 0, background: 'transparent',
              fontFamily: T.body, fontSize: 14, color: T.ink, height: '100%', minWidth: 0,
            }} />
          )}
          {suffix && <span style={{color: T.ink4, fontSize: 13}}>{suffix}</span>}
          {trailing && <Icon name={trailing} size={16} color={T.ink4} />}
        </div>
      )}
      {error && (
        <div style={{display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12, color: T.error, fontWeight: 500}}>
          <Icon name="alert" size={12} color={T.error} />{error}
        </div>
      )}
      {helper && !error && <div style={{marginTop: 6, fontSize: 12, color: T.ink4}}>{helper}</div>}
    </div>
  );
};

// ============================================================
// TABLE PRIMITIVES (used everywhere)
// ============================================================
const Table = ({columns, rows, dense, selectable, sortable, emptyState}) => (
  <div className="sx-tablewrap" style={{width: '100%', overflowX: 'auto', borderRadius: 12, border: `1px solid ${T.line}`, boxShadow: '0 1px 2px rgba(11,47,13,0.04)'}}>
    <table style={{width: '100%', borderCollapse: 'collapse', fontFamily: T.body}}>
      <thead>
        <tr>
          {selectable && (
            <th style={{width: 36, padding: '12px 0 12px 16px', background: T.muted, borderBottom: `1px solid ${T.line}`}}>
              <Check />
            </th>
          )}
          {columns.map((c, i) => (
            <th key={i} style={{
              textAlign: c.align || 'left', padding: '12px 16px',
              fontSize: 11, fontWeight: 600, color: T.ink3,
              letterSpacing: '0.08em', textTransform: 'uppercase',
              background: T.muted, borderBottom: `1px solid ${T.line}`,
              width: c.width,
            }}>
              <div style={{display: 'inline-flex', alignItems: 'center', gap: 4, justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start'}}>
                {c.title}
                {sortable && c.sortable && <Icon name="chevdown" size={11} color={c.active ? T.green : T.ink4} />}
              </div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={columns.length + (selectable ? 1 : 0)} style={{padding: 60, textAlign: 'center'}}>{emptyState}</td></tr>
        ) : rows.map((row, i) => (
          <tr key={i} className={`sx-row${row.selected || row.suspended ? '' : ' sx-plain'}`} style={{background: row.selected ? T.greenSoft : row.suspended ? '#fef5f5' : '#fff', borderLeft: row.selected ? `2px solid ${T.green}` : 'none'}}>
            {selectable && (
              <td style={{padding: `${dense ? 10 : 14}px 0 ${dense ? 10 : 14}px 16px`, borderBottom: `1px solid ${T.line}`, verticalAlign: 'middle'}}>
                <Check checked={row.selected} />
              </td>
            )}
            {row.cells.map((cell, j) => (
              <td key={j} style={{
                padding: `${dense ? 10 : 14}px 16px`,
                borderBottom: `1px solid ${T.line}`,
                fontSize: 13, color: T.ink2,
                textAlign: columns[j].align || 'left',
                verticalAlign: 'middle',
              }}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Check = ({checked = false, partial}) => (
  <div style={{
    width: 16, height: 16, borderRadius: 4,
    border: `${checked || partial ? 0 : 1.5}px solid ${T.lineStrong}`,
    background: (checked || partial) ? T.green : '#fff',
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', verticalAlign: 'middle',
  }}>
    {checked && <Icon name="check" size={10} color="#fff" stroke={3} />}
    {partial && <Icon name="minus" size={10} color="#fff" stroke={3} />}
  </div>
);

const Mono = ({children, color}) => (
  <span style={{fontFamily: T.mono, fontSize: 12.5, color: color || T.ink}}>{children}</span>
);

const Avatar = ({size = 32, name = '', src, color, role}) => {
  const initials = name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
  const palette = role === 'platform' ? T.rolePlatform : role === 'china' ? T.roleChina : role === 'nigeria' ? T.copper : role === 'warehouse' ? T.warning : color || T.green;
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      background: palette + '22', color: palette,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: T.body, fontWeight: 700, fontSize: size * 0.4,
      flexShrink: 0,
    }}>{initials || '?'}</div>
  );
};

// ============================================================
// BANNER / ALERT
// ============================================================
const Banner = ({variant = 'info', title, children, icon, action, dismissible}) => {
  const palette = {
    info: {bg: T.infoSoft, fg: T.infoStrong, accent: T.info, ic: 'info'},
    success: {bg: T.successSoft, fg: T.successStrong, accent: T.success, ic: 'check'},
    warning: {bg: T.warningSoft, fg: T.warningStrong, accent: T.warning, ic: 'warn'},
    error: {bg: T.errorSoft, fg: T.errorStrong, accent: T.error, ic: 'alert'},
  }[variant];
  return (
    <div style={{
      display: 'flex', gap: 12, alignItems: 'flex-start',
      background: palette.bg, color: palette.fg,
      borderLeft: `4px solid ${palette.accent}`,
      border: `1px solid ${palette.accent}33`,
      borderRadius: 8, padding: '14px 16px',
      fontSize: 13, lineHeight: 1.5,
    }}>
      <Icon name={icon || palette.ic} size={18} color={palette.accent} />
      <div style={{flex: 1}}>
        {title && <div style={{fontWeight: 700, marginBottom: 2}}>{title}</div>}
        <div>{children}</div>
      </div>
      {action}
      {dismissible && <Icon name="x" size={16} color={palette.fg} />}
    </div>
  );
};

// ============================================================
// PILL / CHIP (filter chips)
// ============================================================
const Chip = ({active, children, onClick, count, dismissible}) => (
  <button onClick={onClick} className="sx-chip" style={{
    display: 'inline-flex', alignItems: 'center', gap: 6,
    height: 30, padding: '0 12px',
    background: active ? T.greenSoft : '#fff',
    color: active ? T.greenDeep : T.ink2,
    border: `1px solid ${active ? T.green + '55' : T.lineStrong}`,
    borderRadius: 9999, cursor: 'pointer',
    fontFamily: T.body, fontWeight: active ? 600 : 500, fontSize: 13,
    whiteSpace: 'nowrap',
  }}>
    {children}
    {count != null && <span style={{
      background: active ? T.green : T.line, color: active ? '#fff' : T.ink3,
      borderRadius: 999, padding: '0 6px', fontSize: 11, fontWeight: 700, minWidth: 16, textAlign: 'center',
    }}>{count}</span>}
    {dismissible && <Icon name="x" size={11} color={active ? T.greenDeep : T.ink4} stroke={2.5} />}
  </button>
);

Object.assign(window, {
  T, KolaMark, ShipxWordmark, Icon, Button, Badge, Card, StatCard,
  Field, Table, Check, Mono, Avatar, Banner, Chip,
});
