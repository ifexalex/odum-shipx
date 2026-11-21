/**
 * Run a document or export download with feedback (FD-44): a toast while it is prepared, and the reason when it
 * fails, so a button never silently does nothing. Returns whether it worked.
 *
 * `run` must start its request synchronously (as `apiDownloadFile` does), so a PDF's tab opens inside the click.
 */
import { ApiError } from '../api/client'
import { dismissToast, toast } from '../design/toast'

export async function runDocument(label: string, run: () => Promise<void>): Promise<boolean> {
  const pending = toast.info(`Preparing ${label}…`)
  try {
    await run()
    return true
  } catch (err) {
    toast.error(`Couldn't prepare ${label}`, err instanceof ApiError ? err.message : 'Check your connection and try again.')
    return false
  } finally {
    dismissToast(pending)
  }
}
