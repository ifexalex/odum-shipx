"""Document application-level field encryption for sensitive PII columns.

No schema change is made here. This migration records which columns are
protected by envelope encryption (AWS KMS + Fernet) at the application layer
via shared.encryption.encrypt_field / decrypt_field.

Encrypted columns (as of this migration):
  pickup_record.id_number
    — passport / national ID numbers supplied at cargo collection.
    — Write path: services/payment_release/repository.py:create_pickup_record
    — Requires: ENCRYPTION_KMS_KEY_ID env var on payment_release Lambda.

  refund_request.account_number
  refund_request.account_name
    — Bank account details supplied when a refund is paid directly to a customer.
    — Write path: to be added when the "capture bank details" endpoint is built;
      MUST call encrypt_field() before INSERT/UPDATE.
    — Read path: services/refunds/repository.py:_decrypt_refund_row (already applied
      to all SELECT / RETURNING * paths).
    — Requires: ENCRYPTION_KMS_KEY_ID env var on refunds Lambda.

Encryption scheme:
  Each value is protected with envelope encryption:
    1. KMS GenerateDataKey (AES-256) produces a plaintext key + encrypted key blob.
    2. Fernet encrypts the plaintext value with the plaintext key.
    3. The encrypted key blob and Fernet ciphertext are concatenated and
       base64-encoded before storage. No plaintext key material ever touches the DB.

KMS key: alias/{project_name}-field-encryption-{environment}
Terraform: infrastructure/aws/modules/kms/main.tf

Revision ID: 013
Revises: 012
Create Date: 2026-03-01 00:00:00
"""


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change — encryption is applied at the application layer.
    # Column types remain TEXT / VARCHAR; ciphertext is stored as base64 ASCII.
    pass


def downgrade() -> None:
    pass
