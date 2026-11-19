import { Component, type ErrorInfo, type JSX, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { homePathForRole } from '../auth/roleHome'
import { useSession } from '../auth/useSession'
import { Button } from '../design/components'
import styles from './ErrorBoundary.module.css'

export interface ErrorBoundaryProps {
  children: ReactNode
  /** The error is cleared whenever this changes, so navigating away from a broken page recovers. */
  resetKey?: string
  /** Where "Go home" points. A plain link on purpose: after an error, a clean reload is the safe way back. */
  homeHref?: string
  /** `app` replaces the whole screen; `content` sits inside a layout so the menu stays usable. */
  variant?: 'app' | 'content'
  /** Shown instead of the default panel when set. `null` shows nothing, for chrome that is not worth a screen. */
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  failed: boolean
}

/** Replace UUIDs and long numbers in a path, so what is logged names the page, not a record. */
export function redactPath(path: string): string {
  return path
    .replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ':id')
    .replace(/\/\d{4,}/g, '/:n')
}

/**
 * Catches a render error below it and shows a way back, instead of letting React unmount the whole app
 * to a white screen. Nothing else catches these: one unexpected `undefined` on any page was enough.
 *
 * What is logged names the kind of error and the page, never the message or props: those can carry
 * customer data (frontend/11_security_and_compliance.md). The message is logged in development only.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    const components = (info.componentStack ?? '')
      .split('\n')
      .map((line) => line.trim().match(/^at (\w+)/)?.[1])
      .filter((name): name is string => Boolean(name))
      .slice(0, 6)
    console.error('Render error caught by ErrorBoundary', {
      name: error.name,
      page: redactPath(window.location.pathname),
      components,
      ...(import.meta.env.DEV ? { message: error.message } : {}),
    })
  }

  componentDidUpdate(previous: ErrorBoundaryProps): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false })
  }

  private retry = (): void => this.setState({ failed: false })

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    if (this.props.fallback !== undefined) return this.props.fallback
    const full = this.props.variant === 'app'
    return (
      <div role="alert" className={[styles.panel, full ? styles.fullPage : ''].filter(Boolean).join(' ')}>
        <h1 className={styles.title}>Something went wrong</h1>
        <p className={styles.message}>
          This page hit an unexpected problem. Your work elsewhere is not affected. Try again, or go back to the start.
        </p>
        <div className={styles.actions}>
          <Button variant="primary" onClick={this.retry}>Try again</Button>
          <a className={styles.link} href={this.props.homeHref ?? '/'}>Go home</a>
        </div>
      </div>
    )
  }
}

/**
 * For optional chrome (a banner, a badge): if it breaks it disappears, and the page and menu around it keep working.
 * A quota banner reading an unexpected response must never take the whole app down.
 */
export function QuietBoundary({ children }: { children: ReactNode }): JSX.Element {
  return <ErrorBoundary fallback={null}>{children}</ErrorBoundary>
}

/** The boundary for a layout's routed content: resets on navigation and knows the role's home. */
export function ContentErrorBoundary({ children }: { children: ReactNode }): JSX.Element {
  const { pathname } = useLocation()
  const { session } = useSession()
  return (
    <ErrorBoundary variant="content" resetKey={pathname} homeHref={session ? homePathForRole(session.role) : '/'}>
      {children}
    </ErrorBoundary>
  )
}
