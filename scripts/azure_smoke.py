#!/usr/bin/env python3
"""Manual smoke test of the Azure provider adapters against REAL Azure resources.

This is intentionally NOT a pytest test — the pytest suite is fully mocked and
never touches a real cloud. Run this by hand after `terraform apply` to prove the
adapters work end-to-end against your own account (or Azurite for Blob). It prints
each real call + result so you can watch it connect.

Prereqs:
    az login                                  # for Key Vault (DefaultAzureCredential)
    export AZURE_STORAGE_CONNECTION_STRING=$(terraform -chdir=infrastructure/azure output -raw storage_connection_string)
    export BLOB_CONTAINER_NAME=$(terraform -chdir=infrastructure/azure output -raw blob_container_name)
    export AZURE_KEY_VAULT_URL=$(terraform -chdir=infrastructure/azure output -raw key_vault_url)
    export ENCRYPTION_KEY_VAULT_KEY_ID=$(terraform -chdir=infrastructure/azure output -raw encryption_key_vault_key_id)

Usage:
    python scripts/azure_smoke.py            # runs every check its env is configured for
    python scripts/azure_smoke.py --blob     # only the ones you name
    python scripts/azure_smoke.py --keyvault --secret

Each check is skipped (not failed) when its env vars are absent, so you can run a
subset. Exit code is non-zero if any attempted check fails.
"""
import argparse
import os
import sys
import uuid

CLOUD = os.environ.get("CLOUD_PROVIDER", "")


def _require_azure() -> None:
    if CLOUD and CLOUD != "azure":
        print(f"  note: CLOUD_PROVIDER={CLOUD!r}; adapters are constructed directly here, so this is fine.")


def check_blob() -> bool:
    """Real Blob SAS round-trip: presigned PUT (201) then presigned GET (200)."""
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    container = os.environ.get("BLOB_CONTAINER_NAME", "logistics-assets")
    if not conn:
        print("blob:      SKIP (AZURE_STORAGE_CONNECTION_STRING not set)")
        return True

    import requests

    from shared.providers.azure.blob import BlobStorageProvider

    provider = BlobStorageProvider(container)
    key = f"smoke/{uuid.uuid4().hex}.txt"
    body = b"shipx-azure-smoke"
    print(f"blob:      container={container} key={key}")

    ticket = provider.presigned_upload(key, content_type="text/plain", expires_in=600)
    put = requests.put(ticket.url, data=body, headers=ticket.headers, timeout=15)
    print(f"  PUT  {put.status_code} (expect 201) via {ticket.method} + {sorted(ticket.headers)}")
    if put.status_code != 201:
        print(f"  FAIL: {put.text[:300]}")
        return False

    get_url = provider.presigned_get_url(key, expires_in=600)
    got = requests.get(get_url, timeout=15)
    ok = got.status_code == 200 and got.content == body
    print(f"  GET  {got.status_code} (expect 200), body_matches={got.content == body}")

    provider.delete_prefix("smoke/")
    print(f"  cleanup: delete_prefix('smoke/') size_after={provider.object_size(key)}")
    print("  -> PASS" if ok else "  -> FAIL")
    return ok


def check_keyvault_key() -> bool:
    """Real Key Vault RSA wrap/unwrap of a 32-byte data key."""
    key_id = os.environ.get("ENCRYPTION_KEY_VAULT_KEY_ID", "")
    if not key_id:
        print("keyvault:  SKIP (ENCRYPTION_KEY_VAULT_KEY_ID not set)")
        return True

    from shared.providers.azure.keyvault import KeyVaultKeyProvider

    provider = KeyVaultKeyProvider(key_id)
    print(f"keyvault:  key={key_id}")
    plaintext, wrapped = provider.generate_data_key()
    recovered = provider.decrypt_data_key(wrapped)
    ok = len(plaintext) == 32 and recovered == plaintext
    print(f"  wrap {len(wrapped)}B -> unwrap, 32-byte & round-trip={ok}")
    print("  -> PASS" if ok else "  -> FAIL")
    return ok


def check_secret() -> bool:
    """Real Key Vault secret read."""
    vault = os.environ.get("AZURE_KEY_VAULT_URL", "")
    if not vault:
        print("secret:    SKIP (AZURE_KEY_VAULT_URL not set)")
        return True

    from shared.providers.azure.keyvault_secrets import KeyVaultSecretsProvider

    name = os.environ.get("AZURE_KEYVAULT_SMOKE_SECRET", "shipx-smoke-secret")
    value = KeyVaultSecretsProvider().get_secret(name)
    ok = value == "ok"
    print(f"secret:    vault={vault} name={name} value={value!r} (expect 'ok')")
    print("  -> PASS" if ok else "  -> FAIL")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blob", action="store_true")
    parser.add_argument("--keyvault", action="store_true")
    parser.add_argument("--secret", action="store_true")
    args = parser.parse_args()

    # No flags → run everything that's configured.
    run_all = not (args.blob or args.keyvault or args.secret)
    _require_azure()

    checks = []
    if run_all or args.blob:
        checks.append(check_blob)
    if run_all or args.keyvault:
        checks.append(check_keyvault_key)
    if run_all or args.secret:
        checks.append(check_secret)

    results = [fn() for fn in checks]
    print("\n" + ("ALL PASS" if all(results) else "FAILURES — see above"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
