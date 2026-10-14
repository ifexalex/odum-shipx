// Apply the saved (or system) color scheme before first paint to avoid a
// light-mode flash. Mirrors src/design/colorScheme.tsx. Kept as an external
// same-origin file (not inline) so the strict CSP script-src 'self' allows it
// without 'unsafe-inline' or a per-build hash.
;(function () {
  try {
    var pref = localStorage.getItem('shipx-color-scheme') || 'system'
    var dark =
      pref === 'dark' ||
      (pref === 'system' &&
        window.matchMedia &&
        window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  } catch (e) {
    document.documentElement.dataset.theme = 'light'
  }
})()
