"""House style for generated MoM documents.

Style rules requested for the DAC Minutes deliverables:

* the whole document is set in **Cambria**;
* sub-headings are **12 pt**;
* normal text is **11 pt**;
* line spacing is **1.15** (leading = font size x 1.15).

Cambria itself is a proprietary Microsoft font that cannot be redistributed, so
the bundled PDF embeds **Caladea**, the metric-compatible Cambria substitute
published by Google under the SIL Open Font License. Caladea has identical
advance widths and a near-identical design, so pagination and line breaks match
Cambria. The registered PDF font is named ``Cambria`` so viewers report it that
way, and the Word export names Cambria directly - Microsoft Word then renders
with the real Cambria installed on the machine.

If the font files are ever missing, the theme falls back to the built-in
Times-Roman family so exports never break.
"""
from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FONT_DIR = BASE_DIR / "assets" / "fonts"

# Logical family name used inside the generated PDF and DOCX.
FAMILY_NAME = "Cambria"
DOCX_FAMILY_NAME = "Cambria"

#: Body text size in points.
BODY_SIZE = 11
#: Sub-heading size in points.
HEADING_SIZE = 12
#: Document title size in points (kept distinct from sub-headings).
TITLE_SIZE = 14
#: Running footer / annexure index footnotes.
FOOTNOTE_SIZE = 9
#: Required line spacing multiple.
LINE_SPACING = 1.15

FONT_FILES = {
    "regular": FONT_DIR / "Caladea-Regular.ttf",
    "bold": FONT_DIR / "Caladea-Bold.ttf",
    "italic": FONT_DIR / "Caladea-Italic.ttf",
    "boldItalic": FONT_DIR / "Caladea-BoldItalic.ttf",
}

_REGISTERED = False
_EMBEDDED = False


def leading(size: float = BODY_SIZE) -> float:
    """Return the 1.15 line-spacing leading for a font size in points."""
    return round(size * LINE_SPACING, 2)


def space_after(size: float = BODY_SIZE) -> float:
    """Paragraph gap that preserves the 1.15 rhythm (a fraction of one line)."""
    return round(leading(size) * 0.5, 2)


def fonts_available() -> bool:
    return all(path.is_file() for path in FONT_FILES.values())


def register_pdf_fonts() -> bool:
    """Register the Cambria-compatible family with ReportLab.

    Returns ``True`` when the bundled Cambria-metric font was embedded, and
    ``False`` when the Times-Roman fallback is in use.
    """
    global _REGISTERED, _EMBEDDED
    if _REGISTERED:
        return _EMBEDDED
    _REGISTERED = True
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if fonts_available():
        try:
            pdfmetrics.registerFont(TTFont(FAMILY_NAME, str(FONT_FILES["regular"])))
            pdfmetrics.registerFont(TTFont(f"{FAMILY_NAME}-Bold", str(FONT_FILES["bold"])))
            pdfmetrics.registerFont(TTFont(f"{FAMILY_NAME}-Italic", str(FONT_FILES["italic"])))
            pdfmetrics.registerFont(TTFont(f"{FAMILY_NAME}-BoldItalic", str(FONT_FILES["boldItalic"])))
            pdfmetrics.registerFontFamily(
                FAMILY_NAME,
                normal=FAMILY_NAME,
                bold=f"{FAMILY_NAME}-Bold",
                italic=f"{FAMILY_NAME}-Italic",
                boldItalic=f"{FAMILY_NAME}-BoldItalic",
            )
            _EMBEDDED = True
            return True
        except Exception:  # pragma: no cover - corrupt font file, fall back below
            _EMBEDDED = False
    return _EMBEDDED


def pdf_font(bold: bool = False, italic: bool = False) -> str:
    """Return the registered PDF font name for the requested face."""
    if not register_pdf_fonts():
        if bold and italic:
            return "Times-BoldItalic"
        if bold:
            return "Times-Bold"
        if italic:
            return "Times-Italic"
        return "Times-Roman"
    if bold and italic:
        return f"{FAMILY_NAME}-BoldItalic"
    if bold:
        return f"{FAMILY_NAME}-Bold"
    if italic:
        return f"{FAMILY_NAME}-Italic"
    return FAMILY_NAME


def font_status() -> dict:
    """Describe which font is actually used, for the API/UI diagnostics."""
    embedded = register_pdf_fonts()
    return {
        "family": FAMILY_NAME,
        "pdfFont": FAMILY_NAME if embedded else "Times-Roman",
        "pdfEmbedded": embedded,
        "source": "Caladea (metric-compatible Cambria substitute, SIL OFL 1.1)" if embedded else "ReportLab built-in Times-Roman fallback",
        "docxFont": DOCX_FAMILY_NAME,
        "bodyPt": BODY_SIZE,
        "headingPt": HEADING_SIZE,
        "titlePt": TITLE_SIZE,
        "lineSpacing": LINE_SPACING,
    }


def apply_docx_style(document, name: str = "Normal", *, size: float = BODY_SIZE, bold: bool = False,
                     italic: bool = False, align=None, space_before: float = 0.0,
                     space_after_pt: float | None = None, keep_with_next: bool = False):
    """Configure a Word style with Cambria, the requested size and 1.15 spacing."""
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt

    style = document.styles[name]
    style.font.name = DOCX_FAMILY_NAME
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    if align is not None:
        style.paragraph_format.alignment = align
    style.paragraph_format.line_spacing = LINE_SPACING
    style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    style.paragraph_format.space_before = Pt(space_before)
    style.paragraph_format.space_after = Pt(space_after(size) if space_after_pt is None else space_after_pt)
    style.paragraph_format.keep_with_next = keep_with_next
    _apply_east_asian_font(style)
    return style


def _apply_east_asian_font(style) -> None:
    """python-docx only sets the Latin font, so set the complex-script faces too."""
    try:
        rpr = style.element.get_or_add_rPr()
        rfonts = rpr.find(_qn("w:rFonts"))
        if rfonts is None:
            from docx.oxml import OxmlElement

            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        from docx.oxml.ns import qn

        for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(attribute), DOCX_FAMILY_NAME)
    except Exception:  # pragma: no cover - style still works with the Latin face only
        pass


def _qn(tag: str):
    from docx.oxml.ns import qn

    return qn(tag)


def style_docx_run(run, *, size: float = BODY_SIZE, bold: bool = False, italic: bool = False) -> None:
    """Force Cambria + size on a single run (tables ignore the Normal style)."""
    from docx.oxml.ns import qn
    from docx.shared import Pt

    run.font.name = DOCX_FAMILY_NAME
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        from docx.oxml import OxmlElement

        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attribute), DOCX_FAMILY_NAME)
