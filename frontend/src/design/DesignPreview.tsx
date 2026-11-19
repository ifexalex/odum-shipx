import { KolaMark } from './components/KolaMark'
import { ShipxWordmark } from './components/ShipxWordmark'
import { colors, fonts, radius, shadows, typeScale } from './theme'

const MARK_SIZES = [16, 24, 32, 48, 64]

// Dev-only visual QA route — renders every color/type/radius/shadow token plus
// the logo marks for design sign-off before component work begins (FE-03).
// Mounted at /design-preview only when import.meta.env.DEV (see App.tsx).
export function DesignPreview(): JSX.Element {
  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 40 }}>
      <h1>ShipX Design Preview</h1>

      <section>
        <h2>Logo marks (16px–64px)</h2>
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', background: colors.forestDark, padding: 16 }}>
          {MARK_SIZES.map((size) => (
            <KolaMark key={size} size={size} color={colors.primaryBright} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', background: colors.forestDark, padding: 16, marginTop: 8 }}>
          {MARK_SIZES.map((size) => (
            <ShipxWordmark key={size} size={size} />
          ))}
        </div>
      </section>

      <section>
        <h2>Colors</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {Object.entries(colors).map(([name, hex]) => (
            <div key={name} style={{ width: 140 }}>
              <div style={{ height: 56, borderRadius: radius.sm, background: hex, border: `1px solid ${colors.line}` }} />
              <div style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>{name}</div>
              <div style={{ fontSize: 'var(--text-xs)', color: colors.ink4 }}>{hex}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Type scale</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {Object.entries(typeScale).map(([name, style]) => (
            <div key={name} style={{ ...style, display: 'flex', gap: 12, alignItems: 'baseline' }}>
              <span style={{ width: 110, fontSize: 'var(--text-xs)', fontFamily: fonts.mono, color: colors.ink4 }}>{name}</span>
              <span>The quick brown fox ships cargo</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Radius</h2>
        <div style={{ display: 'flex', gap: 16 }}>
          {Object.entries(radius).map(([name, value]) => (
            <div key={name} style={{ textAlign: 'center' }}>
              <div
                style={{
                  width: 64,
                  height: 64,
                  borderRadius: value,
                  background: colors.primarySoft,
                  border: `1px solid ${colors.primary}`,
                }}
              />
              <div style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>{name}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Shadows</h2>
        <div style={{ display: 'flex', gap: 24 }}>
          {Object.entries(shadows).map(([name, value]) => (
            <div key={name} style={{ textAlign: 'center' }}>
              <div
                style={{
                  width: 96,
                  height: 64,
                  borderRadius: radius.md,
                  background: colors.surface,
                  boxShadow: name === 'scrimModal' ? undefined : value,
                  ...(name === 'scrimModal' ? { background: value } : {}),
                }}
              />
              <div style={{ fontSize: 'var(--text-xs)', marginTop: 4 }}>{name}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
