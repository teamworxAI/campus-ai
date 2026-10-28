"""Make scanned_two_pages.pdf: two pages that are only images of text, for the A7 OCR demo.

Text is drawn onto page-sized PNGs with Pillow and each PNG is the whole of one PDF
page (no text layer), as a scanner would produce. Offline; reportlab is in the dev group.

    docker compose run --rm test python evals/course_access/fixtures/make_scanned_pdf.py
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PAGES = [
    ["Introduction to Ocean Science", "",
     "Week one covers the water cycle and the major ocean currents.",
     "Students should read chapter two before the first lecture.", "",
     "Assessment: two quizzes, one lab report and a final exam."],
    ["Course Policies", "",
     "Late assignments lose five percent for each day after the deadline.",
     "Please contact the instructor early if you need an accommodation."],
]
OUT = Path(__file__).with_name("scanned_two_pages.pdf")


def render(lines: list[str]) -> Image.Image:
    page = Image.new("L", (1700, 2200), 255)  # letter paper at 200 dpi, greyscale like a scan
    draw = ImageDraw.Draw(page)
    for i, line in enumerate(lines):
        draw.text((150, 200 + i * 70), line, fill=0, font=ImageFont.load_default(size=44))
    return page


def main() -> None:
    c = canvas.Canvas(str(OUT), pagesize=letter)
    c.setTitle("")
    for lines in PAGES:
        png = io.BytesIO()
        render(lines).save(png, "PNG")
        png.seek(0)
        c.drawImage(ImageReader(png), 0, 0, width=letter[0], height=letter[1])
        c.showPage()
    c.save()
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
