import type { JSX } from 'react'
import { Avatar } from './Avatar'
import styles from './UserCell.module.css'

export interface UserCellProps {
  name: string
  email: string
}

// Avatar + name/meta pairing for table rows (customer, staff actor, etc.).
// `email` is reused for non-email meta text too (e.g. "22 cartons") in the
// mockups — kept that loose contract rather than renaming to "meta", since
// every call site in the source screens passes non-email strings there too.
export function UserCell({ name, email }: UserCellProps): JSX.Element {
  return (
    <div className={styles.cell}>
      <Avatar size={28} name={name} />
      <div className={styles.text}>
        <div className={styles.name}>{name}</div>
        <div className={styles.meta}>{email}</div>
      </div>
    </div>
  )
}
