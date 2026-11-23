"""Unit tests for global search (audit UX-05): who may find what, how the text is bound, and how results are ranked.

The SQL itself is exercised against a real database in tests/db/test_search.py. Here the repository is mocked, and the
queries are inspected for the properties that matter: tenant scoping, a customer pin, and the text never being spliced in.
"""

import json
import logging
from unittest.mock import patch

import pytest

from services.search import handler, repository, service
from shared.exceptions import InsufficientPermissionsError, ValidationError
from shared.tenant_context import TenantContext, UserRole

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _ctx(role: UserRole, user_id: str = "user-1") -> TenantContext:
    return TenantContext(tenant_id=TENANT, user_id=user_id, role=role)


def _container(**kw):
    return {
        "id": "k1",
        "container_number": "MSKU1234567",
        "status": "at_warehouse",
        "vessel_name": "MSC Ana",
        "is_exact": False,
        **kw,
    }


def _shipment(**kw):
    return {
        "id": "p1",
        "reference": "PL-001",
        "status": "approved",
        "customer_name": "Ngozi",
        "container_number": "MSKU1",
        "is_exact": False,
        **kw,
    }


def _invoice(**kw):
    return {
        "id": "b1",
        "invoice_number": "INV-A-001",
        "status": "unpaid",
        "customer_name": "Ngozi",
        "container_number": "MSKU1",
        "is_exact": False,
        **kw,
    }


def _note(**kw):
    return {
        "id": "r1",
        "reference_number": "RN-1",
        "status": "active",
        "customer_name": "Ngozi",
        "container_number": "MSKU1",
        "is_exact": False,
        **kw,
    }


def _customer(**kw):
    return {"id": "c1", "name": "Ngozi Okonkwo", "phone": "+2348012345678", "is_exact": False, **kw}


@pytest.fixture
def repo():
    """Every repository lookup stubbed to find one record, so a test sees which ones the role reached."""
    with (
        patch.object(repository, "search_containers", return_value=[_container()]) as containers,
        patch.object(repository, "search_shipments", return_value=[_shipment()]) as shipments,
        patch.object(repository, "search_invoices", return_value=[_invoice()]) as invoices,
        patch.object(repository, "search_release_notes", return_value=[_note()]) as notes,
        patch.object(repository, "search_customers", return_value=[_customer()]) as customers,
        patch.object(repository, "get_customer_id_for_user", return_value="cust-own") as own,
    ):
        yield type(
            "R",
            (),
            {
                "containers": containers,
                "shipments": shipments,
                "invoices": invoices,
                "notes": notes,
                "customers": customers,
                "own": own,
            },
        )


def _kinds(result: dict) -> list[str]:
    return [r["kind"] for r in result["results"]]


class TestWhoFindsWhat:
    def test_a_tenant_admin_finds_every_kind(self, repo):
        assert _kinds(service.search(TENANT, "ngozi", _ctx(UserRole.TENANT_ADMIN))) == [
            "container",
            "shipment",
            "invoice",
            "release_note",
            "customer",
        ]

    def test_nigeria_staff_find_everything_but_customer_profiles(self, repo):
        """A customer profile is an admin page; they reach a customer's records through the invoices and notes."""
        assert _kinds(service.search(TENANT, "ngozi", _ctx(UserRole.NIGERIA_OFFICE_STAFF))) == [
            "container",
            "shipment",
            "invoice",
            "release_note",
        ]
        repo.customers.assert_not_called()

    def test_china_staff_find_containers_and_packing_lists_only(self, repo):
        assert _kinds(service.search(TENANT, "msku", _ctx(UserRole.CHINA_OFFICE_STAFF))) == ["container", "shipment"]
        repo.invoices.assert_not_called()
        repo.notes.assert_not_called()
        repo.customers.assert_not_called()

    def test_a_warehouse_attendant_finds_release_notes_only(self, repo):
        assert _kinds(service.search(TENANT, "rn-1", _ctx(UserRole.WAREHOUSE_ATTENDANT))) == ["release_note"]
        repo.containers.assert_not_called()
        repo.shipments.assert_not_called()
        repo.invoices.assert_not_called()

    def test_a_customer_finds_their_own_shipments_invoices_and_notes(self, repo):
        assert _kinds(service.search(TENANT, "msku", _ctx(UserRole.CUSTOMER))) == ["shipment", "invoice", "release_note"]
        repo.containers.assert_not_called()
        repo.customers.assert_not_called()

    def test_every_customer_query_is_pinned_to_their_record_and_does_not_match_names(self, repo):
        service.search(TENANT, "msku", _ctx(UserRole.CUSTOMER))
        for lookup in (repo.shipments, repo.invoices, repo.notes):
            assert lookup.call_args.kwargs["customer_id"] == "cust-own"
            assert lookup.call_args.kwargs["by_name"] is False

    def test_a_customer_login_with_no_customer_record_finds_nothing(self, repo):
        repo.own.return_value = None
        assert service.search(TENANT, "msku", _ctx(UserRole.CUSTOMER))["results"] == []
        repo.shipments.assert_not_called()

    def test_staff_queries_are_not_pinned_to_a_customer(self, repo):
        service.search(TENANT, "msku", _ctx(UserRole.NIGERIA_OFFICE_STAFF))
        assert repo.invoices.call_args.kwargs["customer_id"] is None
        assert repo.invoices.call_args.kwargs["by_name"] is True

    def test_a_platform_admin_is_refused(self, repo):
        with pytest.raises(InsufficientPermissionsError):
            service.search("PLATFORM", "msku", _ctx(UserRole.PLATFORM_ADMIN))
        repo.containers.assert_not_called()


class TestPhoneLookup:
    @pytest.mark.parametrize("typed", ["08012345678", "+234 801 234 5678", "2348012345678", "(0801) 234-5678"])
    def test_one_number_however_it_is_typed(self, typed):
        assert service._phone_pattern(typed) == "%8012345678%"

    @pytest.mark.parametrize("typed", ["12345", "0801", "ngozi", "MSKU1234567", "INV-2026-0001", "801234 abc"])
    def test_text_that_is_not_a_phone_number_is_never_one(self, typed):
        """A short fragment or a reference with digits in it must not match half the customer list."""
        assert service._phone_pattern(typed) == ""

    def test_admin_and_nigeria_staff_may_look_a_customer_up_by_phone(self, repo):
        for role in (UserRole.TENANT_ADMIN, UserRole.NIGERIA_OFFICE_STAFF):
            service.search(TENANT, "08012345678", _ctx(role))
            assert repo.invoices.call_args.args[3] == "%8012345678%"
            assert repo.invoices.call_args.kwargs["by_phone"] is True

    @pytest.mark.parametrize("role", [UserRole.CHINA_OFFICE_STAFF, UserRole.WAREHOUSE_ATTENDANT, UserRole.CUSTOMER])
    def test_other_roles_never_match_on_phone_numbers(self, repo, role):
        service.search(TENANT, "08012345678", _ctx(role))
        lookups = [repo.shipments, repo.notes]
        for lookup in lookups:
            if lookup.called:
                assert lookup.call_args.args[3] == ""
                assert lookup.call_args.kwargs["by_phone"] is False

    def test_a_customer_result_shows_the_phone_only_when_it_was_searched_by(self, repo):
        by_name = service.search(TENANT, "ngozi", _ctx(UserRole.TENANT_ADMIN))
        by_phone = service.search(TENANT, "08012345678", _ctx(UserRole.TENANT_ADMIN))
        assert next(r for r in by_name["results"] if r["kind"] == "customer")["subtitle"] is None
        assert next(r for r in by_phone["results"] if r["kind"] == "customer")["subtitle"] == "+2348012345678"


class TestTheText:
    @pytest.mark.parametrize("short", ["", " ", "a"])
    def test_too_short_to_search_returns_nothing_and_asks_the_database_nothing(self, repo, short):
        assert service.search(TENANT, short, _ctx(UserRole.TENANT_ADMIN))["results"] == []
        repo.containers.assert_not_called()

    def test_too_long_is_a_422(self, repo):
        with pytest.raises(ValidationError):
            service.search(TENANT, "x" * 65, _ctx(UserRole.TENANT_ADMIN))

    def test_spaces_are_normalised(self, repo):
        result = service.search(TENANT, "  ngozi    okonkwo ", _ctx(UserRole.TENANT_ADMIN))
        assert result["query"] == "ngozi okonkwo"

    @pytest.mark.parametrize(
        ("typed", "pattern"),
        [
            ("msku", "%msku%"),
            ("50%", "%50\\%%"),
            ("a_b", "%a\\_b%"),
            ("back\\slash", "%back\\\\slash%"),
            ("100% o_k\\", "%100\\% o\\_k\\\\%"),
        ],
    )
    def test_like_wildcards_in_the_text_are_literal(self, typed, pattern):
        """Typing % or _ must not turn the search into a pattern that matches everything."""
        assert service._like_pattern(typed) == pattern

    def test_the_pattern_reaches_the_repository(self, repo):
        service.search(TENANT, "50%", _ctx(UserRole.TENANT_ADMIN))
        assert repo.containers.call_args.args[2] == "%50\\%%"


class TestRanking:
    def test_an_exact_match_ranks_above_partial_matches_of_earlier_kinds(self, repo):
        repo.containers.return_value = [_container(is_exact=False)]
        repo.invoices.return_value = [_invoice(is_exact=True)]
        assert _kinds(service.search(TENANT, "INV-A-001", _ctx(UserRole.TENANT_ADMIN)))[0] == "invoice"

    def test_otherwise_results_follow_the_kind_order_and_each_kinds_own_ranking(self, repo):
        repo.shipments.return_value = [_shipment(id="s1"), _shipment(id="s2")]
        ids = [r["id"] for r in service.search(TENANT, "x1", _ctx(UserRole.TENANT_ADMIN))["results"] if r["kind"] == "shipment"]
        assert ids == ["s1", "s2"]

    def test_at_most_twenty_results(self, repo):
        repo.containers.return_value = [_container(id=f"k{i}") for i in range(5)]
        repo.shipments.return_value = [_shipment(id=f"s{i}") for i in range(5)]
        repo.invoices.return_value = [_invoice(id=f"b{i}") for i in range(5)]
        repo.notes.return_value = [_note(id=f"r{i}") for i in range(5)]
        repo.customers.return_value = [_customer(id=f"c{i}") for i in range(5)]
        assert len(service.search(TENANT, "x1", _ctx(UserRole.TENANT_ADMIN))["results"]) == 20

    def test_a_result_has_no_internal_fields(self, repo):
        for result in service.search(TENANT, "x1", _ctx(UserRole.TENANT_ADMIN))["results"]:
            assert set(result) == {"kind", "id", "title", "subtitle", "status"}

    def test_a_packing_list_with_no_reference_still_has_a_title(self, repo):
        repo.shipments.return_value = [_shipment(reference=None)]
        titles = [
            r["title"]
            for r in service.search(TENANT, "x1", _ctx(UserRole.CHINA_OFFICE_STAFF))["results"]
            if r["kind"] == "shipment"
        ]
        assert titles == ["Packing list"]

    def test_a_container_subtitle_is_its_vessel_not_a_repeat_of_the_status_field(self, repo):
        container = next(
            r for r in service.search(TENANT, "x1", _ctx(UserRole.TENANT_ADMIN))["results"] if r["kind"] == "container"
        )
        assert container["subtitle"] == "MSC Ana"
        assert container["status"] == "at_warehouse"


class TestQueriesAreSafe:
    """The SQL, inspected: tenant scope, the customer pin, erased customers, and the text only as a bound parameter."""

    @staticmethod
    def _captured(call):
        seen: list[tuple[str, dict]] = []
        with patch.object(repository, "execute_with_tenant", side_effect=lambda t, q, p=None: seen.append((q, p)) or []):
            call()
        return seen[0]

    HOSTILE = "x'; DROP TABLE customer; --"

    def _all(self):
        pat, dig = "%x%", "%8012345678%"
        return {
            "containers": lambda: repository.search_containers(TENANT, self.HOSTILE, pat, 5),
            "shipments": lambda: repository.search_shipments(
                TENANT, self.HOSTILE, pat, dig, 5, customer_id=None, by_name=True, by_phone=True
            ),
            "invoices": lambda: repository.search_invoices(
                TENANT, self.HOSTILE, pat, dig, 5, customer_id=None, by_name=True, by_phone=True
            ),
            "notes": lambda: repository.search_release_notes(
                TENANT, self.HOSTILE, pat, dig, 5, customer_id=None, by_name=True, by_phone=True
            ),
            "customers": lambda: repository.search_customers(TENANT, self.HOSTILE, pat, dig, 5, by_phone=True),
        }

    @pytest.mark.parametrize("name", ["containers", "shipments", "invoices", "notes", "customers"])
    def test_every_query_is_tenant_scoped_and_never_contains_the_text(self, name):
        query, params = self._captured(self._all()[name])
        assert "tenant_id = %(tenant)s" in query
        assert "DROP TABLE" not in query
        assert self.HOSTILE not in query
        assert params["tenant"] == TENANT
        assert params["text"] == self.HOSTILE, "the text goes in as a bound parameter"

    @pytest.mark.parametrize("name", ["shipments", "invoices", "notes"])
    def test_a_customers_lookup_is_pinned_to_their_record_in_sql(self, name):
        pinned = {
            "shipments": lambda: repository.search_shipments(
                TENANT, "x", "%x%", "", 5, customer_id="c-1", by_name=False, by_phone=False
            ),
            "invoices": lambda: repository.search_invoices(
                TENANT, "x", "%x%", "", 5, customer_id="c-1", by_name=False, by_phone=False
            ),
            "notes": lambda: repository.search_release_notes(
                TENANT, "x", "%x%", "", 5, customer_id="c-1", by_name=False, by_phone=False
            ),
        }[name]
        query, params = self._captured(pinned)
        assert ".customer_id = %(customer)s" in query
        assert params["customer"] == "c-1"
        assert "cu.name ILIKE" not in query, "a customer's search does not match other people's names"
        assert "regexp_replace" not in query

    @pytest.mark.parametrize("name", ["shipments", "invoices", "notes"])
    def test_staff_queries_are_not_pinned(self, name):
        query, _ = self._captured(self._all()[name])
        assert "%(customer)s" not in query.replace("customer_id", "")

    def test_phone_matching_is_absent_unless_asked_for(self):
        query, _ = self._captured(
            lambda: repository.search_invoices(TENANT, "x", "%x%", "", 5, customer_id=None, by_name=True, by_phone=False)
        )
        assert "regexp_replace" not in query

    def test_erased_customers_never_match(self):
        query, _ = self._captured(self._all()["customers"])
        assert "anonymised_at IS NULL" in query

    def test_like_is_escaped_in_every_text_comparison(self):
        for name, call in self._all().items():
            query, _ = self._captured(call)
            assert query.count("ILIKE") == query.count("ESCAPE '\\'"), name


class TestHandler:
    @staticmethod
    def _event(q: str | None = "msku", method: str = "GET", path: str = "/v1/search") -> dict:
        return {
            "requestContext": {"requestId": "r1", "http": {"method": method, "path": path}},
            "queryStringParameters": {"q": q} if q is not None else None,
            "headers": {},
        }

    def test_it_returns_the_results(self, repo):
        with patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)):
            resp = handler.lambda_handler(self._event(), None)
        body = json.loads(resp["body"])
        assert resp["statusCode"] == 200
        assert body["data"]["query"] == "msku"
        assert body["data"]["results"]

    def test_a_missing_q_is_just_no_results(self, repo):
        with patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)):
            resp = handler.lambda_handler(self._event(q=None), None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["data"]["results"] == []

    def test_a_platform_admin_gets_403(self, repo):
        with patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.PLATFORM_ADMIN)):
            assert handler.lambda_handler(self._event(), None)["statusCode"] == 403

    def test_an_overlong_query_gets_422(self, repo):
        with patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)):
            assert handler.lambda_handler(self._event(q="x" * 65), None)["statusCode"] == 422

    def test_other_methods_and_paths_are_404(self, repo):
        with patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)):
            assert handler.lambda_handler(self._event(method="POST"), None)["statusCode"] == 404
            assert handler.lambda_handler(self._event(path="/v1/search/other"), None)["statusCode"] == 404

    def test_the_text_searched_for_is_never_logged(self, repo, caplog):
        """It can be a customer's name or phone number."""
        with (
            caplog.at_level(logging.DEBUG),
            patch("services.search.handler.get_tenant_context", return_value=_ctx(UserRole.TENANT_ADMIN)),
        ):
            handler.lambda_handler(self._event(q="Ngozi Okonkwo 08012345678"), None)
        assert "Ngozi" not in caplog.text
        assert "08012345678" not in caplog.text

    def test_it_is_routed_by_the_shared_route_table(self):
        from shared.http_routing import resolve_service

        assert resolve_service("/v1/search") == "search"
