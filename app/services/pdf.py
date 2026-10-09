"""The single, predefined certificate template (landscape A4 PDF)."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A4)

NAVY = HexColor("#1F2A44")
GOLD = HexColor("#B8892B")
GREY = HexColor("#555555")


@dataclass(frozen=True)
class CertificateData:
    recipient_name: str
    course_name: str
    issuer: str
    issue_date: date
    verification_code: str


def _fit_font_size(text: str, font: str, max_size: int, max_width: float, min_size: int = 12) -> int:
    """Shrink the font until the text fits on one line (long names / course titles)."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _draw(c: canvas.Canvas, data: CertificateData) -> None:
    cx = PAGE_W / 2

    # frame
    c.setStrokeColor(NAVY)
    c.setLineWidth(6)
    c.rect(20, 20, PAGE_W - 40, PAGE_H - 40)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(32, 32, PAGE_W - 64, PAGE_H - 64)

    # heading
    c.setFillColor(NAVY)
    c.setFont("Times-Bold", 44)
    c.drawCentredString(cx, PAGE_H - 130, "CERTIFICATE")
    c.setFillColor(GOLD)
    c.setFont("Helvetica", 16)
    c.drawCentredString(cx, PAGE_H - 158, "O F   C O M P L E T I O N")

    c.setFillColor(GREY)
    c.setFont("Helvetica", 14)
    c.drawCentredString(cx, PAGE_H - 215, "This is to certify that")

    # recipient
    name_font = "Times-BoldItalic"
    name_size = _fit_font_size(data.recipient_name, name_font, 40, PAGE_W - 200)
    c.setFillColor(NAVY)
    c.setFont(name_font, name_size)
    c.drawCentredString(cx, PAGE_H - 270, data.recipient_name)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(cx - 220, PAGE_H - 284, cx + 220, PAGE_H - 284)

    c.setFillColor(GREY)
    c.setFont("Helvetica", 14)
    c.drawCentredString(cx, PAGE_H - 320, "has successfully completed")

    course_font = "Helvetica-Bold"
    course_size = _fit_font_size(data.course_name, course_font, 24, PAGE_W - 160)
    c.setFillColor(NAVY)
    c.setFont(course_font, course_size)
    c.drawCentredString(cx, PAGE_H - 360, data.course_name)

    # footer: date (left) and issuer (right)
    for x, value, label in (
        (170, data.issue_date.strftime("%d %B %Y"), "Date"),
        (PAGE_W - 170, data.issuer, "Issued by"),
    ):
        c.setFillColor(NAVY)
        size = _fit_font_size(value, "Helvetica-Bold", 13, 200, min_size=8)
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(x, 115, value)
        c.setStrokeColor(GREY)
        c.setLineWidth(0.8)
        c.line(x - 90, 108, x + 90, 108)
        c.setFillColor(GREY)
        c.setFont("Helvetica", 10)
        c.drawCentredString(x, 94, label)

    c.setFont("Helvetica", 9)
    c.drawCentredString(cx, 48, f"Certificate ID: {data.verification_code}")


def render_certificate(data: CertificateData, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # write to a temp file first so a crash never leaves a half-written PDF behind
    tmp_path = output_path.with_suffix(".pdf.tmp")
    c = canvas.Canvas(str(tmp_path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issuer)
    c.setSubject(data.course_name)
    _draw(c, data)
    c.showPage()
    c.save()
    tmp_path.replace(output_path)
    return output_path
