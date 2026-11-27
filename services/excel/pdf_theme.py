"""The one theme every generated PDF is built on (audit FD-41).

Each document module (invoice, packing list, release note, receipt, manifest) describes its content; this module
decides how it looks and how its values read, so the documents agree with each other and with the app:

* **Fonts.** Noto Sans (with the naira sign) and a Noto Sans SC subset for Chinese, embedded from ``shared/fonts``.
  reportlab has no per-glyph fallback, so ``markup`` puts every run of characters the Latin font lacks into the Chinese
  font. ``missing_glyphs`` names any character neither font can draw; the template tests assert there are none.
* **Colours and type** from the design tokens (``frontend/src/design/tokens.css``), scaled for print. The tenant's
  brand colour accents rules and the title; without one it is the app's green, never the old blue.
* **Values** formatted as the app formats them (``frontend/src/lib/format.ts``, FD-17): ``₦174,375``, CBM to three
  decimals, kilograms to one, dates as "10 Nov 2026" and times in Lagos as "10 Nov 2026, 11:04 WAT".
* **Pages.** The brand block (logo or initials, name, tagline, address, phone, email) opens the first page with the
  document's title and reference; later pages carry a running header; every page ends with the tenant's document
  footer and "Page n of N". Tables wrap their cells and repeat their header row on each page.
* **Safety.** Every value goes through ``markup``, which escapes ``&``, ``<`` and ``>``: a description typed as
  "<b>" or "A & B" is printed, not interpreted as reportlab markup (it used to break the PDF).

Document title and author are set on every PDF (they read "(anonymous)" before).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, Image, PageTemplate, Paragraph, Spacer, Table
from reportlab.platypus import TableStyle as _ReportlabTableStyle

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

FONT_DIR = Path(__file__).resolve().parents[2] / "shared" / "fonts"
BODY_FONT = "ShipXSans"
BOLD_FONT = "ShipXSans-Bold"
CJK_FONT = "ShipXSansSC"


@cache
def register_fonts() -> None:
    """Register the embedded fonts with reportlab, once per process."""
    pdfmetrics.registerFont(TTFont(BODY_FONT, str(FONT_DIR / "NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD_FONT, str(FONT_DIR / "NotoSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(CJK_FONT, str(FONT_DIR / "NotoSansSC-Regular.ttf")))
    pdfmetrics.registerFontFamily(BODY_FONT, normal=BODY_FONT, bold=BOLD_FONT, italic=BODY_FONT, boldItalic=BOLD_FONT)
    pdfmetrics.registerFontFamily(CJK_FONT, normal=CJK_FONT, bold=CJK_FONT, italic=CJK_FONT, boldItalic=CJK_FONT)


@cache
def _covered(font_name: str) -> frozenset[int]:
    register_fonts()
    return frozenset(pdfmetrics.getFont(font_name).face.charToGlyph)


def _in_body(ch: str) -> bool:
    return ord(ch) in _covered(BODY_FONT) or ch in "\n\t"


def missing_glyphs(text: str) -> set[str]:
    """Characters in ``text`` that neither embedded font can draw (spaces and line breaks aside)."""
    return {ch for ch in text if not ch.isspace() and not _in_body(ch) and ord(ch) not in _covered(CJK_FONT)}


def markup(value: object) -> str:
    """``value`` as safe reportlab paragraph markup: escaped, with Chinese runs set in the Chinese font."""
    text = "" if value is None else str(value)
    out: list[str] = []
    run: list[str] = []
    for ch in text:
        if _in_body(ch):
            if run:
                out.append(f'<font name="{CJK_FONT}">{escape("".join(run))}</font>')
                run = []
            out.append("<br/>" if ch == "\n" else escape(ch))
        else:
            run.append(ch)
    if run:
        out.append(f'<font name="{CJK_FONT}">{escape("".join(run))}</font>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Colours and type (design tokens, light theme)
# ---------------------------------------------------------------------------

INK = colors.HexColor("#1f2329")
INK_2 = colors.HexColor("#374151")
INK_3 = colors.HexColor("#4b5563")
LINE = colors.HexColor("#d1d5db")
LINE_SOFT = colors.HexColor("#e5e7eb")
SURFACE_MUTED = colors.HexColor("#f9fafb")
SUCCESS = colors.HexColor("#15803d")
WARNING = colors.HexColor("#b45309")
ERROR_HEX = "#c81e1e"
ERROR = colors.HexColor(ERROR_HEX)
#: The app's primary green (`--color-primary`); the PDFs used to default to blue.
DEFAULT_BRAND = "#1c7922"

#: The token type scale (--text-xs … --text-2xl, 12–24 px) scaled to print points.
TYPE = {"xs": 7.5, "sm": 8.5, "md": 9.5, "lg": 11.0, "xl": 13.5, "2xl": 17.0}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def brand_color(value: object) -> colors.Color:
    """The tenant's colour when it is a plain ``#rrggbb``, else the app's green."""
    return colors.HexColor(value if isinstance(value, str) and _HEX.match(value) else DEFAULT_BRAND)


@cache
def styles() -> dict[str, ParagraphStyle]:
    """The paragraph styles every template uses."""
    register_fonts()

    def style(
        name: str, size: str, *, font: str = BODY_FONT, color: Any = INK, align: int = TA_LEFT, leading: float = 1.35
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name, fontName=font, fontSize=TYPE[size], leading=TYPE[size] * leading, textColor=color, alignment=align
        )

    return {
        "title": style("title", "2xl", font=BOLD_FONT, align=TA_RIGHT, leading=1.15),
        "reference": style("reference", "md", font=BOLD_FONT, align=TA_RIGHT),
        "figure": style("figure", "2xl", font=BOLD_FONT, leading=1.2),
        "brand_name": style("brand_name", "xl", font=BOLD_FONT, leading=1.2),
        "brand_line": style("brand_line", "sm", color=INK_3),
        "heading": style("heading", "lg", font=BOLD_FONT),
        "body": style("body", "md"),
        "body_bold": style("body_bold", "md", font=BOLD_FONT),
        "small": style("small", "sm", color=INK_3),
        "label": style("label", "xs", color=INK_3),
        "value": style("value", "md", font=BOLD_FONT),
        "fact_label": style("fact_label", "xs", color=INK_3, align=TA_RIGHT),
        "fact_value": style("fact_value", "sm", font=BOLD_FONT, align=TA_RIGHT),
        "cell": style("cell", "sm"),
        "cell_right": style("cell_right", "sm", align=TA_RIGHT),
        "cell_bold": style("cell_bold", "sm", font=BOLD_FONT),
        "cell_bold_right": style("cell_bold_right", "sm", font=BOLD_FONT, align=TA_RIGHT),
        "head": style("head", "xs", font=BOLD_FONT, color=INK_2),
        "head_right": style("head_right", "xs", font=BOLD_FONT, color=INK_2, align=TA_RIGHT),
        "footer": style("footer", "xs", color=INK_3),
    }


def para(value: object, style_name: str = "body") -> Paragraph:
    """A paragraph of ``value``, escaped and font-fallback aware."""
    return Paragraph(markup(value), styles()[style_name])


# ---------------------------------------------------------------------------
# Values, formatted as the app formats them
# ---------------------------------------------------------------------------

LAGOS = ZoneInfo("Africa/Lagos")
MISSING = "—"


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _fixed(n: Decimal, places: int) -> str:
    """``n`` to ``places`` decimals, rounding half up as the app's ``Intl.NumberFormat`` does (0.0305 is 0.031)."""
    return f"{n.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):,.{places}f}"


def amount(value: object) -> str:
    """Money without a symbol: ``174,375``, or ``174,375.50`` with kobo."""
    n = _decimal(value)
    if n is None:
        return MISSING
    rounded = n.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return _fixed(rounded, 0 if rounded == rounded.to_integral_value() else 2)


def money(value: object) -> str:
    """Naira: ``₦174,375``, ``-₦5,000``."""
    n = _decimal(value)
    if n is None:
        return MISSING
    return f"{'-' if n < 0 else ''}₦{amount(abs(n))}"


def usd(value: object) -> str:
    """US dollars, always with cents: ``$112.50``."""
    n = _decimal(value)
    return MISSING if n is None else f"${_fixed(n, 2)}"


def cbm(value: object) -> str:
    """Cubic metres to three decimals: ``2.500``."""
    n = _decimal(value)
    return MISSING if n is None else _fixed(n, 3)


def kg(value: object) -> str:
    """Kilograms to one decimal: ``1,240.5``."""
    n = _decimal(value)
    return MISSING if n is None else _fixed(n, 1)


def measure(value: object) -> str:
    """A length in centimetres: up to one decimal, no trailing zero ("35.5", "60")."""
    n = _decimal(value)
    if n is None:
        return MISSING
    rounded = n.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return _fixed(rounded, 0 if rounded == rounded.to_integral_value() else 1)


def count(value: object) -> str:
    """A whole number with grouping."""
    n = _decimal(value)
    return MISSING if n is None else _fixed(n, 0)


def _moment(value: object) -> datetime | date | None:
    if isinstance(value, datetime | date):
        return value
    if isinstance(value, str) and value:
        try:
            return (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                if "T" in value or " " in value
                else date.fromisoformat(value[:10])
            )
        except ValueError:
            return None
    return None


def day(value: object) -> str:
    """A date as "10 Nov 2026"; a timestamp is taken at its Lagos date."""
    moment = _moment(value)
    if moment is None:
        return MISSING
    if isinstance(moment, datetime):
        moment = (moment if moment.tzinfo else moment.replace(tzinfo=ZoneInfo("UTC"))).astimezone(LAGOS).date()
    return f"{moment.day} {moment.strftime('%b %Y')}"


def moment(value: object) -> str:
    """A timestamp as "10 Nov 2026, 11:04 WAT" in Lagos time; a plain date as a date."""
    when = _moment(value)
    if not isinstance(when, datetime):
        return day(value)
    local = (when if when.tzinfo else when.replace(tzinfo=ZoneInfo("UTC"))).astimezone(LAGOS)
    return f"{local.day} {local.strftime('%b %Y, %H:%M')} WAT"


def now() -> datetime:
    """The current moment, timezone-aware (never a naive ``utcnow``)."""
    return datetime.now(LAGOS)


def humanise(code: object) -> str:
    """A status code as words: ``released_with_outstanding`` → "Released with outstanding"."""
    text = str(code or "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else MISSING


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Brand:
    """Who a document is from: everything Company settings holds, plus the logo's bytes when there is one."""

    name: str
    tagline: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    footer: str = ""
    color: str = DEFAULT_BRAND
    logo: bytes | None = None
    chinese_name: str = ""
    china_warehouse_address: str = ""
    china_warehouse_phone: str = ""

    @classmethod
    def from_branding(cls, branding: dict[str, Any], logo: bytes | None = None) -> "Brand":
        """Build from ``tenant.branding_config`` (with ``company_name`` filled in by the repository)."""

        def text(key: str) -> str:
            value = branding.get(key)
            return value.strip() if isinstance(value, str) else ""

        return cls(
            name=text("display_name") or text("company_display_name") or text("company_name") or "ShipX",
            tagline=text("tagline"),
            address=text("warehouse_address"),
            phone=text("pickup_phone"),
            email=text("support_email"),
            footer=text("document_footer"),
            color=text("primary_color") if _HEX.match(text("primary_color")) else DEFAULT_BRAND,
            logo=logo,
            chinese_name=text("chinese_display_name"),
            china_warehouse_address=text("china_warehouse_address"),
            china_warehouse_phone=text("china_warehouse_phone"),
        )


def initials(name: str) -> str:
    """Up to two initials, as the app's logo tile shows them."""
    words = [w for w in name.split() if w]
    return "".join(w[0].upper() for w in words[:2]) or "?"


class InitialsTile(Flowable):  # type: ignore[misc]  # reportlab ships no type hints
    """The initials on the brand colour, standing in for a logo (as in the app)."""

    def __init__(self, brand: Brand, size: float) -> None:
        super().__init__()
        self.brand = brand
        self.size = size
        self.width = self.height = size

    def draw(self) -> None:
        canvas = self.canv
        canvas.setFillColor(brand_color(self.brand.color))
        canvas.roundRect(0, 0, self.size, self.size, self.size * 0.18, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont(BOLD_FONT, self.size * 0.38)
        canvas.drawCentredString(self.size / 2, self.size * 0.34, initials(self.brand.name))


def logo_mark(brand: Brand, size: float = 1.7 * cm) -> Flowable:
    """The uploaded logo fitted into a square, or the initials tile when there is none or it cannot be read."""
    if brand.logo:
        try:
            image = Image(BytesIO(brand.logo))
            scale = min(size / image.imageWidth, size / image.imageHeight)
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            return image
        except OSError:
            # An unreadable image (corrupt, or a type Pillow lacks) must not stop the document: fall back to initials.
            pass
    return InitialsTile(brand, size)


def TableStyle(commands: Sequence[tuple[Any, ...]]) -> _ReportlabTableStyle:  # noqa: N802 — stands in for reportlab's
    """A table style in the embedded font: reportlab draws a table's plain-string cells (even an empty placeholder) in
    Helvetica unless told otherwise, which put an unembedded font into every document."""
    return _ReportlabTableStyle([("FONTNAME", (0, 0), (-1, -1), BODY_FONT), *commands])


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 1.6 * cm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
FOOTER_HEIGHT = 1.6 * cm


def brand_block(brand: Brand, title: str, reference: str, facts: Sequence[tuple[str, str]] = ()) -> Table:
    """The top of the first page: who it is from (left) and what it is (right)."""
    contact = " · ".join(p for p in (brand.phone, brand.email) if p)
    left_lines: list[Flowable] = [para(brand.name, "brand_name")]
    for line in (brand.tagline, brand.address, contact):
        if line:
            left_lines.append(para(line, "brand_line"))
    right: list[Flowable] = [para(title.upper(), "title"), para(reference, "reference")]
    for label, value in facts:
        right.append(Spacer(1, 2))
        right.append(para(label, "fact_label"))
        right.append(para(value, "fact_value"))
    mark = logo_mark(brand)
    table = Table(
        [[mark, left_lines, right]],
        colWidths=[2.0 * cm, CONTENT_WIDTH * 0.55 - 2.0 * cm, CONTENT_WIDTH * 0.45],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, 0), 1.5, brand_color(brand.color)),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ]
        )
    )
    return table


def section(title: str) -> list[Flowable]:
    """A section heading with space above."""
    return [Spacer(1, 0.45 * cm), para(title, "heading"), Spacer(1, 0.15 * cm)]


def facts_grid(pairs: Sequence[tuple[str, str]], columns: int = 3) -> Table:
    """Label-over-value facts in a grid (customer, container, dates ...)."""
    cells: list[Any] = [[para(label, "label"), para(value, "value")] for label, value in pairs]
    rows: list[list[Any]] = [cells[i : i + columns] for i in range(0, len(cells), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1] = rows[-1] + [""] * (columns - len(rows[-1]))
    table = Table(rows or [[""]], colWidths=[CONTENT_WIDTH / columns] * columns)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


@dataclass(frozen=True)
class Column:
    """One table column: its title, share of the width, and alignment (numbers right)."""

    title: str
    width: float
    align: Literal["left", "right"] = "left"


@dataclass
class DataTable:
    """A table whose cells wrap and whose header row repeats on every page.

    ``rows`` hold plain values (escaped here). ``totals`` is an optional last row in bold, on a tinted band.
    """

    columns: Sequence[Column]
    rows: Sequence[Sequence[object]]
    totals: Sequence[object] | None = None
    brand: str = DEFAULT_BRAND
    zebra: bool = True
    extra_style: list[tuple[Any, ...]] = field(default_factory=list)

    def build(self) -> Table:
        """The reportlab table."""
        total_share = sum(c.width for c in self.columns)
        widths = [CONTENT_WIDTH * c.width / total_share for c in self.columns]

        def cell(value: object, column: Column, bold: bool = False) -> Paragraph:
            name = ("cell_bold" if bold else "cell") + ("_right" if column.align == "right" else "")
            return para(value, name)

        data: list[list[Any]] = [[para(c.title, "head_right" if c.align == "right" else "head") for c in self.columns]]
        data += [[cell(v, c) for v, c in zip(row, self.columns, strict=True)] for row in self.rows]
        if self.totals is not None:
            data.append([cell(v, c, bold=True) for v, c in zip(self.totals, self.columns, strict=True)])
        table = Table(data, colWidths=widths, repeatRows=1)
        commands: list[tuple[Any, ...]] = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, brand_color(self.brand)),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE_SOFT),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        last_body = len(data) - (2 if self.totals is not None else 1)
        if self.zebra and last_body >= 1:
            commands.append(("ROWBACKGROUNDS", (0, 1), (-1, last_body), [colors.white, SURFACE_MUTED]))
        if self.totals is not None:
            commands += [("BACKGROUND", (0, -1), (-1, -1), SURFACE_MUTED), ("LINEABOVE", (0, -1), (-1, -1), 0.8, LINE)]
        table.setStyle(TableStyle(commands + self.extra_style))
        return table


def summary_lines(lines: Sequence[tuple[str, str]], emphasise: Sequence[str] = (), alarm: Sequence[str] = ()) -> Table:
    """Right-aligned label/amount lines (Total, Paid, Outstanding). ``alarm`` labels print red, as owed money does in the app."""
    rows = []
    commands: list[tuple[Any, ...]] = [
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i, (label, value) in enumerate(lines):
        bold = label in emphasise or label in alarm
        value_style = "cell_bold_right" if bold else "cell_right"
        value_para = para(value, value_style)
        if label in alarm:
            value_para = Paragraph(f'<font color="{ERROR_HEX}">{markup(value)}</font>', styles()[value_style])
        rows.append([para(label, "cell_bold_right" if bold else "cell_right"), value_para])
        if label in emphasise:
            commands.append(("LINEABOVE", (0, i), (-1, i), 0.8, LINE))
    table = Table(rows, colWidths=[CONTENT_WIDTH * 0.75, CONTENT_WIDTH * 0.25])
    table.setStyle(TableStyle(commands))
    return table


def signature_lines(labels: Sequence[str], columns: int = 2) -> Table:
    """Room to sign, ruled underneath, each named below its line."""
    rows: list[list[Any]] = []
    commands: list[tuple[Any, ...]] = [
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
    ]
    for start in range(0, len(labels), columns):
        chunk = list(labels[start : start + columns])
        space_row = len(rows)
        blanks: list[Any] = [""] * (columns - len(chunk))
        rows.append([*(Spacer(1, 0.9 * cm) for _ in chunk), *blanks])
        rows.append([*(para(label, "small") for label in chunk), *blanks])
        for column in range(len(chunk)):
            commands.append(("LINEBELOW", (column, space_row), (column, space_row), 0.6, INK_3))
    table = Table(rows, colWidths=[CONTENT_WIDTH / columns] * columns)
    table.setStyle(TableStyle(commands))
    return table


class QrCode(Flowable):  # type: ignore[misc]  # reportlab ships no type hints
    """A QR code holding ``data``, drawn as filled squares straight onto the page.

    Not through reportlab's graphics renderer, which sets an unembedded Helvetica as its default font even for a
    drawing with no text in it.
    """

    def __init__(self, data: str, size: float) -> None:
        super().__init__()
        self.data = data
        self.size = size
        self.width = self.height = size

    def draw(self) -> None:
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Group, Rect

        widget = QrCodeWidget(self.data)
        x0, y0, x1, y1 = widget.getBounds()
        scale = self.size / max(x1 - x0, y1 - y0)
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(colors.black)

        def paint(node: Any) -> None:
            if isinstance(node, Group):
                for child in node.contents:
                    paint(child)
            elif isinstance(node, Rect) and node.fillColor is not None and node.fillColor != colors.white:
                canvas.rect(
                    (node.x - x0) * scale, (node.y - y0) * scale, node.width * scale, node.height * scale, stroke=0, fill=1
                )

        paint(widget.draw())
        canvas.restoreState()


def qr_code(data: str, size: float = 2.6 * cm) -> Flowable:
    """A QR code holding ``data``, ``size`` square."""
    return QrCode(data, size)


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderedPdf:
    """Rendered PDF buffer paired with its exact page count from ``NumberedCanvas``."""

    buf: BytesIO
    page_count: int


def _numbered_canvas(brand: Brand, title: str, reference: str, page_count_out: list[int] | None = None) -> type[Canvas]:
    """A canvas that draws the running header and footer once the page count is known ("Page n of N")."""

    class NumberedCanvas(Canvas):  # type: ignore[misc]  # reportlab ships no type hints
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._pages: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802 — reportlab's API
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._pages)
            if page_count_out is not None:
                page_count_out.append(total)
            for state in self._pages:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int) -> None:
            page = self._pageNumber
            self.saveState()
            if page > 1:
                self.setFont(BOLD_FONT, TYPE["sm"])
                self.setFillColor(INK_2)
                self.drawString(MARGIN, PAGE_HEIGHT - MARGIN + 0.35 * cm, _plain(brand.name))
                self.setFont(BODY_FONT, TYPE["sm"])
                self.drawRightString(PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN + 0.35 * cm, _plain(f"{title} {reference}"))
                self.setStrokeColor(LINE)
                self.setLineWidth(0.5)
                self.line(MARGIN, PAGE_HEIGHT - MARGIN + 0.2 * cm, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN + 0.2 * cm)
            # Footer: the tenant's document footer on the left, the page number on the right.
            self.setStrokeColor(LINE)
            self.setLineWidth(0.5)
            self.line(MARGIN, FOOTER_HEIGHT, PAGE_WIDTH - MARGIN, FOOTER_HEIGHT)
            footer = Paragraph(
                markup(brand.footer) if brand.footer else markup(f"{brand.name} · generated with ShipX"), styles()["footer"]
            )
            _, height = footer.wrap(CONTENT_WIDTH - 3 * cm, FOOTER_HEIGHT)
            footer.drawOn(self, MARGIN, FOOTER_HEIGHT - 0.15 * cm - height)
            self.setFont(BODY_FONT, TYPE["xs"])
            self.setFillColor(INK_3)
            self.drawRightString(PAGE_WIDTH - MARGIN, FOOTER_HEIGHT - 0.15 * cm - TYPE["xs"], f"Page {page} of {total}")
            self.restoreState()

    return NumberedCanvas


def _plain(text: str) -> str:
    """Text for a direct canvas string: characters the Latin font lacks become "?" rather than empty boxes."""
    return "".join(ch if _in_body(ch) else "?" for ch in text)


def render_with_meta(
    brand: Brand,
    title: str,
    reference: str,
    body: Sequence[Flowable],
    *,
    facts: Sequence[tuple[str, str]] = (),
    subject: str = "",
) -> RenderedPdf:
    """Lay out a document and return both the PDF buffer and its exact page count."""
    register_fonts()
    buf = BytesIO()
    page_count_out: list[int] = []
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=FOOTER_HEIGHT + 0.4 * cm,
        title=f"{title} {reference}".strip(),
        author=brand.name,
        subject=subject or title,
        creator="ShipX",
        # Every page starts in the embedded font; reportlab's default would reference an unembedded Helvetica.
        initialFontName=BODY_FONT,
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame])])
    doc.build(
        [brand_block(brand, title, reference, facts), Spacer(1, 0.4 * cm), *body],
        canvasmaker=_numbered_canvas(brand, title, reference, page_count_out),
    )
    buf.seek(0)
    return RenderedPdf(buf=buf, page_count=page_count_out[-1] if page_count_out else 1)


def render(
    brand: Brand,
    title: str,
    reference: str,
    body: Sequence[Flowable],
    *,
    facts: Sequence[tuple[str, str]] = (),
    subject: str = "",
) -> BytesIO:
    """Lay out a document: the brand block, then ``body``, on A4 pages with the running header and footer."""
    return render_with_meta(brand, title, reference, body, facts=facts, subject=subject).buf
