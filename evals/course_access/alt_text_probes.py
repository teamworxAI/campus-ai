"""Probe run for the alt-text worker (A3): six synthetic images with known kinds.

Not the B3 bake-off (that needs the A6 gold set and human ratings); this checks
that the configured vision model answers in the expected shape, sorts kinds
sensibly and routes the right images to review. Images are drawn here, so the
run is reproducible on any machine. Read the alt texts: the kind score alone
says little.

    docker compose run --rm test python evals/course_access/alt_text_probes.py
"""

from __future__ import annotations

import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image as PILImage, ImageDraw, ImageFont

from campus_ai.course_access.alt_text import ALWAYS_REVIEW, describe, report_markdown
from campus_ai.course_access.parser import Document, Image, Paragraph

HERE = Path(__file__).parent


def png(draw_fn, size=(480, 320)) -> bytes:
    image = PILImage.new("RGB", size, "white")
    draw_fn(ImageDraw.Draw(image), ImageFont.load_default(size=22))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def bar_chart(d, font):
    d.text((20, 10), "Sockeye returns, Fraser River (millions)", fill="black", font=font)
    years, values = ["2018", "2019", "2020", "2021", "2022"], [120, 180, 90, 240, 150]
    d.line((60, 280, 460, 280), fill="black", width=2)
    d.line((60, 60, 60, 280), fill="black", width=2)
    for i, (year, value) in enumerate(zip(years, values)):
        x = 80 + i * 76
        d.rectangle((x, 280 - value * 0.8, x + 50, 280), fill="#1f77b4")
        d.text((x + 4, 286), year, fill="black", font=font)
        d.text((x + 8, 280 - value * 0.8 - 26), str(value / 100), fill="black", font=font)


def flow_diagram(d, font):
    boxes = [("Egg", 20), ("Fry", 180), ("Smolt", 340)]
    for label, x in boxes:
        d.rectangle((x, 120, x + 120, 190), outline="black", width=3)
        d.text((x + 30, 142), label, fill="black", font=font)
    for x in (140, 300):
        d.line((x, 155, x + 40, 155), fill="black", width=3)
        d.polygon([(x + 40, 145), (x + 40, 165), (x + 52, 155)], fill="black")


def equation(d, font):
    d.text((60, 130), "N(t) = N0 * e^(r t)", fill="black", font=ImageFont.load_default(size=36))


def text_slide(d, font):
    for i, line in enumerate(["Reading for next week:", "Groot et al. (1995), chapter 3", "Quinn (2018), pages 40-62"]):
        d.text((30, 60 + i * 50), line, fill="black", font=font)


def divider(d, font):
    d.line((20, 160, 460, 160), fill="#999999", width=4)


def shapes(d, font):
    d.ellipse((60, 60, 260, 260), fill="#d62728")
    d.rectangle((300, 100, 440, 260), fill="#2ca02c")


PROBES = [  # name, drawing, expected kinds (any of), surrounding text
    ("bar chart", bar_chart, {"chart"}, "Sockeye returns vary strongly between years."),
    ("flow diagram", flow_diagram, {"diagram"}, "The freshwater stages of the life cycle."),
    ("equation", equation, {"equation", "text"}, "Exponential growth of a population."),
    ("text slide", text_slide, {"text"}, "Homework."),
    ("divider line", divider, {"decorative"}, ""),
    ("shapes", shapes, {"illustration", "other", "photo"}, "Two coloured shapes used as an example of colour contrast."),
]


def main() -> int:
    data_class = "P"
    rows, proposals = [], []
    for name, draw_fn, expected, context in PROBES:
        document = Document("pptx", title="Probe deck", language="en", page_count=1,
                            blocks=[Paragraph(context, page=1), Image(png(draw_fn), "png", page=1, nearby_text=context)])
        start = time.perf_counter()
        proposal = describe(document, 1, data_class=data_class)
        seconds = time.perf_counter() - start
        proposals.append(proposal)
        must_review = bool(expected & ALWAYS_REVIEW) or expected == {"decorative"}
        rows.append((name, sorted(expected), proposal.kind, proposal.kind in expected,
                     proposal.needs_review == must_review or not must_review, round(seconds, 1)))
    when = datetime.now(timezone.utc)
    kind_ok = sum(r[3] for r in rows)
    route_ok = sum(r[4] for r in rows)
    lines = [f"# Alt-text probe run: {proposals[0].model}", "",
             f"{when:%Y-%m-%d %H:%M} UTC. Kind right for {kind_ok}/{len(rows)}; review routing right for "
             f"{route_ok}/{len(rows)} (images that must go to review did). Times include model loading on the first call.",
             "", "| Probe | Expected kind | Got | Kind ok | Routing ok | Seconds |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {', '.join(e)} | {g} | {'yes' if k else 'NO'} | {'yes' if r else 'NO'} | {s} |"
              for n, e, g, k, r, s in rows]
    lines += ["", report_markdown(proposals, "probe deck")]
    report = "\n".join(lines)
    print(report)
    out = HERE / f"alt_text_probes_{when:%Y%m%d}.md"
    out.write_text(report, encoding="utf-8")
    print(f"\nReport: {out.relative_to(HERE.parents[1])}")
    return 0 if kind_ok == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
