"""Make the A4b equation fixtures: a DOCX with two equations and a PPTX with one.

Hand-written OMML (the quadratic formula and a sum with limits, from the unit
tests) placed in a python-docx / python-pptx document, the way Word and
PowerPoint store native equations. Output goes to the folder given (default
evals/course_access/fixtures/). Fully offline.

    docker compose run --rm test python evals/course_access/make_math_fixtures.py
    docker compose run --rm test python scripts/remediate.py evals/course_access/fixtures/equations.docx --out /tmp/out
"""

from __future__ import annotations

import sys
from pathlib import Path

import docx
import pptx
from lxml import etree
from pptx.util import Inches

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "tests"))
from test_course_access_mathml import QUADRATIC, SUM, add_equation, display, root_of  # noqa: E402


def make(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    d = docx.Document()
    d.core_properties.title = "Equations sample"
    d.core_properties.language = "en-CA"
    d.add_heading("Algebra", level=1)
    add_equation(d.add_paragraph("The roots of a quadratic equation are:"), display(QUADRATIC))
    d.add_paragraph("The total of the marks is ")
    add_equation(d.paragraphs[-1], SUM)
    d.add_paragraph("That is all.")
    docx_path = out / "equations.docx"
    d.save(docx_path)

    deck = pptx.Presentation()
    deck.core_properties.title = "Equations sample"
    deck.core_properties.language = "en-CA"
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Sums"
    box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    box.text_frame.text = "The total of the marks:"
    paragraph = box.text_frame.add_paragraph()
    paragraph._p.append(etree.fromstring(
        '<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        '<mc:Choice Requires="a14" xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main">'
        f'<a14:m>{etree.tostring(root_of(SUM), encoding="unicode")}</a14:m></mc:Choice></mc:AlternateContent>'))
    pptx_path = out / "equations.pptx"
    deck.save(pptx_path)
    return [docx_path, pptx_path]


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fixtures"
    for path in make(folder):
        print(f"{path} ({path.stat().st_size / 1024:.1f} KB)")
