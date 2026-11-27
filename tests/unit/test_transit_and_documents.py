"""Unit tests for ENG-2, ENG-3, ENG-4, and ENG-5:
- ENG-2: in_transit auto-stamping ship_date + dynamic ETA onto container & packing lists, finalized bilingual PL PDF
- ENG-3: same_day vs multiple_days delivery date modes, shared tracking code invariant, per-item loading_date override
- ENG-4: automatic Loading Receipt number (LR-YYYYMMDD-NNN) on approval, modern bilingual Loading Receipt PDF (zh/en)
- ENG-5: single-page PNG rasterization, multi-page 422 guardrail, /documents metadata, WhatsApp image vs PDF share
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from services.excel import pdf_theme
from services.excel import service as excel_service
from services.excel.export_loading_receipt_pdf import generate_loading_receipt_pdf_with_meta
from services.excel.export_packing_list_pdf import generate_packing_list_pdf_with_meta
from services.excel.pdf_image import MULTIPAGE_IMAGE_DISABLED_RULE, render_single_page_png
from services.notification import service as notif_service
from services.packing_list import service as pl_service
from services.packing_list.models import (
    ApprovePackingListRequest,
    CreatePackingListRequest,
    DeliveryDateMode,
    PackingListItemInput,
)
from services.tracking import service as tracking_service
from shared.exceptions import BusinessRuleViolationError
from shared.tenant_context import TenantContext, UserRole


def _ctx(role: UserRole = UserRole.CHINA_OFFICE_STAFF, user_id: str = "user-1") -> TenantContext:
    return TenantContext(tenant_id="tenant-1", user_id=user_id, role=role)


def _brand() -> pdf_theme.Brand:
    return pdf_theme.Brand(
        name="Acme Global Shipping",
        chinese_name="示例国际货运代理有限公司",
        china_warehouse_address="广州市白云区示例路100号物流园1号楼101",
        china_warehouse_phone="+86 13800000000",
        email="ops@acme-shipping.test",
        color="#1c7922",
    )


def _sample_pl(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "pl-1",
        "reference": "PL-20261127-001",
        "loading_receipt_number": "LR-20261127-001",
        "status": "approved",
        "customer_id": "cust-1",
        "customer_name": "Adaeze Okafor",
        "customer_phone": "+2348000000001",
        "customer_whatsapp": "+2348000000001",
        "container_number": "MSKU1234567",
        "container_parcel_number": "PARCEL-101",
        "destination": "Lagos",
        "arrival_warehouse_name": "Lagos Main Warehouse",
        "shipping_line": "MSC",
        "vessel_name": "MSC Lagos",
        "voyage_number": "V042",
        "delivery_date_mode": "same_day",
        "delivery_date": date(2026, 11, 2),
        "loading_date": date(2026, 11, 6),
        "ship_date": date(2026, 11, 10),
        "estimated_arrival_date": date(2026, 12, 25),
        "supplier_name": "Example Fabrics Ltd",
        "supplier_phone": "+86 13800000001",
        "remarks": "Compress bales tightly",
        "created_by_name": "Chidi Okoro",
        "approved_by_name": "Adaeze Obi",
        "created_at": datetime(2026, 11, 2, 10, 0),
        "approved_at": datetime(2026, 11, 6, 14, 30),
        "loaded_at": datetime(2026, 11, 6, 14, 30),
    }
    base.update(overrides)
    return base


def _sample_items(count: int = 2) -> list[dict[str, object]]:
    return [
        {
            "carton_tag": f"XPE-MSKU1234567-{i:03d}",
            "tracking_code": "XPE-TRK-20261102-001",
            "description": f"Air Fryer 空气炸锅 #{i}",
            "package_unit": "carton",
            "quantity": 1,
            "length_cm": Decimal("60"),
            "width_cm": Decimal("40"),
            "height_cm": Decimal("50"),
            "cbm": Decimal("0.120"),
            "weight_dispatch_kg": Decimal("18.5"),
            "weight_actual_kg": Decimal("18.2"),
            "received_date": date(2026, 11, 2) + timedelta(days=i % 3),
            "loading_date": date(2026, 11, 6) if i == 1 else date(2026, 11, 7),
        }
        for i in range(1, count + 1)
    ]


class TestEng2InTransitAutomation:
    def test_in_transit_computes_eta_from_tenant_duration_and_stamps_packing_lists(self) -> None:
        container = {"id": "cont-1", "status": "sealed", "container_number": "MSKU1234567"}
        updated_container = {
            **container,
            "status": "in_transit",
            "ship_date": date(2026, 11, 10),
            "estimated_arrival_date": date(2026, 12, 10),
        }
        with (
            patch.object(tracking_service.repo, "get_container_by_id", return_value=container),
            patch.object(tracking_service, "get_default_transit_days", return_value=30),
            patch.object(tracking_service, "tenant_transaction") as mock_tx,
            patch.object(tracking_service.repo, "update_container_status", return_value=updated_container) as mock_update,
            patch.object(tracking_service.repo, "stamp_packing_lists_transit_dates", return_value=3) as mock_stamp,
            patch.object(tracking_service.repo, "insert_container_event"),
            patch.object(tracking_service.repo, "bulk_insert_tracking_events"),
            patch.object(tracking_service.repo, "bulk_update_tracking_status"),
            patch.object(tracking_service.repo, "get_customers_for_container", return_value=[]),
            patch.object(tracking_service, "publish_event"),
            patch.object(tracking_service, "fire_tenant_webhook"),
            patch.object(tracking_service, "log_audit"),
        ):
            mock_tx.return_value.__enter__ = MagicMock(return_value=None)
            mock_tx.return_value.__exit__ = MagicMock(return_value=False)

            result = tracking_service.update_container_status(
                tenant_id="tenant-1",
                container_id="cont-1",
                new_status="in_transit",
                extra={"ship_date": "2026-11-10"},
                actor_id="user-1",
                ctx=_ctx(),
            )

        assert result["estimated_arrival_date"] == date(2026, 12, 10)
        extra_passed = mock_update.call_args[0][3]
        assert extra_passed["ship_date"] == date(2026, 11, 10)
        assert extra_passed["estimated_arrival_date"] == date(2026, 12, 10)
        mock_stamp.assert_called_once_with("tenant-1", "cont-1", date(2026, 11, 10), date(2026, 12, 10))


class TestEng3DeliveryDateModesAndTracking:
    def test_multiple_days_mode_rejects_item_loading_before_delivery(self) -> None:
        with pytest.raises(PydanticValidationError, match="loading date cannot be before its delivery date"):
            CreatePackingListRequest(
                container_id="cont-1",
                customer_id="cust-1",
                delivery_date_mode=DeliveryDateMode.multiple_days,
                loading_date=date(2026, 11, 4),
                items=[
                    PackingListItemInput(
                        description="Shoes",
                        received_date=date(2026, 11, 5),
                    )
                ],
            )

    def test_multiple_days_mode_allows_per_item_loading_date_override(self) -> None:
        req = CreatePackingListRequest(
            container_id="cont-1",
            customer_id="cust-1",
            delivery_date_mode=DeliveryDateMode.multiple_days,
            loading_date=date(2026, 11, 4),
            items=[
                PackingListItemInput(description="Fabrics", received_date=date(2026, 11, 2)),
                PackingListItemInput(description="Shoes", received_date=date(2026, 11, 5), loading_date=date(2026, 11, 6)),
            ],
        )
        assert req.items[1].loading_date == date(2026, 11, 6)

    def test_shared_tracking_code_across_multiple_delivery_dates_on_same_loading_date(self) -> None:
        items = [
            PackingListItemInput(description="Item A", received_date=date(2026, 11, 21)),
            PackingListItemInput(description="Item B", received_date=date(2026, 11, 22)),
            PackingListItemInput(description="Item C", received_date=date(2026, 11, 23)),
        ]
        with (
            patch.object(pl_service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(pl_service.repo, "get_next_tracking_sequence", return_value=1),
        ):
            rows = pl_service._build_item_rows(
                tenant_id="tenant-1",
                pl_id="pl-1",
                items=items,
                container_id="cont-1",
                customer_id="cust-1",
                tenant_short="XPE",
                container_number="MSKU123",
                carton_seq_start=1,
                min_cbm=Decimal("0.1"),
                delivery_date_mode="multiple_days",
                header_delivery_date=None,
                header_loading_date=date(2026, 11, 24),
            )

        assert len(rows) == 3
        # All three share ONE tracking code centered on the 24th loading date, with distinct tags
        assert {r["tracking_code"] for r in rows} == {"XPE-TRK-20261124-001"}
        assert [r["carton_tag"] for r in rows] == ["XPE-MSKU123-001", "XPE-MSKU123-002", "XPE-MSKU123-003"]
        assert [r["received_date"] for r in rows] == [date(2026, 11, 21), date(2026, 11, 22), date(2026, 11, 23)]

    def test_per_item_different_loading_date_gets_own_loading_date_tracking_code(self) -> None:
        items = [
            PackingListItemInput(description="Fabrics", received_date=date(2026, 11, 2)),
            PackingListItemInput(description="Shoes", received_date=date(2026, 11, 5), loading_date=date(2026, 11, 8)),
        ]
        with (
            patch.object(pl_service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(pl_service.repo, "get_next_tracking_sequence", return_value=1),
        ):
            rows = pl_service._build_item_rows(
                tenant_id="tenant-1",
                pl_id="pl-1",
                items=items,
                container_id="cont-1",
                customer_id="cust-1",
                tenant_short="XPE",
                container_number="MSKU123",
                carton_seq_start=1,
                min_cbm=Decimal("0.1"),
                delivery_date_mode="multiple_days",
                header_delivery_date=None,
                header_loading_date=date(2026, 11, 6),
            )

        assert rows[0]["tracking_code"] == "XPE-TRK-20261106-001"
        assert rows[1]["tracking_code"] == "XPE-TRK-20261108-001"
        assert rows[1]["loading_date"] == date(2026, 11, 8)

    def test_same_day_mode_propagates_header_delivery_date_to_all_items(self) -> None:
        items = [PackingListItemInput(description="Item A"), PackingListItemInput(description="Item B")]
        with (
            patch.object(pl_service.repo, "get_existing_tracking_code", return_value=None),
            patch.object(pl_service.repo, "get_next_tracking_sequence", return_value=2),
        ):
            rows = pl_service._build_item_rows(
                tenant_id="tenant-1",
                pl_id="pl-1",
                items=items,
                container_id="cont-1",
                customer_id="cust-1",
                tenant_short="XPE",
                container_number="MSKU123",
                carton_seq_start=1,
                min_cbm=Decimal("0.1"),
                delivery_date_mode="same_day",
                header_delivery_date=date(2026, 11, 3),
            )
        assert all(r["received_date"] == date(2026, 11, 3) for r in rows)
        assert rows[0]["tracking_code"] == rows[1]["tracking_code"] == "XPE-TRK-20261103-002"


class TestEng4LoadingReceiptApprovalAndBilingualPdfs:
    def test_approve_packing_list_stamps_loading_receipt_number(self) -> None:
        pl = {
            "id": "pl-1",
            "container_id": "cont-1",
            "customer_id": "cust-1",
            "status": "pending_approval",
            "created_by": "creator-1",
            "container_status": "loading",
            "reference": "PL-20261127-001",
        }
        updated_pl = {**pl, "status": "approved", "approved_by": "approver-1"}
        stamped_pl = {**updated_pl, "loading_receipt_number": "LR-20261127-001", "loaded_at": datetime(2026, 11, 27, 12, 0)}

        with (
            patch.object(pl_service.repo, "get_packing_list_by_id", return_value=pl),
            patch.object(pl_service, "tenant_transaction") as mock_tx,
            patch.object(pl_service.repo, "approve_packing_list_row", return_value=updated_pl),
            patch.object(pl_service.repo, "get_manifest_by_container", return_value={"id": "man-1"}),
            patch.object(pl_service.repo, "link_manifest"),
            patch.object(pl_service.repo, "recalculate_manifest_totals"),
            patch.object(pl_service.repo, "reset_manifest_verification_if_verified"),
            patch.object(pl_service.repo, "get_next_loading_receipt_number", return_value="LR-20261127-001"),
            patch.object(pl_service.repo, "stamp_loading_receipt", return_value=stamped_pl) as mock_stamp,
            patch.object(pl_service.repo, "get_items_by_packing_list", return_value=[]),
            patch.object(pl_service, "_emit_approval_notifications"),
            patch.object(pl_service, "log_audit"),
        ):
            mock_tx.return_value.__enter__ = MagicMock(return_value=None)
            mock_tx.return_value.__exit__ = MagicMock(return_value=False)

            res = pl_service.approve_packing_list(
                tenant_id="tenant-1",
                pl_id="pl-1",
                req=ApprovePackingListRequest(),
                actor_id="approver-1",
                ctx=_ctx(user_id="approver-1"),
            )

        mock_stamp.assert_called_once_with("tenant-1", "pl-1", "LR-20261127-001")
        assert res["loading_receipt_number"] == "LR-20261127-001"

    def test_loading_receipt_and_packing_list_pdfs_render_bilingually_with_no_missing_glyphs(self) -> None:
        brand = _brand()
        pl = _sample_pl()
        items = _sample_items(2)

        for lang in ("zh", "en"):
            lr = generate_loading_receipt_pdf_with_meta(brand, pl, items, lang=lang)  # type: ignore[arg-type]
            assert lr.buf.getvalue().startswith(b"%PDF")
            assert lr.page_count == 1

            pl_pdf = generate_packing_list_pdf_with_meta(brand, pl, items, lang=lang)  # type: ignore[arg-type]
            assert pl_pdf.buf.getvalue().startswith(b"%PDF")
            assert pl_pdf.page_count == 1

        # Verify all Chinese & English template strings are covered by embedded fonts
        from services.excel.export_loading_receipt_pdf import _STRINGS as LR_STRINGS
        from services.excel.export_packing_list_pdf import _STRINGS as PL_STRINGS

        for lang_dict in (*LR_STRINGS.values(), *PL_STRINGS.values()):
            for val in lang_dict.values():
                text = "\n".join(val) if isinstance(val, list) else str(val)
                assert pdf_theme.missing_glyphs(text) == set()

    def test_destination_warehouse_formats_country_city_name_and_address(self) -> None:
        from services.excel.export_packing_list_pdf import format_destination_warehouse

        headline, address = format_destination_warehouse(
            {
                "destination": "Nigeria",
                "arrival_warehouse_country": "Nigeria",
                "arrival_warehouse_state": "Lagos",
                "arrival_warehouse_city": "Lagos",
                "arrival_warehouse_name": "Trade Fair Warehouse",
                "arrival_warehouse_address": "Block C, Trade Fair Complex",
            }
        )
        assert headline == "Nigeria · Lagos — Trade Fair Warehouse"
        assert address == "Block C, Trade Fair Complex"
        assert pdf_theme.initials("示例国际货运代理有限公司 · Acme Global Shipping") == "AG"

    def test_loading_receipt_executive_banner_layout_contains_key_sections_bilingually(self) -> None:
        from io import BytesIO

        from pypdf import PdfReader

        brand = _brand()
        pl = _sample_pl(
            destination="Nigeria",
            arrival_warehouse_country="Nigeria",
            arrival_warehouse_state="Lagos",
            arrival_warehouse_city="Lagos",
            arrival_warehouse_name="Trade Fair Warehouse",
            arrival_warehouse_address="Block C, Trade Fair Complex, Lagos",
            arrival_warehouse_phone="+234 800 111 2222",
            delivery_date_mode="multiple_days",
        )
        items = _sample_items(2)

        for lang, expected_snippets in (
            (
                "zh",
                (
                    "入仓装柜收据",
                    "NO. LR-20261127-001",
                    "Nigeria · Lagos — Trade Fair Warehouse",
                    "Block C, Trade Fair Complex, Lagos",
                    "PL-20261127-001",
                    "MSKU1234567 / PARCEL-101",
                    "合计 Total",
                    "Compress bales tightly",
                ),
            ),
            (
                "en",
                (
                    "LOADING RECEIPT",
                    "NO. LR-20261127-001",
                    "DESTINATION WAREHOUSE",
                    "Nigeria · Lagos — Trade Fair Warehouse",
                    "Block C, Trade Fair Complex, Lagos",
                    "PL-20261127-001",
                    "MSKU1234567 / PARCEL-101",
                    "Total",
                    "Compress bales tightly",
                ),
            ),
        ):
            rendered = generate_loading_receipt_pdf_with_meta(brand, pl, items, lang=lang)  # type: ignore[arg-type]
            assert rendered.page_count == 1
            reader = PdfReader(BytesIO(rendered.buf.getvalue()))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            for snippet in expected_snippets:
                assert snippet in text, f"{snippet!r} missing from {lang} loading receipt"
            # Verify embedded Noto fonts only (no Helvetica / Times)
            fonts = {
                str(font.get_object().get("/BaseFont"))
                for page in reader.pages
                for font in ((page.get("/Resources") or {}).get("/Font") or {}).values()
            }
            assert fonts and all("Noto" in name for name in fonts)

        # Also verify clean rendering without optional remarks or Chinese brand name
        plain_brand = pdf_theme.Brand(name="Acme Global Shipping", color="#1c7922")
        no_remarks_pl = _sample_pl(remarks=None)
        rendered_plain = generate_loading_receipt_pdf_with_meta(plain_brand, no_remarks_pl, items, lang="en")
        assert rendered_plain.page_count == 1


class TestEng5DualFormatGuardrailAndWhatsApp:
    def test_single_page_pdf_rasterizes_to_valid_png(self) -> None:
        rendered = generate_loading_receipt_pdf_with_meta(_brand(), _sample_pl(), _sample_items(2), lang="zh")
        assert rendered.page_count == 1
        png_buf = render_single_page_png(rendered.buf.getvalue(), rendered.page_count)
        assert png_buf.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    def test_multipage_packing_list_and_loading_receipt_reject_image_export(self) -> None:
        many_items = _sample_items(45)
        pl_rendered = generate_packing_list_pdf_with_meta(_brand(), _sample_pl(), many_items, lang="en")
        assert pl_rendered.page_count > 1
        with pytest.raises(BusinessRuleViolationError) as exc_info:
            render_single_page_png(pl_rendered.buf.getvalue(), pl_rendered.page_count)
        assert exc_info.value.rule_id == MULTIPAGE_IMAGE_DISABLED_RULE

        lr_rendered = generate_loading_receipt_pdf_with_meta(_brand(), _sample_pl(), many_items, lang="zh")
        assert lr_rendered.page_count > 1
        with pytest.raises(BusinessRuleViolationError) as lr_exc:
            render_single_page_png(lr_rendered.buf.getvalue(), lr_rendered.page_count)
        assert lr_exc.value.rule_id == MULTIPAGE_IMAGE_DISABLED_RULE

    def test_whatsapp_share_sends_image_for_1_page_and_pdf_for_multipage(self) -> None:
        pl = _sample_pl()
        one_page_items = _sample_items(2)
        multi_page_items = _sample_items(45)

        fake_storage = MagicMock()
        fake_storage.presigned_get_url.return_value = "https://cdn.shipx.test/doc"

        with (
            patch.object(excel_service.repo, "get_packing_list_for_export", return_value=pl),
            patch.object(excel_service.repo, "get_tenant_branding", return_value={"company_name": "Xperts"}),
            patch.object(excel_service, "get_storage_provider", return_value=fake_storage),
            patch.object(excel_service, "log_audit"),
            patch.object(notif_service, "send_whatsapp", return_value="wamid.123") as mock_wa,
        ):
            with patch.object(excel_service.repo, "get_items_for_packing_list", return_value=one_page_items):
                res_img = excel_service.share_packing_list_document_whatsapp(
                    "tenant-1", "pl-1", "loading_receipt", lang="zh", actor_id="u1", actor_role="china_office_staff"
                )
            assert res_img["format_sent"] == "image"
            assert res_img["page_count"] == 1
            assert res_img["notice"] is None
            wa_components = mock_wa.call_args.kwargs["components"]
            assert wa_components[0]["type"] == "header"
            assert wa_components[0]["parameters"][0]["type"] == "image"

            with patch.object(excel_service.repo, "get_items_for_packing_list", return_value=multi_page_items):
                res_pdf = excel_service.share_packing_list_document_whatsapp(
                    "tenant-1", "pl-1", "packing_list", lang="en", actor_id="u1", actor_role="china_office_staff"
                )
            assert res_pdf["format_sent"] == "pdf"
            assert res_pdf["page_count"] > 1
            assert res_pdf["notice"] is not None
            wa_components_pdf = mock_wa.call_args.kwargs["components"]
            assert wa_components_pdf[0]["type"] == "header"
            assert wa_components_pdf[0]["parameters"][0]["type"] == "document"

    def test_unapproved_packing_list_blocks_pdf_image_and_whatsapp_exports(self) -> None:
        pending_pl = _sample_pl(status="pending_approval", loading_receipt_number=None)
        with (
            patch.object(excel_service.repo, "get_packing_list_for_export", return_value=pending_pl),
            patch.object(excel_service.repo, "get_items_for_packing_list", return_value=_sample_items(1)),
            patch.object(excel_service.repo, "get_tenant_branding", return_value={"company_name": "Acme"}),
        ):
            docs = excel_service.get_packing_list_documents("tenant-1", "pl-1")
            assert docs["loading_receipt"]["available"] is False
            assert docs["packing_list"]["available"] is False
            assert docs["packing_list"]["image_eligible"] is False

            with pytest.raises(BusinessRuleViolationError) as pdf_exc:
                excel_service.export_packing_list_pdf("tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff")
            assert pdf_exc.value.rule_id == "PACKING_LIST_NOT_APPROVED"

            with pytest.raises(BusinessRuleViolationError) as img_exc:
                excel_service.export_packing_list_image("tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff")
            assert img_exc.value.rule_id == "PACKING_LIST_NOT_APPROVED"

            with pytest.raises(BusinessRuleViolationError) as wa_exc:
                excel_service.share_packing_list_document_whatsapp(
                    "tenant-1", "pl-1", "packing_list", actor_id="u1", actor_role="china_office_staff"
                )
            assert wa_exc.value.rule_id == "PACKING_LIST_NOT_APPROVED"

    def test_document_logo_and_blob_fingerprint_caches_skip_repeat_renders(self) -> None:
        excel_service._clear_document_caches()
        pl = _sample_pl()
        items = _sample_items(1)
        branding = {"company_name": "Acme", "logo_key": "tenant-1/branding/logo/logo.png"}

        stored: dict[str, bytes] = {}
        fake_storage = MagicMock()
        fake_storage.get_object.return_value = b"\x89PNG\r\n\x1a\nfake"
        fake_storage.object_size.side_effect = lambda key: len(stored[key]) if key in stored else None
        fake_storage.put_object.side_effect = lambda key, body, **_: stored.__setitem__(key, body)
        fake_storage.presigned_get_url.side_effect = lambda key, **_: f"https://cdn.shipx.test/{key}"

        with (
            patch.object(excel_service.repo, "get_packing_list_for_export", return_value=pl),
            patch.object(excel_service.repo, "get_items_for_packing_list", return_value=items),
            patch.object(excel_service.repo, "get_tenant_branding", return_value=branding),
            patch.object(excel_service, "get_storage_provider", return_value=fake_storage),
            patch.object(excel_service, "log_audit"),
        ):
            # First PDF + Image exports render and populate both logo and blob caches
            first_pdf = excel_service.export_loading_receipt_pdf(
                "tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff", lang="zh"
            )
            first_png = excel_service.export_loading_receipt_image(
                "tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff", lang="zh"
            )
            assert fake_storage.get_object.call_count == 1  # logo downloaded once, reused for PNG
            assert fake_storage.put_object.call_count == 2  # 1 PDF + 1 PNG cached

            # Second PDF + Image exports hit the fingerprinted blob cache (no re-render, no put_object)
            with (
                patch.object(excel_service, "generate_loading_receipt_pdf_with_meta") as mock_gen,
                patch.object(excel_service, "render_single_page_png") as mock_png,
            ):
                second_pdf = excel_service.export_loading_receipt_pdf(
                    "tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff", lang="zh"
                )
                second_png = excel_service.export_loading_receipt_image(
                    "tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff", lang="zh"
                )
                mock_gen.assert_not_called()
                mock_png.assert_not_called()

            assert second_pdf["download_url"] == first_pdf["download_url"]
            assert second_png["download_url"] == first_png["download_url"]
            assert fake_storage.put_object.call_count == 2

            # Changing document data (e.g. remarks) invalidates the fingerprint and creates a new key
            updated_pl = _sample_pl(remarks="Updated packing note")
            with patch.object(excel_service.repo, "get_packing_list_for_export", return_value=updated_pl):
                third_pdf = excel_service.export_loading_receipt_pdf(
                    "tenant-1", "pl-1", actor_id="u1", actor_role="china_office_staff", lang="zh"
                )
            assert third_pdf["download_url"] != first_pdf["download_url"]
            assert fake_storage.put_object.call_count == 3
