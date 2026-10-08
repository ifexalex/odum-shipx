// ============================================================
// Shipx — Authentication Screens (Section 1)
// Split-panel layout: brand panel (forest dark) + form panel (white)
// ============================================================

const AUTH_TOKENS = {
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
  successSoft: '#dcfce7',
  warning: '#d97706',
  warningSoft: '#fef3c7',
  error: '#dc2626',
  errorSoft: '#fee2e2',
  errorStrong: '#991b1b',
  display: '"Manrope", "Averta", system-ui, sans-serif',
  body: '"Kumbh Sans", system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',
};

// ============================================================
// MARK + LOCKUP
// ============================================================
const KolaMark = ({size = 44, color = '#fff'}) => (
  <svg width={size} height={size} viewBox="0 0 100 100" fill={color}>
    <g transform="rotate(0 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
    <g transform="rotate(120 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
    <g transform="rotate(240 50 50)"><rect x="36" y="6" width="28" height="48" rx="14" /></g>
  </svg>
);

const ShipxLockup = ({color = '#fff', xColor = AUTH_TOKENS.copper, markColor, size = 'md', showBy = false}) => {
  const wmSize = size === 'lg' ? 40 : size === 'sm' ? 22 : 30;
  const markSize = size === 'lg' ? 44 : size === 'sm' ? 26 : 34;
  const mc = markColor || (color === '#fff' ? AUTH_TOKENS.greenFlash : color);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
      <KolaMark size={markSize} color={mc} />
      <div style={{display: 'flex', alignItems: 'baseline', gap: 8}}>
        <span style={{fontFamily: AUTH_TOKENS.display, fontWeight: 800, fontSize: wmSize, letterSpacing: '-0.022em', color, lineHeight: 1}}>
          ship<span style={{color: xColor}}>x</span>
        </span>
        {showBy && (
          <span style={{fontFamily: AUTH_TOKENS.body, fontSize: 11, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.16em', textTransform: 'uppercase', fontWeight: 600}}>
            Logistics platform
          </span>
        )}
      </div>
    </div>
  );
};

// ============================================================
// BRAND PANEL (left side, 40%)
// ============================================================
const BrandIllustration = () => (
  <div style={{position: 'relative', width: '100%', maxWidth: 420, aspectRatio: '1 / 1', margin: '0 auto'}}>
    {/* Faint large kola mark anchored center */}
    <div style={{position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.18}}>
      <KolaMark size={340} color={AUTH_TOKENS.greenFlash} />
    </div>
    {/* Shipping route arc — Guangzhou → Lagos */}
    <svg viewBox="0 0 400 400" style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}>
      <defs>
        <linearGradient id="routeGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor={AUTH_TOKENS.greenFlash} stopOpacity="0.2" />
          <stop offset="0.5" stopColor={AUTH_TOKENS.greenFlash} stopOpacity="1" />
          <stop offset="1" stopColor={AUTH_TOKENS.copperHover} stopOpacity="0.9" />
        </linearGradient>
      </defs>
      {/* Origin pin — Guangzhou */}
      <circle cx="80" cy="130" r="10" fill={AUTH_TOKENS.greenFlash} />
      <circle cx="80" cy="130" r="22" fill={AUTH_TOKENS.greenFlash} fillOpacity="0.18" />
      {/* Destination pin — Lagos */}
      <circle cx="320" cy="280" r="10" fill={AUTH_TOKENS.copperHover} />
      <circle cx="320" cy="280" r="22" fill={AUTH_TOKENS.copperHover} fillOpacity="0.22" />
      {/* Arc route */}
      <path d="M80 130 Q200 60 320 280" fill="none" stroke="url(#routeGrad)" strokeWidth="3" strokeDasharray="6 6" />
      {/* Container in transit on arc */}
      <g transform="translate(195 145) rotate(28)">
        <rect x="-22" y="-13" width="44" height="26" rx="6" fill={AUTH_TOKENS.greenFlash} />
        <rect x="-18" y="-9" width="36" height="2" fill={AUTH_TOKENS.greenForest} opacity="0.35" />
        <rect x="-18" y="-2" width="36" height="2" fill={AUTH_TOKENS.greenForest} opacity="0.35" />
        <rect x="-18" y="5" width="36" height="2" fill={AUTH_TOKENS.greenForest} opacity="0.35" />
      </g>
      {/* Origin label */}
      <text x="80" y="105" textAnchor="middle" style={{fontFamily: AUTH_TOKENS.mono, fontSize: 10, fill: AUTH_TOKENS.greenFlash, letterSpacing: '0.1em'}}>CN · GZG</text>
      <text x="320" y="312" textAnchor="middle" style={{fontFamily: AUTH_TOKENS.mono, fontSize: 10, fill: AUTH_TOKENS.copperHover, letterSpacing: '0.1em'}}>NG · LOS</text>
    </svg>
  </div>
);

const BrandPanel = () => {
  const panel = {
    width: '40%',
    minWidth: 360,
    background: `radial-gradient(circle at 20% 100%, ${AUTH_TOKENS.greenDeep} 0%, ${AUTH_TOKENS.greenForest} 60%)`,
    color: '#fff',
    padding: '40px 48px',
    display: 'flex',
    flexDirection: 'column',
    position: 'relative',
    overflow: 'hidden',
    boxShadow: 'inset -1px 0 0 rgba(255,255,255,0.06)',
  };
  return (
    <div className="sx-brandpanel" style={panel}>
      {/* subtle radial glow */}
      <div style={{position: 'absolute', top: -120, right: -120, width: 360, height: 360, borderRadius: '50%', background: `radial-gradient(circle, ${AUTH_TOKENS.greenFlash}22, transparent 60%)`, pointerEvents: 'none', animation: 'authGlow 9s ease-in-out infinite alternate'}} />
      {/* Logo top */}
      <ShipxLockup size="sm" showBy />
      {/* Tagline center */}
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', maxWidth: 460, position: 'relative', zIndex: 1}}>
        <BrandIllustration />
        <h1 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 800, fontSize: 38, lineHeight: 1.08, letterSpacing: '-0.025em', margin: '32px 0 14px', color: '#fff'}}>
          Cargo logistics,<br />
          <span style={{color: AUTH_TOKENS.greenFlash}}>engineered to move.</span>
        </h1>
        <p style={{fontFamily: AUTH_TOKENS.body, fontSize: 15, lineHeight: 1.55, color: 'rgba(255,255,255,0.72)', margin: 0, maxWidth: 380}}>
          Guangzhou to Lagos. End-to-end. Unstoppable. Built for the operators, customers, and developers who lead every shipment.
        </p>
      </div>
      {/* Footer */}
      <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 24, borderTop: '1px solid rgba(255,255,255,0.1)', position: 'relative', zIndex: 1}}>
        <div style={{fontFamily: AUTH_TOKENS.body, fontSize: 11, color: 'rgba(255,255,255,0.4)', letterSpacing: '0.14em', textTransform: 'uppercase', fontWeight: 600}}>
          © 2026 Shipx Platform
        </div>
        <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
          <div style={{width: 6, height: 6, borderRadius: '50%', background: AUTH_TOKENS.greenFlash, boxShadow: `0 0 8px ${AUTH_TOKENS.greenFlash}`}} />
          <span style={{fontSize: 11, color: 'rgba(255,255,255,0.5)', letterSpacing: '0.1em', fontWeight: 600}}>All systems operational</span>
        </div>
      </div>
    </div>
  );
};

// ============================================================
// ATOM COMPONENTS
// ============================================================
const Icon = ({name, size = 16, color = 'currentColor', stroke = 2}) => {
  const props = {width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: color, strokeWidth: stroke, strokeLinecap: 'round', strokeLinejoin: 'round'};
  const paths = {
    mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></>,
    lock: <><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></>,
    eyeoff: <><path d="M1 1l22 22" /><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" /><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c6.5 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" /><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3.5 7 10 7a9.74 9.74 0 0 0 5.39-1.61" /></>,
    user: <><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></>,
    phone: <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />,
    check: <polyline points="20 6 9 17 4 12" />,
    alert: <><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" /></>,
    arrowleft: <><path d="M19 12H5M12 19l-7-7 7-7" /></>,
    arrowright: <><path d="M5 12h14M12 5l7 7-7 7" /></>,
    x: <><path d="M18 6L6 18M6 6l12 12" /></>,
    whatsapp: <><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" /></>,
  };
  return <svg {...props} style={{flexShrink: 0}}>{paths[name]}</svg>;
};

const Field = ({label, type = 'text', icon, trailing, placeholder, value = '', error, helper, state = 'default', optional}) => {
  const isError = state === 'error' || !!error;
  const isFocused = state === 'focused';
  const isDisabled = state === 'disabled';
  const borderColor = isError ? AUTH_TOKENS.error : isFocused ? AUTH_TOKENS.green : AUTH_TOKENS.lineStrong;
  return (
    <div style={{marginBottom: 16}}>
      <label style={{display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', fontFamily: AUTH_TOKENS.body, fontWeight: 500, fontSize: 13, color: AUTH_TOKENS.ink2, marginBottom: 6}}>
        <span>{label}</span>
        {optional && <span style={{fontWeight: 400, color: AUTH_TOKENS.ink4, fontSize: 12}}>Optional</span>}
      </label>
      <div style={{
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        height: 44,
        background: isDisabled ? AUTH_TOKENS.page : '#fff',
        border: `${isFocused || isError ? 2 : 1}px solid ${borderColor}`,
        borderRadius: 10,
        padding: '0 14px',
        boxShadow: isFocused ? `0 0 0 3px rgba(45,196,56,0.30), 0 1px 2px rgba(11,47,13,0.05)` : 'inset 0 1px 2px rgba(11,47,13,0.03)',
        transition: 'all .15s',
      }}>
        {icon && <Icon name={icon} size={16} color={AUTH_TOKENS.ink4} />}
        <input
          type={type}
          defaultValue={value}
          placeholder={placeholder}
          style={{
            flex: 1,
            border: 0,
            outline: 0,
            background: 'transparent',
            padding: `0 ${icon ? 10 : 0}px 0 ${icon ? 10 : 0}px`,
            fontFamily: AUTH_TOKENS.body,
            fontSize: 14,
            color: AUTH_TOKENS.ink,
            height: '100%',
          }}
        />
        {trailing && <Icon name={trailing} size={16} color={AUTH_TOKENS.ink4} />}
      </div>
      {error && (
        <div style={{display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 12, color: AUTH_TOKENS.error, fontWeight: 500}}>
          <Icon name="alert" size={12} color={AUTH_TOKENS.error} />
          {error}
        </div>
      )}
      {helper && !error && (
        <div style={{marginTop: 6, fontSize: 12, color: AUTH_TOKENS.ink4}}>{helper}</div>
      )}
    </div>
  );
};

const Button = ({variant = 'accent', size = 'lg', loading, disabled, children, full = true}) => {
  const heights = {sm: 32, md: 38, lg: 48};
  const bg = variant === 'accent' ? 'linear-gradient(180deg, #b13e15 0%, #9a3412 100%)' : variant === 'primary' ? 'linear-gradient(180deg, #229329 0%, #1c7922 100%)' : variant === 'ghost' ? 'transparent' : '#fff';
  const color = variant === 'ghost' || variant === 'secondary' ? AUTH_TOKENS.ink : '#fff';
  const border = variant === 'secondary' ? `1px solid ${AUTH_TOKENS.lineStrong}` : 'none';
  const shadow = variant === 'accent' ? '0 1px 2px rgba(124,45,18,0.3), inset 0 1px 0 rgba(255,255,255,0.14)' : variant === 'primary' ? '0 1px 2px rgba(11,47,13,0.3), inset 0 1px 0 rgba(255,255,255,0.14)' : variant === 'secondary' ? '0 1px 2px rgba(11,47,13,0.05)' : 'none';
  return (
    <button className="sx-btn" style={{
      width: full ? '100%' : 'auto',
      height: heights[size],
      background: disabled ? '#a8a39c' : bg,
      color,
      border,
      borderRadius: 10,
      boxShadow: disabled ? 'none' : shadow,
      fontFamily: AUTH_TOKENS.body,
      fontWeight: 600,
      fontSize: size === 'sm' ? 13 : 14,
      cursor: disabled || loading ? 'not-allowed' : 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 8,
      opacity: disabled ? 0.7 : 1,
      transition: 'all .15s',
    }}>
      {loading ? (
        <>
          <div style={{width: 16, height: 16, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%', animation: 'spinx 0.8s linear infinite'}} />
          Signing in...
        </>
      ) : children}
    </button>
  );
};

const Checkbox = ({label, checked = false}) => (
  <label style={{display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: AUTH_TOKENS.ink2, fontWeight: 500}}>
    <div style={{
      width: 18, height: 18, borderRadius: 4,
      border: `${checked ? 0 : 1.5}px solid ${checked ? 'transparent' : AUTH_TOKENS.lineStrong}`,
      background: checked ? AUTH_TOKENS.green : '#fff',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {checked && <Icon name="check" size={11} color="#fff" stroke={3} />}
    </div>
    {label}
  </label>
);

const Banner = ({variant = 'error', title, children, icon}) => {
  const palette = {
    error: {bg: AUTH_TOKENS.errorSoft, color: AUTH_TOKENS.errorStrong, accent: AUTH_TOKENS.error, ic: 'alert'},
    info: {bg: '#dbeafe', color: '#1e3a8a', accent: '#2563eb', ic: 'info'},
    success: {bg: AUTH_TOKENS.successSoft, color: '#14532d', accent: AUTH_TOKENS.success, ic: 'check'},
    warning: {bg: AUTH_TOKENS.warningSoft, color: '#7c2d0e', accent: AUTH_TOKENS.warning, ic: 'alert'},
  }[variant];
  return (
    <div style={{
      display: 'flex', gap: 12, alignItems: 'flex-start',
      background: palette.bg, color: palette.color,
      border: `1px solid ${palette.accent}33`,
      borderLeft: `4px solid ${palette.accent}`,
      borderRadius: 10, padding: '12px 14px', marginBottom: 20, fontSize: 13, lineHeight: 1.45,
      boxShadow: '0 1px 2px rgba(11,47,13,0.04)',
    }}>
      <Icon name={icon || palette.ic} size={16} color={palette.accent} />
      <div style={{flex: 1}}>
        {title && <div style={{fontWeight: 700, marginBottom: 2}}>{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  );
};

const Divider = ({children}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 12, margin: '20px 0', color: AUTH_TOKENS.ink4, fontSize: 12, fontWeight: 500}}>
    <div style={{flex: 1, height: 1, background: AUTH_TOKENS.line}} />
    {children && <span style={{textTransform: 'uppercase', letterSpacing: '0.1em'}}>{children}</span>}
    <div style={{flex: 1, height: 1, background: AUTH_TOKENS.line}} />
  </div>
);

const PasswordStrength = ({level = 0}) => {
  // 0=empty, 1=weak, 2=medium, 3=strong, 4=excellent
  const labels = ['', 'Weak', 'Fair', 'Strong', 'Excellent'];
  const colors = ['', AUTH_TOKENS.error, AUTH_TOKENS.warning, AUTH_TOKENS.success, AUTH_TOKENS.success];
  return (
    <div style={{marginTop: 8}}>
      <div style={{display: 'flex', gap: 4}}>
        {[1, 2, 3, 4].map(i => (
          <div key={i} style={{flex: 1, height: 4, borderRadius: 2, background: i <= level ? colors[level] : AUTH_TOKENS.line}} />
        ))}
      </div>
      {level > 0 && (
        <div style={{display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 11, color: colors[level], fontWeight: 600}}>
          <span>Password strength: {labels[level]}</span>
        </div>
      )}
    </div>
  );
};

// ============================================================
// SHELL — wraps brand + form panels
// ============================================================
const AuthShell = ({children, formWidth = 440, padding = 56}) => (
  <div className="sx-authframe" style={{display: 'flex', height: '100%', minHeight: 720, background: '#fff', fontFamily: AUTH_TOKENS.body, color: AUTH_TOKENS.ink}}>
    <BrandPanel />
    <div style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: `${padding}px 32px`, overflow: 'auto'}}>
      <div style={{width: '100%', maxWidth: formWidth}}>
        {children}
      </div>
    </div>
    <style>{`
      @keyframes spinx { to { transform: rotate(360deg); } }
      @keyframes authGlow { from { transform: translateY(0) scale(1); opacity: .8; } to { transform: translateY(30px) scale(1.15); opacity: 1; } }
      .sx-btn { transition: transform .16s cubic-bezier(.2,.7,.3,1), box-shadow .16s, filter .16s; }
      .sx-btn:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); box-shadow: 0 6px 14px rgba(11,47,13,0.18); }
      .sx-btn:active:not(:disabled) { transform: translateY(0); filter: brightness(0.97); }
      .sx-authframe { container-type: inline-size; container-name: sxauth; }
      @container sxauth (max-width: 920px) {
        .sx-brandpanel { display: none !important; }
      }
      @container sxauth (max-width: 560px) {
        .sx-grid2, .sx-cols { grid-template-columns: 1fr !important; }
      }
    `}</style>
  </div>
);

const FormHead = ({title, sub}) => (
  <div style={{marginBottom: 28}}>
    <h2 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 700, fontSize: 28, letterSpacing: '-0.018em', color: AUTH_TOKENS.ink, margin: '0 0 6px'}}>{title}</h2>
    {sub && <p style={{fontSize: 14, color: AUTH_TOKENS.ink3, margin: 0, lineHeight: 1.5}}>{sub}</p>}
  </div>
);

// ============================================================
// 1.1 — LOGIN VARIANTS
// ============================================================
const LoginScreen = ({state = 'default'}) => {
  const filled = state === 'filled' || state === 'loading';
  const errorBanner = {
    'error-invalid': {variant: 'error', title: 'Invalid email or password', body: 'Check your credentials and try again. After 5 failed attempts, your account locks for 15 minutes.'},
    'error-suspended': {variant: 'error', title: 'Account suspended', body: 'Your account has been deactivated. Contact your tenant administrator to restore access.'},
    'error-tenant': {variant: 'error', title: 'Company account suspended', body: 'Your company\'s Shipx subscription is currently suspended. Contact Shipx support at support@shipx.co.'},
  }[state];

  return (
    <AuthShell>
      <FormHead title="Sign in to Shipx" sub="Enter your credentials to access your portal." />
      {errorBanner && <Banner variant={errorBanner.variant} title={errorBanner.title}>{errorBanner.body}</Banner>}
      <Field label="Email address" type="email" icon="mail" placeholder="you@company.com" value={filled ? 'amara@acmelogistics.com' : ''} />
      <Field label="Password" type="password" icon="lock" trailing="eye" placeholder="••••••••" value={filled ? '••••••••••••' : ''} />
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 24px'}}>
        <Checkbox label="Remember me for 30 days" checked={filled} />
        <a style={{color: AUTH_TOKENS.green, fontWeight: 600, fontSize: 13, textDecoration: 'none'}}>Forgot password?</a>
      </div>
      <Button variant="accent" size="lg" loading={state === 'loading'}>Sign In</Button>
      <Divider>or</Divider>
      <p style={{textAlign: 'center', fontSize: 13, color: AUTH_TOKENS.ink3, margin: 0}}>
        New customer? <a style={{color: AUTH_TOKENS.green, fontWeight: 700, textDecoration: 'none'}}>Register here →</a>
      </p>
    </AuthShell>
  );
};

// ============================================================
// 1.2 — CUSTOMER REGISTRATION
// ============================================================
const RegisterScreen = ({state = 'default'}) => {
  if (state === 'success') {
    return (
      <AuthShell>
        <div style={{textAlign: 'center'}}>
          <div style={{width: 84, height: 84, borderRadius: '50%', background: AUTH_TOKENS.successSoft, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px'}}>
            <Icon name="check" size={42} color={AUTH_TOKENS.success} stroke={2.5} />
          </div>
          <h2 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 700, fontSize: 28, color: AUTH_TOKENS.ink, margin: '0 0 8px', letterSpacing: '-0.015em'}}>Account created.</h2>
          <p style={{fontSize: 15, color: AUTH_TOKENS.ink3, margin: '0 0 24px', lineHeight: 1.55}}>
            We sent a verification link to <strong style={{color: AUTH_TOKENS.ink}}>ngozi.okonkwo@gmail.com</strong>.
            Click the link in your email to activate your account and sign in.
          </p>
          <Banner variant="info" title="Didn't receive the email?">
            Check your spam folder, or <a style={{color: '#2563eb', fontWeight: 600}}>resend the verification email</a>. The link expires in 24 hours.
          </Banner>
          <Button variant="primary">Back to sign in</Button>
        </div>
      </AuthShell>
    );
  }

  const validation = state === 'validation';

  return (
    <AuthShell padding={48}>
      <FormHead title="Create your account" sub="Register to track your shipments and manage billing." />
      {validation && <Banner variant="error" title="Please fix the highlighted fields">3 fields need attention.</Banner>}
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <Field label="Full name" placeholder="Ngozi Okonkwo" value="Ngozi Okonkwo" />
        <Field label="Email address" type="email" placeholder="you@example.com" value="ngozi.okonkwo@gmail" error={validation ? 'Please enter a complete email address.' : null} />
      </div>
      <div className="sx-grid2" style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14}}>
        <Field label="Phone number" icon="phone" placeholder="+234..." value="+234 801 234 5678" />
        <Field label="WhatsApp number" icon="whatsapp" placeholder="+234..." value="" optional helper="If different from phone" />
      </div>
      <div style={{marginBottom: 16}}>
        <label style={{display: 'block', fontFamily: AUTH_TOKENS.body, fontWeight: 500, fontSize: 13, color: AUTH_TOKENS.ink2, marginBottom: 8}}>
          Notify me via
        </label>
        <div style={{display: 'flex', gap: 16}}>
          <Checkbox label="SMS" checked={true} />
          <Checkbox label="WhatsApp" checked={true} />
          <Checkbox label="Email" checked={true} />
        </div>
      </div>
      <Field label="Password" type="password" icon="lock" trailing="eye" placeholder="••••••••" value="Logistic2026!" error={validation ? 'Add at least one special character.' : null} />
      {!validation && <PasswordStrength level={3} />}
      <div style={{marginTop: 16}}>
        <Field label="Confirm password" type="password" icon="lock" trailing="eye" placeholder="••••••••" value="Logistic2026!" error={validation ? 'Passwords don\'t match.' : null} />
      </div>
      <div style={{margin: '8px 0 24px', display: 'flex', alignItems: 'flex-start', gap: 8}}>
        <div style={{paddingTop: 2}}>
          <Checkbox label="" checked={!validation} />
        </div>
        <div style={{fontSize: 13, color: AUTH_TOKENS.ink2, lineHeight: 1.5}}>
          I agree to the <a style={{color: AUTH_TOKENS.green, fontWeight: 600, textDecoration: 'none'}}>Terms of Service</a> and <a style={{color: AUTH_TOKENS.green, fontWeight: 600, textDecoration: 'none'}}>Privacy Policy</a>.
        </div>
      </div>
      <Button variant="accent" size="lg">Create account</Button>
      <p style={{textAlign: 'center', fontSize: 13, color: AUTH_TOKENS.ink3, margin: '20px 0 0'}}>
        Already have an account? <a style={{color: AUTH_TOKENS.green, fontWeight: 700, textDecoration: 'none'}}>Sign in →</a>
      </p>
    </AuthShell>
  );
};

// ============================================================
// 1.3 — FORGOT PASSWORD
// ============================================================
const ForgotPasswordScreen = ({state = 'form'}) => {
  if (state === 'sent') {
    return (
      <AuthShell>
        <a style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: AUTH_TOKENS.ink3, fontWeight: 500, fontSize: 13, textDecoration: 'none', marginBottom: 32}}>
          <Icon name="arrowleft" size={14} /> Back to sign in
        </a>
        <div style={{textAlign: 'center'}}>
          <div style={{width: 84, height: 84, borderRadius: '50%', background: AUTH_TOKENS.greenSoft, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px'}}>
            <Icon name="mail" size={38} color={AUTH_TOKENS.green} stroke={2} />
          </div>
          <h2 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 700, fontSize: 28, color: AUTH_TOKENS.ink, margin: '0 0 8px', letterSpacing: '-0.015em'}}>Check your email</h2>
          <p style={{fontSize: 15, color: AUTH_TOKENS.ink3, margin: '0 0 8px', lineHeight: 1.55}}>
            We sent a password reset link to
          </p>
          <p style={{fontSize: 15, color: AUTH_TOKENS.ink, fontWeight: 600, margin: '0 0 24px'}}>
            amara@acmelogistics.com
          </p>
          <Banner variant="info" title="Link expires in 60 minutes">
            For security, the reset link works only once and expires after one hour.
          </Banner>
          <p style={{fontSize: 13, color: AUTH_TOKENS.ink3, margin: '24px 0 8px'}}>
            Didn't receive it? <a style={{color: AUTH_TOKENS.green, fontWeight: 600, textDecoration: 'none'}}>Resend email</a>
          </p>
          <p style={{fontSize: 13, color: AUTH_TOKENS.ink4, margin: 0}}>
            Or try a <a style={{color: AUTH_TOKENS.green, fontWeight: 600, textDecoration: 'none'}}>different email address</a>
          </p>
        </div>
      </AuthShell>
    );
  }
  return (
    <AuthShell>
      <a style={{display: 'inline-flex', alignItems: 'center', gap: 6, color: AUTH_TOKENS.ink3, fontWeight: 500, fontSize: 13, textDecoration: 'none', marginBottom: 32}}>
        <Icon name="arrowleft" size={14} /> Back to sign in
      </a>
      <FormHead title="Reset your password" sub="Enter the email associated with your account. We'll send a reset link." />
      <Field label="Email address" type="email" icon="mail" placeholder="you@company.com" value="" />
      <Button variant="accent" size="lg">Send reset link</Button>
      <p style={{textAlign: 'center', fontSize: 13, color: AUTH_TOKENS.ink3, margin: '20px 0 0'}}>
        Remember your password? <a style={{color: AUTH_TOKENS.green, fontWeight: 700, textDecoration: 'none'}}>Sign in →</a>
      </p>
    </AuthShell>
  );
};

// ============================================================
// 1.4 — SET NEW PASSWORD
// ============================================================
const SetPasswordScreen = ({state = 'form'}) => {
  if (state === 'success') {
    return (
      <AuthShell>
        <div style={{textAlign: 'center'}}>
          <div style={{width: 84, height: 84, borderRadius: '50%', background: AUTH_TOKENS.successSoft, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px'}}>
            <Icon name="check" size={42} color={AUTH_TOKENS.success} stroke={2.5} />
          </div>
          <h2 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 700, fontSize: 28, color: AUTH_TOKENS.ink, margin: '0 0 8px', letterSpacing: '-0.015em'}}>Password updated.</h2>
          <p style={{fontSize: 15, color: AUTH_TOKENS.ink3, margin: '0 0 32px', lineHeight: 1.55}}>
            Your password has been changed. Redirecting you to sign in...
          </p>
          <div style={{display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, fontSize: 13, color: AUTH_TOKENS.ink4, fontWeight: 500}}>
            <div style={{width: 16, height: 16, border: `2px solid ${AUTH_TOKENS.line}`, borderTopColor: AUTH_TOKENS.green, borderRadius: '50%', animation: 'spinx 0.8s linear infinite'}} />
            Redirecting in 3...
          </div>
        </div>
      </AuthShell>
    );
  }
  return (
    <AuthShell>
      <FormHead title="Set a new password" sub="Choose a strong password. You'll be signed in automatically after setting it." />
      <Field label="New password" type="password" icon="lock" trailing="eye" placeholder="At least 12 characters" value="Logistic2026!" />
      <PasswordStrength level={3} />
      <div style={{marginTop: 16}}>
        <Field label="Confirm new password" type="password" icon="lock" trailing="eye" placeholder="Re-enter password" value="Logistic2026!" />
      </div>
      <div style={{background: AUTH_TOKENS.muted, border: `1px solid ${AUTH_TOKENS.line}`, borderRadius: 10, padding: '12px 14px', margin: '8px 0 24px', fontSize: 12, color: AUTH_TOKENS.ink3, lineHeight: 1.7}}>
        <div style={{fontWeight: 600, color: AUTH_TOKENS.ink2, marginBottom: 6, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.08em'}}>Password requirements</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 6}}><Icon name="check" size={12} color={AUTH_TOKENS.success} stroke={3} /> At least 12 characters</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 6}}><Icon name="check" size={12} color={AUTH_TOKENS.success} stroke={3} /> Mix of upper &amp; lowercase</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 6}}><Icon name="check" size={12} color={AUTH_TOKENS.success} stroke={3} /> At least one number</div>
        <div style={{display: 'flex', alignItems: 'center', gap: 6, color: AUTH_TOKENS.ink3}}><Icon name="check" size={12} color={AUTH_TOKENS.success} stroke={3} /> At least one special character</div>
      </div>
      <Button variant="accent" size="lg">Update password</Button>
    </AuthShell>
  );
};

// ============================================================
// MOBILE LOGIN VARIANT
// ============================================================
const MobileLoginScreen = () => (
  <div style={{height: '100%', background: '#fff', fontFamily: AUTH_TOKENS.body, display: 'flex', flexDirection: 'column'}}>
    {/* Top brand bar */}
    <div style={{background: AUTH_TOKENS.greenForest, padding: '32px 24px 40px', color: '#fff'}}>
      <ShipxLockup size="md" />
      <h2 style={{fontFamily: AUTH_TOKENS.display, fontWeight: 800, fontSize: 24, letterSpacing: '-0.02em', margin: '24px 0 6px', color: '#fff'}}>
        Cargo logistics,<br /><span style={{color: AUTH_TOKENS.greenFlash}}>engineered to move.</span>
      </h2>
      <p style={{fontSize: 13, color: 'rgba(255,255,255,0.6)', margin: 0}}>Guangzhou to Lagos. End-to-end.</p>
    </div>
    {/* Form */}
    <div style={{flex: 1, padding: '32px 24px'}}>
      <FormHead title="Sign in" sub="Welcome back. Pick up where you left off." />
      <Field label="Email address" type="email" icon="mail" placeholder="you@company.com" />
      <Field label="Password" type="password" icon="lock" trailing="eye" placeholder="••••••••" />
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '4px 0 20px'}}>
        <Checkbox label="Remember me" />
        <a style={{color: AUTH_TOKENS.green, fontWeight: 600, fontSize: 13, textDecoration: 'none'}}>Forgot?</a>
      </div>
      <Button variant="accent" size="lg">Sign In</Button>
      <Divider>or</Divider>
      <p style={{textAlign: 'center', fontSize: 13, color: AUTH_TOKENS.ink3}}>
        New customer? <a style={{color: AUTH_TOKENS.green, fontWeight: 700, textDecoration: 'none'}}>Register →</a>
      </p>
    </div>
  </div>
);

Object.assign(window, {
  LoginScreen,
  RegisterScreen,
  ForgotPasswordScreen,
  SetPasswordScreen,
  MobileLoginScreen,
  AUTH_TOKENS,
});
