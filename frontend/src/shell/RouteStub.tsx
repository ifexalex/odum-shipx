import type { JSX } from 'react'
import { useLocation } from 'react-router-dom'
import styles from './RouteStub.module.css'

export interface RouteStubProps {
  title: string
}

// Placeholder element for every route in routeTable.ts whose real screen
// hasn't been built yet — proves the route exists, is guarded, and renders
// inside the right shell, ahead of Task 07 swapping it for the real page.
export function RouteStub({ title }: RouteStubProps): JSX.Element {
  const location = useLocation()
  return (
    <div className={styles.stub}>
      <h2 className={styles.title}>{title}</h2>
      <span className={styles.path}>{location.pathname}</span>
      <p className={styles.note}>This screen is routed and guarded — the real page lands in Task 07.</p>
    </div>
  )
}
