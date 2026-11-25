import { useEffect, useRef, type JSX, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon, KolaMark, ShipxWordmark } from '../../design/components'
import styles from './LandingPage.module.css'

// Scroll-reveal, ported from the v2 prototype's inline script: elements
// tagged data-reveal get .reveal (hidden, shifted down) on mount and .revealIn
// once they enter the viewport, with a stagger delay by sibling position.
// Classes are added by JS — never in the JSX — so content stays visible if
// the effect never runs; the CSS additionally gates the hidden state behind
// prefers-reduced-motion: no-preference.
function useScrollReveal(rootRef: { current: HTMLElement | null }): void {
  useEffect(() => {
    const root = rootRef.current
    if (!root) return undefined
    const targets = root.querySelectorAll<HTMLElement>('[data-reveal]')
    const stagger = [styles.revealD1!, styles.revealD2!, styles.revealD3!]
    targets.forEach((el) => {
      el.classList.add(styles.reveal!)
      const index = el.parentElement ? Array.prototype.indexOf.call(el.parentElement.children, el) : 0
      const delay = index % 4
      if (delay >= 1) el.classList.add(stagger[delay - 1]!)
    })
    if (!('IntersectionObserver' in window)) {
      targets.forEach((el) => el.classList.add(styles.revealIn!))
      return undefined
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add(styles.revealIn!)
            io.unobserve(entry.target)
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    )
    targets.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [rootRef])
}

// CTAs here are navigational (route changes / same-page scroll / mailto), not
// form actions — rendered as styled <a>/<Link> rather than <button> (the
// design system's Button) so we never nest interactive anchor content inside
// a <button>, which is invalid HTML and breaks keyboard/screen-reader focus.
type CtaVariant = 'accent' | 'primary' | 'secondary' | 'ghost'

const CTA_VARIANT_CLASS: Record<CtaVariant, string> = {
  accent: styles.btnAccent!,
  primary: styles.btnPrimary!,
  secondary: styles.btnSecondary!,
  ghost: styles.btnGhost!,
}

function ctaClass(variant: CtaVariant, small = false): string {
  return [styles.btn, CTA_VARIANT_CLASS[variant], small ? styles.btnSm : ''].filter(Boolean).join(' ')
}

function CtaLink({
  to,
  variant,
  small,
  full,
  children,
}: {
  to: string
  variant: CtaVariant
  small?: boolean
  full?: boolean
  children: ReactNode
}): JSX.Element {
  const className = [ctaClass(variant, small), full ? styles.btnFull : ''].filter(Boolean).join(' ')
  return (
    <Link to={to} className={className}>
      {children}
    </Link>
  )
}

function CtaAnchor({
  href,
  variant,
  small,
  full,
  children,
}: {
  href: string
  variant: CtaVariant
  small?: boolean
  full?: boolean
  children: ReactNode
}): JSX.Element {
  const className = [ctaClass(variant, small), full ? styles.btnFull : ''].filter(Boolean).join(' ')
  return (
    <a href={href} className={className}>
      {children}
    </a>
  )
}

interface Feature {
  icon: Parameters<typeof Icon>[0]['name']
  tone: 'info' | 'primary' | 'accent' | 'warning' | 'bright' | 'ink'
  title: string
  body: string
}

const FEATURES: Feature[] = [
  {
    icon: 'container',
    tone: 'info',
    title: 'Containers & tracking',
    body: 'Create containers, track them through 8 stages from China warehouse to Lagos pickup, with a clear China-side / Nigeria-side handoff.',
  },
  {
    icon: 'package',
    tone: 'primary',
    title: 'Packing lists',
    body: "Carton-level capture with auto-CBM, an approval workflow, and bulk import from Excel when you're processing a whole container at once.",
  },
  {
    icon: 'coin',
    tone: 'accent',
    title: 'Billing on autopilot',
    body: 'Every bill computed from your configured CBM and USD→NGN rates. Misc charges, carryovers, storage fees and CBM disputes all handled.',
  },
  {
    icon: 'warn',
    tone: 'warning',
    title: 'Claims & customs',
    body: 'Log damage, missing items and seized goods. Verify manifests on arrival, manage customs clearance, and resolve disputes with a full paper trail.',
  },
  {
    icon: 'user',
    tone: 'bright',
    title: 'Customer self-service',
    body: 'Your customers register, track shipments, see their bill, pay with Paystack, and file claims — without tying up your staff on the phone.',
  },
  {
    icon: 'log',
    tone: 'ink',
    title: 'Release notes & pickup',
    body: 'Generate release notes the moment a bill is settled, with QR codes your warehouse scans to confirm pickup — partial releases included.',
  },
]

interface RoleCard {
  label: string
  tone: 'admin' | 'china' | 'nigeria' | 'warehouse' | 'customer' | 'platform'
  title: string
  body: string
  dark?: boolean
}

const ROLES: RoleCard[] = [
  {
    label: 'Admin',
    tone: 'admin',
    title: 'You, the owner',
    body: 'Configure rates, branding and charge types. Invite staff, manage customers, and see business-wide reports and analytics.',
  },
  {
    label: 'China Office',
    tone: 'china',
    title: 'Your Guangzhou team',
    body: 'Receive cargo, build packing lists, load containers, and update China-side tracking stages as goods move toward the vessel.',
  },
  {
    label: 'Nigeria Office',
    tone: 'nigeria',
    title: 'Your Lagos team',
    body: 'Verify manifests on arrival, clear customs, generate billing, resolve claims, and issue release notes to customers.',
  },
  {
    label: 'Warehouse',
    tone: 'warehouse',
    title: 'Pickup staff',
    body: "Scan a release note's QR code, confirm the customer's identity, and record the pickup — no training required.",
  },
  {
    label: 'Customer',
    tone: 'customer',
    title: 'Your clients',
    body: 'A clean self-service portal to track cargo, view bills, pay online and file claims — branded as your company.',
  },
  {
    label: 'Multi-tenant',
    tone: 'platform',
    title: 'Your own isolated space',
    body: 'Your data, users, customers and branding stay completely separate from every other company on Shipx.',
    dark: true,
  },
]

const STEPS = [
  {
    n: 1,
    title: 'Request access',
    body: 'Tell us about your operation. Once we have set up your workspace, upload your logo and set your USD→NGN and CBM rates.',
  },
  {
    n: 2,
    title: 'Invite your team',
    body: 'Add your China office, Nigeria office and warehouse staff. Each lands in the right portal with the right permissions.',
  },
  {
    n: 3,
    title: 'Start shipping',
    body: 'Create your first container, build packing lists, and watch billing, tracking and customer notifications run themselves.',
  },
]

interface PricingTier {
  tier: string
  sub: string
  amount: string
  cadence: string
  perks: string[]
  featured?: boolean
  cta: ReactNode
}

function NavLogo(): JSX.Element {
  return (
    <Link to="/" className={styles.logo}>
      <KolaMark size={30} color="var(--color-primary-bright)" />
      <ShipxWordmark size={22} color="#fff" xColor="#fed7aa" />
    </Link>
  )
}

export function LandingPage(): JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null)
  useScrollReveal(rootRef)

  const pricing: PricingTier[] = [
    {
      tier: 'Starter',
      sub: 'For solo operators getting off spreadsheets.',
      amount: '₦180k',
      cadence: 'billed monthly',
      perks: ['Up to 10 staff users', '20 containers / month', '5 GB document storage', 'SMS + WhatsApp + email alerts'],
      cta: (
        <CtaLink to="/get-started" variant="secondary" full>
          Request access
        </CtaLink>
      ),
    },
    {
      tier: 'Professional',
      sub: 'For established forwarders running steady volume.',
      amount: '₦480k',
      cadence: 'billed monthly',
      perks: [
        'Up to 50 staff users',
        '200 containers / month',
        '10 GB document storage',
        'API access for integrations',
        'Priority support',
      ],
      featured: true,
      cta: (
        <CtaLink to="/get-started" variant="primary" full>
          Request access
        </CtaLink>
      ),
    },
    {
      tier: 'Enterprise',
      sub: 'For large-volume operations with custom needs.',
      amount: 'Custom',
      cadence: 'annual contract · white-glove onboarding',
      perks: ['100+ staff users', '500+ containers / month', '50 GB+ storage', 'SSO & dedicated support'],
      cta: (
        <CtaAnchor href="mailto:sales@shipx.co" variant="secondary" full>
          Talk to sales
        </CtaAnchor>
      ),
    },
  ]

  return (
    <div className={styles.page} ref={rootRef}>
      <header className={styles.nav}>
        <div className={styles.wrap}>
          <NavLogo />
          <nav className={styles.navLinks}>
            <a href="#how">How it works</a>
            <a href="#features">Features</a>
            <a href="#roles">For your team</a>
            <a href="#pricing">Pricing</a>
          </nav>
          <div className={styles.navCta}>
            <Link to="/login" className={styles.signIn}>
              Sign in
            </Link>
            <CtaLink to="/get-started" variant="accent" small>
              Request access
            </CtaLink>
          </div>
        </div>
      </header>

      <div className={styles.hero}>
        <div className={styles.wrap}>
          <div className={styles.eyebrow}>
            <span className={styles.eyebrowDot} aria-hidden="true" />
            Built for China → Nigeria freight forwarders
          </div>
          <h1 className={styles.heroHeading}>
            Run your entire cargo operation on <em>one platform.</em>
          </h1>
          <p className={styles.heroSub}>
            Shipx gives shipping companies everything to move cargo from Guangzhou to Lagos — containers, packing
            lists, billing, customs, claims and customer tracking. One login for your whole team.
          </p>
          <div className={styles.heroCta}>
            {/* A request our team reviews, not a self-serve trial (FD-30): the copy promises what /get-started does. */}
            <CtaLink to="/get-started" variant="accent">
              Request access
            </CtaLink>
            <CtaAnchor href="#how" variant="ghost">
              See how it works
            </CtaAnchor>
            <span className={styles.heroNote}>We review every request and set up your workspace with you.</span>
          </div>
          <div className={styles.heroStats}>
            <div className={styles.stat}>
              <div className={styles.statN}>
                18–24<em>d</em>
              </div>
              <div className={styles.statL}>Average transit, fully tracked</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statN}>6</div>
              <div className={styles.statL}>Role-based portals in one app</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statN}>100%</div>
              <div className={styles.statL}>Of billing on a live FX + CBM engine</div>
            </div>
          </div>
        </div>
      </div>

      <div className={styles.route}>
        <div className={`${styles.wrap} ${styles.routeWrap}`}>
          <div className={styles.routeNode} data-reveal="">
            <div className={`${styles.routePin} ${styles.routePinChina}`}>
              <Icon name="container" size={18} stroke={2} />
            </div>
            <div>
              <div className={styles.routeCity}>Guangzhou</div>
              <div className={styles.routeCode}>CN-CAN · origin warehouse</div>
            </div>
          </div>
          <div className={styles.routeLine} aria-hidden="true" />
          <div className={styles.routeNode} data-reveal="">
            <div className={`${styles.routePin} ${styles.routePinTransit}`}>
              <Icon name="truck" size={18} stroke={2} />
            </div>
            <div>
              <div className={styles.routeCity}>In transit</div>
              <div className={styles.routeCode}>live tracking · 6 stages</div>
            </div>
          </div>
          <div className={styles.routeLine} aria-hidden="true" />
          <div className={styles.routeNode} data-reveal="">
            <div className={`${styles.routePin} ${styles.routePinLagos}`}>
              <Icon name="home" size={18} stroke={2} />
            </div>
            <div>
              <div className={styles.routeCity}>Lagos</div>
              <div className={styles.routeCode}>NG-LOS · Tin Can Port</div>
            </div>
          </div>
        </div>
      </div>

      <section className={styles.block}>
        <div className={styles.wrap}>
          <div className={styles.secHead} data-reveal="">
            <div className={styles.secTag}>Why Shipx</div>
            <h2>Stop running your business on WhatsApp and spreadsheets.</h2>
            <p>
              Most China–Nigeria forwarders juggle a dozen disconnected tools. Shipx replaces all of it with one
              system your whole team — and your customers — actually log into.
            </p>
          </div>
          <div className={styles.split}>
            <div className={`${styles.panel} ${styles.panelProblem}`} data-reveal="">
              <h3>The old way</h3>
              <ul>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconBad}`}>✕</span>
                  Packing lists in Excel, emailed back and forth, versions everywhere
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconBad}`}>✕</span>
                  Billing calculated by hand — FX and CBM errors cost you money
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconBad}`}>✕</span>
                  Customers call and message constantly: "where is my cargo?"
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconBad}`}>✕</span>
                  No record of who changed what, when a dispute arises
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconBad}`}>✕</span>
                  China office and Lagos office working off different numbers
                </li>
              </ul>
            </div>
            <div className={`${styles.panel} ${styles.panelSolution}`} data-reveal="">
              <h3>The Shipx way</h3>
              <ul>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconGood}`}>✓</span>
                  Packing lists created once, approved in-app, locked to a container
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconGood}`}>✓</span>
                  Billing auto-computed from live CBM × FX rates, every time
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconGood}`}>✓</span>
                  Customers track their own cargo and pay online — fewer calls
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconGood}`}>✓</span>
                  Every action audit-logged with before/after history
                </li>
                <li>
                  <span className={`${styles.panelIcon} ${styles.panelIconGood}`}>✓</span>
                  One source of truth shared across both offices, in real time
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section className={`${styles.block} ${styles.blockMuted}`} id="features">
        <div className={styles.wrap}>
          <div className={styles.secHead} data-reveal="">
            <div className={styles.secTag}>Everything in one place</div>
            <h2>The full operation, end to end.</h2>
            <p>From the moment cargo enters your Guangzhou warehouse to the customer's pickup in Lagos.</p>
          </div>
          <div className={styles.features}>
            {FEATURES.map((f) => (
              <div className={styles.feat} key={f.title} data-reveal="">
                <div className={`${styles.featIcon} ${styles[`tone${capitalize(f.tone)}`]}`}>
                  <Icon name={f.icon} size={22} stroke={2} />
                </div>
                <h3>{f.title}</h3>
                <p>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={`${styles.block} ${styles.rolesBand}`} id="roles">
        <div className={styles.wrap}>
          <div className={styles.secHead} data-reveal="">
            <div className={styles.secTag}>For your whole team</div>
            <h2>One platform, every role.</h2>
            <p>
              Each member of your team gets exactly the tools they need — and nothing they don't. You control who
              sees what.
            </p>
          </div>
          <div className={styles.roles}>
            {ROLES.map((r) => (
              <div className={`${styles.roleCard} ${r.dark ? styles.roleCardDark : ''}`} key={r.label} data-reveal="">
                <span className={`${styles.roleBadge} ${styles[`role${capitalize(r.tone)}`]}`}>{r.label}</span>
                <h4>{r.title}</h4>
                <p>{r.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.block} id="how">
        <div className={styles.wrap}>
          <div className={styles.secHead} data-reveal="">
            <div className={styles.secTag}>How it works</div>
            <h2>Live in a day, not a quarter.</h2>
            <p>No lengthy implementation. Request access, set your rates, invite your team, and start moving cargo.</p>
          </div>
          <div className={styles.features}>
            {STEPS.map((s) => (
              <div className={styles.feat} key={s.n} data-reveal="">
                <div className={`${styles.featIcon} ${styles.stepIcon}`}>{s.n}</div>
                <h3>{s.title}</h3>
                <p>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={`${styles.block} ${styles.blockMuted}`} id="pricing">
        <div className={styles.wrap}>
          <div className={styles.secHead} data-reveal="">
            <div className={styles.secTag}>Pricing</div>
            <h2>Plans that grow with your cargo.</h2>
            <p>
              Every plan includes all six role portals, customer self-service, and the billing engine. You only
              scale up limits as you grow.
            </p>
          </div>
          <div className={styles.pricing}>
            {pricing.map((p) => (
              <div className={`${styles.priceCard} ${p.featured ? styles.priceCardFeatured : ''}`} key={p.tier} data-reveal="">
                {p.featured && <div className={styles.pop}>Most popular</div>}
                <div className={styles.tier}>{p.tier}</div>
                <div className={styles.tierSub}>{p.sub}</div>
                <div className={styles.amt}>
                  {p.amount}
                  {p.amount !== 'Custom' && <span> / mo</span>}
                </div>
                <div className={styles.amtNote}>{p.cadence}</div>
                <ul className={styles.plist}>
                  {p.perks.map((perk) => (
                    <li key={perk}>
                      <span className={styles.plistIcon}>✓</span>
                      {perk}
                    </li>
                  ))}
                </ul>
                {p.cta}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.ctaSection}>
        <div className={styles.wrap}>
          <div className={styles.ctaBand} data-reveal="">
            <h2>Lead every shipment. Guangzhou to Lagos.</h2>
            <p>
              Join the forwarders running their entire China–Nigeria operation on Shipx. Tell us about your operation
              and we will set up your branded portal with you.
            </p>
            <div className={`${styles.heroCta} ${styles.ctaCenter}`}>
              <CtaLink to="/get-started" variant="accent">
                Request access
              </CtaLink>
              <CtaAnchor href="mailto:sales@shipx.co" variant="ghost">
                Book a demo
              </CtaAnchor>
            </div>
          </div>
        </div>
      </section>

      <footer className={styles.foot}>
        <div className={styles.wrap}>
          <div className={styles.footGrid}>
            <div className={styles.footAbout}>
              <NavLogo />
              <p>
                The operating system for China–Nigeria cargo forwarders. Containers, billing, customs and customer
                tracking — in one platform.
              </p>
            </div>
            <div className={styles.footCol}>
              <h5>Product</h5>
              <a href="#features">Features</a>
              <a href="#roles">For your team</a>
              <a href="#pricing">Pricing</a>
              <Link to="/login">Sign in</Link>
            </div>
            <div className={styles.footCol}>
              <h5>Company</h5>
              <a href="mailto:hello@shipx.co">About ODUM</a>
              <a href="mailto:careers@shipx.co">Careers</a>
              <a href="mailto:hello@shipx.co">Contact</a>
            </div>
            <div className={styles.footCol}>
              <h5>Legal</h5>
              <a href="#">Terms of service</a>
              <a href="#">Privacy (NDPR)</a>
              <a href="#">Data processing</a>
            </div>
          </div>
          <div className={styles.footBottom}>
            <span>© 2026 Shipx · All rights reserved.</span>
            <span className={styles.footBy}>
              A product by <em>ODUM</em>
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}

function capitalize<S extends string>(s: S): Capitalize<S> {
  return (s.charAt(0).toUpperCase() + s.slice(1)) as Capitalize<S>
}
