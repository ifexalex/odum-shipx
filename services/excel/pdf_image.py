"""Single-page PDF → PNG rasterizer with strict multi-page guardrail (ENG-5).

Uses ``pypdfium2`` + ``Pillow`` (prebuilt wheels for macOS, Linux x86_64, and AWS Lambda ARM64
with zero system binary dependencies). Any document spanning more than 1 page is rejected
before rasterization is invoked so multi-page Packing Lists and Loading Receipts always fall
back to PDF for readability.
"""

from io import BytesIO

from shared.exceptions import BusinessRuleViolationError

MULTIPAGE_IMAGE_DISABLED_RULE = "MULTIPAGE_IMAGE_DISABLED"
MULTIPAGE_IMAGE_DISABLED_MESSAGE = (
    "Image export is disabled for multi-page documents to preserve readability. Please download and use the PDF version instead."
)


def image_disabled_reason(page_count: int) -> str | None:
    """Return the user-facing guardrail reason when a document exceeds 1 page, else None."""
    if page_count > 1:
        return (
            f"Image export is disabled for multi-page documents ({page_count} pages) "
            "to preserve readability. Please download and use the PDF version instead."
        )
    return None


def render_single_page_png(pdf_bytes: bytes, page_count: int, *, dpi: int = 200) -> BytesIO:
    """Rasterize a single-page PDF to a crisp RGB PNG buffer.

    Raises:
        BusinessRuleViolationError (422 ``MULTIPAGE_IMAGE_DISABLED``): if ``page_count != 1``.
    """
    if page_count != 1:
        raise BusinessRuleViolationError(
            image_disabled_reason(page_count) or MULTIPAGE_IMAGE_DISABLED_MESSAGE,
            rule_id=MULTIPAGE_IMAGE_DISABLED_RULE,
        )

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        actual_pages = len(pdf)
        if actual_pages != 1:
            raise BusinessRuleViolationError(
                image_disabled_reason(actual_pages) or MULTIPAGE_IMAGE_DISABLED_MESSAGE,
                rule_id=MULTIPAGE_IMAGE_DISABLED_RULE,
            )
        page = pdf[0]
        try:
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil().convert("RGB")
            out = BytesIO()
            # compress_level=1 is ~5x faster than optimize=True (zlib level 9) on 0.5 vCPU containers
            # while keeping full 200 DPI visual sharpness.
            pil_image.save(out, format="PNG", compress_level=1)
            out.seek(0)
            return out
        finally:
            page.close()
    finally:
        pdf.close()
