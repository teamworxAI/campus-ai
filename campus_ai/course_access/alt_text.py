"""Alt-text worker (A3): proposes alt text for images with a local vision model.

Code decides which images need work (the audit's alt-text issues), what the
model sees (the image, the document title and the text around it) and what
becomes of the answer: a parsed, checked proposal with a confidence score.
Nothing is written back. Proposals go to human review; the rebuild step (A5)
applies the approved ones.

Review rules (master plan 3.2), applied in code, not left to the model:
- every chart, diagram, equation and image of text goes to review, whatever
  the confidence;
- so does every answer below CONFIDENCE_THRESHOLD, every proposal to mark an
  image decorative (a wrong call hides content from screen-reader users),
  every over-long alt text and every answer the code can't parse;
- decorative images are marked decorative, not described.

The confidence is the model's own estimate; bake-off B3 calibrates it against
reviewers on the gold set (A6). The model runs on Ollama through the LLM
router (prime directive 2) and never sees class R data (P1b).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass

from campus_ai.core.llm import generate
from campus_ai.course_access.audit import ALT_TEXT, audit
from campus_ai.course_access.model_answers import CONFIDENCE_THRESHOLD, confidence as _confidence, parse_json as _parse
from campus_ai.course_access.parser import Document, Image

KINDS = ("photo", "illustration", "chart", "diagram", "equation", "text", "decorative", "other")
ALWAYS_REVIEW = {"chart", "diagram", "equation", "text"}
MAX_ALT_CHARS = 200

SYSTEM = f"""You write alt text for images in university course materials, for students who use a screen reader.
Answer with one JSON object and nothing else:
{{"kind": "<one of {', '.join(KINDS)}>", "decorative": <true or false>, "alt": "<one sentence>", "long_description": "<text>", "confidence": <0.0 to 1.0>}}
Rules:
- alt: one sentence, at most 150 characters, saying what the image shows and why it matters here. Do not start with "image of" or "picture of". Never invent numbers, labels or names you cannot read.
- long_description: for a chart, the axes, labels, values and trend; for a diagram, its parts and how they connect; for an equation, the equation in words or LaTeX; for an image of text, the text itself. Empty for a simple photo or illustration.
- decorative: true only if the image carries no information (a divider, background, bullet or spacer); then alt is empty.
- confidence: how sure you are that alt and long_description are accurate and complete."""

LEADING_PHRASE = re.compile(r"^(an?\s+)?(image|picture|photo|photograph|graphic|illustration|screenshot)\s+(of|showing)\s+", re.IGNORECASE)
MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


@dataclass
class AltText:
    block: int  # index into Document.blocks
    page: int | None
    kind: str
    decorative: bool
    alt: str  # "" when decorative
    long_description: str
    confidence: float  # the model's own estimate, 0 to 1
    needs_review: bool
    review_reason: str  # "" when the proposal can be applied without review
    model: str


def images_needing_alt(document: Document) -> list[int]:
    """Block indexes of the images the audit sends to the alt-text worker."""
    return [issue.block for issue in audit(document) if issue.fix == ALT_TEXT and issue.block is not None]


def propose(document: Document, *, data_class: str, blocks: list[int] | None = None) -> list[AltText]:
    """One proposal per image that needs alt text (or per index in `blocks`)."""
    indexes = images_needing_alt(document) if blocks is None else blocks
    return [describe(document, i, data_class=data_class) for i in indexes]


def describe(document: Document, index: int, *, data_class: str) -> AltText:
    """Ask the vision model about one image and turn its answer into a checked proposal."""
    image = document.blocks[index]
    if not isinstance(image, Image):
        raise TypeError(f"Block {index} is a {type(image).__name__}, not an Image")
    response = generate([_message(document, image)], task="vision", data_class=data_class, system=SYSTEM)
    answer = _parse(response.text)
    return _check(answer, index, image.page, response.model)


def _message(document: Document, image: Image) -> dict:
    where = f" {'Slide' if document.source_format == 'pptx' else 'Page'} {image.page}." if image.page else ""
    context = [f"Course document: {document.title or 'untitled'} ({document.source_format.upper()}).{where}"]
    if image.nearby_text:
        context.append(f"Text around the image:\n{image.nearby_text}")
    if image.alt:
        context.append(f"Existing alt text, a placeholder to replace: {image.alt!r}")
    media_type = MEDIA_TYPES.get(image.format.lower(), f"image/{image.format.lower()}")
    return {"role": "user", "content": [
        {"type": "text", "text": "\n".join(context)},
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.b64encode(image.data).decode()}},
    ]}


def _check(answer: dict | None, index: int, page: int | None, model: str) -> AltText:
    if answer is None:
        return AltText(index, page, "other", False, "", "", 0.0, True, "the model's answer was not JSON", model)
    kind = str(answer.get("kind", "other")).strip().lower()
    if kind not in KINDS:
        kind = "other"
    decorative = answer.get("decorative") is True or kind == "decorative"
    alt = "" if decorative else _clean(answer.get("alt"))
    long_description = _clean(answer.get("long_description"))
    confidence = _confidence(answer.get("confidence"))
    reasons = []
    if kind in ALWAYS_REVIEW:
        reasons.append(f"{'images of text' if kind == 'text' else kind + 's'} always go to review")
    if decorative:
        reasons.append("marking an image decorative hides it from screen readers")
    elif not alt:
        reasons.append("no description")
    if confidence < CONFIDENCE_THRESHOLD:
        reasons.append(f"confidence {confidence:.2f} is below {CONFIDENCE_THRESHOLD}")
    if len(alt) > MAX_ALT_CHARS:
        reasons.append(f"alt text is over {MAX_ALT_CHARS} characters; move detail to the long description")
    return AltText(index, page, kind, decorative, alt, long_description, confidence,
                   bool(reasons), "; ".join(reasons), model)


def _clean(text) -> str:
    """One line of text, without a leading 'image of' or the like, starting with a capital."""
    if not isinstance(text, str):
        return ""
    text = " ".join(text.split())
    text = LEADING_PHRASE.sub("", text)
    return text[:1].upper() + text[1:]


def report_json(proposals: list[AltText]) -> str:
    return json.dumps([asdict(p) for p in proposals], indent=2, ensure_ascii=False)


def report_markdown(proposals: list[AltText], name: str = "") -> str:
    """A review sheet: every proposal, what to check and why."""
    review = sum(p.needs_review for p in proposals)
    lines = [f"# Alt text proposals{': ' + name if name else ''}", "",
             f"{len(proposals)} images need alt text; {review} need review, "
             f"{len(proposals) - review} can be applied as proposed. Nothing is changed until approved.", ""]
    for p in proposals:
        where = f" (page {p.page})" if p.page else ""
        lines.append(f"## Image at block {p.block}{where}: {p.kind}, confidence {p.confidence:.2f}")
        lines.append("")
        lines.append("- **Decorative:** no alt text; the image is hidden from screen readers." if p.decorative
                     else f"- **Alt:** {p.alt or '(none)'}")
        if p.long_description:
            lines.append(f"- **Long description:** {p.long_description}")
        lines.append(f"- **Review:** {p.review_reason}" if p.needs_review else "- **Review:** not needed")
        lines.append(f"- **Model:** {p.model}")
        lines.append("")
    return "\n".join(lines)
