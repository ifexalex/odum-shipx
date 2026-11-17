import { packingListApi, type PackingList } from '../../../api/packingList'

/**
 * Fetch every packing list on a container, following the cursor to the end.
 *
 * The overview's cargo summary (customer count, cartons, CBM) and the
 * packing-lists tab both aggregate this list in memory, so a single page is not
 * enough: the endpoint returns 50 by default, and a real forwarder manifest
 * routinely exceeds that (the STL409 export alone creates 68). Fetching one
 * page made the page silently under-report its own totals — 50 customers and
 * 35.77 CBM against an actual 68 and 72.55.
 *
 * `_MAX_PAGES` is a guard against a malformed cursor looping forever, not an
 * expected ceiling; at 100 rows per page it covers 10k packing lists.
 */
const _MAX_PAGES = 100

export async function fetchAllPackingLists(containerId: string): Promise<PackingList[]> {
  const all: PackingList[] = []
  let cursor: string | undefined
  for (let page = 0; page < _MAX_PAGES; page += 1) {
    const result = await packingListApi.listByContainer(containerId, { limit: 100, cursor })
    all.push(...result.data)
    const next = result.meta?.pagination?.next_cursor
    if (!result.meta?.pagination?.has_more || !next) break
    cursor = next
  }
  return all
}
