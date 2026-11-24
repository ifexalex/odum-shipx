/** Up to two initials from a name: "Acme Cargo Ltd" is "AC"; an empty name is "?". */
export function initialsFor(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  return (
    words
      .slice(0, 2)
      .map((w) => w[0]!.toUpperCase())
      .join('') || '?'
  )
}
