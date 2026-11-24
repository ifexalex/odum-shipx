/**
 * UnsavedChangesGuard (FD-54): the one guard a form or wizard switches on while it holds input that is not saved.
 *
 *   <UnsavedChangesGuard when={dirty && !saving} />
 *
 * - **Leaving within the app** (a sidebar link, a breadcrumb, the browser's Back) asks "Leave without saving?" first.
 *   Staying keeps everything; leaving goes where the user was going.
 * - **Closing or reloading the tab** gets the browser's own "Leave site?" prompt (browsers show their own wording).
 *
 * `when` must turn false before the form navigates after a successful save, or the save would be asked about: pass
 * `dirty && !submitting`. `allow` lets a form exempt a destination it sends the user to on purpose and returns from
 * (the packing-list wizard's "Create a container").
 *
 * Holding in-app navigation needs a data router (`useBlocker`). The app has one; a page rendered under a plain
 * <MemoryRouter> in a unit test gets the tab-close prompt only.
 */
import { useContext, useEffect, type JSX, type ReactNode } from 'react'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import { ConfirmDialog } from '../design/components'

export interface UnsavedChangesGuardProps {
  /** True while the form holds unsaved input. */
  when: boolean
  /** A destination that does not need asking about (path only, no query). */
  allow?: (pathname: string) => boolean
  /** The dialog's title; "Leave without saving?" by default. */
  title?: string
  /** What leaving costs, in a sentence. */
  children?: ReactNode
  /** How to get the input back, when it is kept somewhere (a tab draft); false when it is lost. */
  undo?: string | false
}

export function UnsavedChangesGuard({ when, allow, title, children, undo = false }: UnsavedChangesGuardProps): JSX.Element | null {
  const dataRouter = useContext(UNSAFE_DataRouterContext)

  // Tab close and reload: the browser asks, in its own words, while there is unsaved input.
  useEffect(() => {
    if (!when) return undefined
    const onBeforeUnload = (event: BeforeUnloadEvent): void => {
      event.preventDefault()
      // Older browsers need a return value to show the prompt.
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [when])

  return dataRouter ? (
    <NavigationPrompt when={when} allow={allow} title={title} undo={undo}>
      {children}
    </NavigationPrompt>
  ) : null
}

function NavigationPrompt({ when, allow, title, children, undo = false }: UnsavedChangesGuardProps): JSX.Element {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      when && currentLocation.pathname !== nextLocation.pathname && !(allow?.(nextLocation.pathname) ?? false),
  )
  return (
    <ConfirmDialog
      open={blocker.state === 'blocked'}
      title={title ?? 'Leave without saving?'}
      confirmLabel="Leave"
      cancelLabel="Keep editing"
      undo={undo}
      onConfirm={() => blocker.proceed?.()}
      onCancel={() => blocker.reset?.()}
    >
      {children ?? 'What you entered on this page has not been saved and will be lost.'}
    </ConfirmDialog>
  )
}
