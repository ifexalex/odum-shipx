"""An invoice built while the market feed is down, against a real database (audit BE-11, migration 068).

The whole invoicing path runs (pricing from real packing lists, the insert, the staff notice); only the market feed
is cut and the Redis cache left empty. Skipped when no database is reachable.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from shared.exceptions import ExternalServiceError
from tests.db.support import _rows

pytestmark = pytest.mark.db


@pytest.fixture
def billable(admin, world):
    """One customer with an approved 2 CBM packing list on a container, and a flat USD 200/CBM rate."""
    tenant, customer, container = world["tenant"], world["customers"][0], world["containers"][0]
    pl = str(uuid.uuid4())
    with admin.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant_config (tenant_id, config_key, config_value) VALUES (%s, 'cbm_rate_per_unit', %s)",
            (tenant, json.dumps({"currency": "usd", "rate_mode": "flat", "carton_rate": 200})),
        )
        cur.execute(
            "INSERT INTO packing_list (id, tenant_id, reference, container_id, customer_id, status) "
            "VALUES (%s, %s, 'PL-FX', %s, %s, 'approved')",
            (pl, tenant, container, customer),
        )
        cur.execute(
            "INSERT INTO packing_list_item (packing_list_id, tracking_code, description, cbm, package_unit, carton_tag) "
            "VALUES (%s, 'TRK-FX', 'Shoes', 2.0, 'carton', 'CT-FX')",
            (pl,),
        )
    yield world
    with admin.cursor() as cur:
        cur.execute("DELETE FROM staff_notification WHERE tenant_id = %s", (tenant,))
        cur.execute("DELETE FROM tenant_config WHERE tenant_id = %s", (tenant,))


def _outage(last_known: dict | None):
    """The feed refuses, the cache is empty, and the stored last-known rate is `last_known`."""
    return (
        patch("shared.fx_rate._cache.get", return_value=None),
        patch("shared.fx_rate.fetch_bybit_ngn_rate", side_effect=ExternalServiceError("Bybit P2P", "down")),
        patch("shared.fx_rate._read_persisted_fallback", return_value=last_known),
        patch("services.billing.service.publish_event"),
    )


def _bill(world):
    from services.billing import service

    return service.handle_payment_due(world["tenant"], world["containers"][0], world["customers"][0], "MNY0000")


def test_an_invoice_built_during_an_outage_is_flagged_and_staff_are_told(admin, billable):
    fetched = (datetime.now(UTC) - timedelta(hours=30)).replace(microsecond=0)
    a, b, c, d = _outage({"rate": "1500.00", "fetched_at": fetched.isoformat()})
    with a, b, c, d:
        outcome = _bill(billable)

    assert outcome.status == "created"
    [(rate, source, fetched_at)] = _rows(
        admin,
        "SELECT exchange_rate_ngn, exchange_rate_source, exchange_rate_fetched_at FROM billing WHERE id = %s",
        (outcome.billing_id,),
    )
    assert source == "last_known" and fetched_at == fetched and rate == 1500  # tenant has no markup
    [(title, role, entity)] = _rows(
        admin,
        "SELECT title, target_role, entity_id FROM staff_notification WHERE tenant_id = %s AND event_type = 'invoice_old_exchange_rate'",
        (billable["tenant"],),
    )
    assert role == "tenant_admin" and str(entity) == outcome.billing_id and "old exchange rate" in title

    # And staff see it on the invoice.
    from services.billing import service
    from shared.tenant_context import TenantContext, UserRole

    ctx = TenantContext(tenant_id=billable["tenant"], user_id=billable["user"], role=UserRole.NIGERIA_OFFICE_STAFF)
    body = service.get_billing(billable["tenant"], outcome.billing_id, ctx)
    assert body["exchange_rate_source"] == "last_known"
    assert body["exchange_rate_fetched_at"] == fetched.isoformat()


def test_with_no_rate_ever_fetched_no_invoice_is_written(admin, billable):
    a, b, c, d = _outage(None)
    with a, b, c, d:
        outcome = _bill(billable)

    assert outcome.status == "skipped" and outcome.reason == "RATE_UNAVAILABLE"
    assert _rows(admin, "SELECT COUNT(*) FROM billing WHERE tenant_id = %s", (billable["tenant"],))[0][0] == 0


def test_the_column_refuses_an_unknown_source(admin, world):
    import psycopg2

    from services.billing import repository as repo
    from tests.db.support import INVOICE_PREFIX, _invoice_data

    data = {**_invoice_data(world["tenant"], world["customers"][1], world["containers"][1]), "exchange_rate_source": "guess"}
    with pytest.raises(psycopg2.errors.CheckViolation):
        repo.create_invoice(world["tenant"], data, INVOICE_PREFIX, [], [])
