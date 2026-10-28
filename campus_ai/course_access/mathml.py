"""Convert Office MathML (OMML) equations to presentation MathML and plain text (A4b).

Word and PowerPoint store native equations as OMML (``m:oMathPara`` for a
display equation, ``m:oMath`` for an inline one). The parser keeps them as
``Equation`` blocks; this module is the deterministic converter behind them.
No model and no OCR: the equation is already structured in the file.

- ``to_mathml(omml)``: presentation MathML, for the accessible HTML.
- ``to_text(omml)``: a plain-text reading, e.g.
  ``x = (-b ± √(b² - 4ac)) / 2a``, for alt text and the DOCX fallback.

Covered: runs, fractions, scripts (sup, sub, sub+sup, pre-scripts), radicals,
n-ary operators with limits, delimiters, functions, accents, bars, matrices,
equation arrays, limits, boxes, group characters and bordered boxes. An
unknown construct degrades to its text inside an ``<mrow>`` rather than
failing. Only lxml (already a dependency of python-docx) is used.
"""

from __future__ import annotations

import re

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MATHML_NS = "http://www.w3.org/1998/Math/MathML"
_M = f"{{{M_NS}}}"
APPLY = "⁡"  # function application, invisible

# Combining accents (what Word stores in m:accPr) to the spacing marks MathML expects.
_ACCENTS = {"̂": "^", "̃": "~", "̄": "¯", "̇": "˙", "̈": "¨",
            "̌": "ˇ", "́": "´", "̀": "`", "⃗": "→", "̆": "˘"}
_SUPERSCRIPT = dict(zip("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"))
_SUBSCRIPT = dict(zip("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"))
_TOKEN = re.compile(r"\d+(?:[.,]\d+)?|[^\W\d_]|\s+|.", re.UNICODE)


def _name(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _child(el, name: str):
    return el.find(f"{_M}{name}")


def _prop(el, pr: str, name: str, default: str | None = None) -> str | None:
    """Value of ``m:<pr>/m:<name>/@m:val`` of `el`, or `default` if absent."""
    holder = _child(el, pr)
    prop = _child(holder, name) if holder is not None else None
    return prop.get(f"{_M}val", default) if prop is not None else default


def _content(el) -> list:
    """Children that carry content (not the ``*Pr`` property elements)."""
    return [c for c in el if isinstance(c.tag, str) and not _name(c).endswith("Pr")]


def _arg(el, name: str):
    """The argument element ``m:<name>`` of `el` (``m:e``, ``m:sup`` ...) or None."""
    return _child(el, name)


def _plain(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{_M}t"))


# --- MathML -------------------------------------------------------------------

def to_mathml(omml, *, display: bool | None = None, alttext: str | None = None) -> str:
    """Presentation MathML for an ``m:oMathPara`` or ``m:oMath`` element, as a string.

    `display` defaults to True for ``m:oMathPara``. `alttext`, if given, is set on ``<math>``.
    """
    if display is None:
        display = _name(omml) == "oMathPara"
    root = etree.Element(f"{{{MATHML_NS}}}math", nsmap={None: MATHML_NS})
    if display:
        root.set("display", "block")
    if alttext:
        root.set("alttext", alttext)
    for node in _mathml_children(omml):
        root.append(node)
    return etree.tostring(root, encoding="unicode")


def _mk(tag: str, *children, text: str | None = None, **attrs):
    el = etree.Element(f"{{{MATHML_NS}}}{tag}", {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = text
    for child in children:
        el.append(child)
    return el


def _row(nodes: list):
    """One MathML element for a list of nodes (an mrow unless it is a single node)."""
    return nodes[0] if len(nodes) == 1 else _mk("mrow", *nodes)


def _group(el, name: str):
    """The MathML for the argument ``m:<name>`` of `el` as a single element (empty mrow if missing)."""
    arg = _arg(el, name)
    return _row(_mathml_children(arg)) if arg is not None else _mk("mrow")


def _mathml_children(el) -> list:
    out: list = []
    for child in _content(el):
        out.extend(_mathml(child))
    return out


def _mo(char: str, **attrs):
    return _mk("mo", text=char, **attrs)


def _mathml(el) -> list:
    handler = _MATHML.get(_name(el))
    if handler is None:
        return _unknown(el)
    return handler(el)


def _unknown(el) -> list:
    """Anything we don't model: its text, so nothing is lost."""
    text = _plain(el).strip()
    return [_mk("mrow", _mk("mtext", text=text))] if text else []


def _run(el) -> list:
    text = _plain(el)
    if _prop(el, "rPr", "nor") in ("1", "on", "true"):  # normal text, not maths
        return [_mk("mtext", text=text)]
    if _prop(el, "rPr", "sty") == "p" and len(text.strip()) > 1 and text.strip().isalpha():  # upright name
        return [_mk("mi", text=text.strip())]
    nodes = []
    for token in _TOKEN.findall(text):
        if token.isspace():
            continue
        if token[0].isdigit():
            nodes.append(_mk("mn", text=token))
        elif token[0].isalpha():
            nodes.append(_mk("mi", text=token))
        else:
            nodes.append(_mo(token))
    return nodes


def _fraction(el) -> list:
    attrs = {"linethickness": "0"} if _prop(el, "fPr", "type") == "noBar" else {}
    return [_mk("mfrac", _group(el, "num"), _group(el, "den"), **attrs)]


def _scripts(tag: str, *names: str):
    def build(el) -> list:
        return [_mk(tag, _group(el, "e"), *(_group(el, n) for n in names))]
    return build


def _pre_script(el) -> list:
    return [_mk("mmultiscripts", _group(el, "e"), _mk("mprescripts"), _group(el, "sub"), _group(el, "sup"))]


def _radical(el) -> list:
    degree = _arg(el, "deg")
    if _prop(el, "radPr", "degHide") in ("1", "on", "true") or degree is None or not _plain(degree).strip():
        return [_mk("msqrt", _group(el, "e"))]
    return [_mk("mroot", _group(el, "e"), _group(el, "deg"))]


def _nary(el) -> list:
    char = _prop(el, "naryPr", "chr", "∫")  # an integral unless said otherwise
    under_over = _prop(el, "naryPr", "limLoc", "subSup" if char.startswith("∫") else "undOvr") == "undOvr"
    sub = None if _prop(el, "naryPr", "subHide") in ("1", "on", "true") else _group(el, "sub")
    sup = None if _prop(el, "naryPr", "supHide") in ("1", "on", "true") else _group(el, "sup")
    operator = _mo(char, largeop="true", stretchy="true") if char else _mk("mrow")
    if sub is not None and sup is not None:
        head = _mk("munderover" if under_over else "msubsup", operator, sub, sup)
    elif sub is not None:
        head = _mk("munder" if under_over else "msub", operator, sub)
    elif sup is not None:
        head = _mk("mover" if under_over else "msup", operator, sup)
    else:
        head = operator
    return [head, _group(el, "e")]


def _delimiter(el) -> list:
    begin = _prop(el, "dPr", "begChr", "(")
    end = _prop(el, "dPr", "endChr", ")")
    sep = _prop(el, "dPr", "sepChr", ",")
    nodes = [_mo(begin, fence="true", form="prefix")] if begin else []
    for i, arg in enumerate(a for a in _content(el) if _name(a) == "e"):
        if i and sep:
            nodes.append(_mo(sep, separator="true"))
        nodes.append(_row(_mathml_children(arg)) if len(arg) else _mk("mrow"))
    if end:
        nodes.append(_mo(end, fence="true", form="postfix"))
    return [_mk("mrow", *nodes)]


def _function(el) -> list:
    name = _arg(el, "fName")
    # A plain-text name (sin, lim, log) is one identifier, not a product of letters.
    if name is not None and all(_name(c) == "r" for c in _content(name)) and _plain(name).strip():
        head = _mk("mi", text=_plain(name).strip())
    else:
        head = _group(el, "fName")
    return [_mk("mrow", head, _mo(APPLY), _group(el, "e"))]


def _accent(el) -> list:
    char = _prop(el, "accPr", "chr", "̂")
    return [_mk("mover", _group(el, "e"), _mo(_ACCENTS.get(char, char)), accent="true")]


def _bar(el) -> list:
    if _prop(el, "barPr", "pos", "bot") == "top":
        return [_mk("mover", _group(el, "e"), _mo("¯"))]
    return [_mk("munder", _group(el, "e"), _mo("_"))]


def _matrix(el) -> list:
    rows = [_mk("mtr", *(_mk("mtd", _row(_mathml_children(c)) if len(c) else _mk("mrow"))
                         for c in _content(r) if _name(c) == "e"))
            for r in _content(el) if _name(r) == "mr"]
    return [_mk("mtable", *rows)]


def _eq_array(el) -> list:
    rows = [_mk("mtr", _mk("mtd", _row(_mathml_children(c)) if len(c) else _mk("mrow")))
            for c in _content(el) if _name(c) == "e"]
    return [_mk("mtable", *rows)]


def _group_char(el) -> list:
    char = _prop(el, "groupChrPr", "chr", "⏟")
    tag = "mover" if _prop(el, "groupChrPr", "pos", "bot") == "top" else "munder"
    return [_mk(tag, _group(el, "e"), _mo(char, stretchy="true"))]


def _wrap(tag: str, **attrs):
    return lambda el: [_mk(tag, _group(el, "e"), **attrs)]


def _transparent(el) -> list:
    return _mathml_children(el)


_MATHML = {
    "oMathPara": lambda el: [_mk("mrow", *_mathml(c)) for c in _content(el)],
    "oMath": _transparent, "e": _transparent, "num": _transparent, "den": _transparent,
    "r": _run, "f": _fraction,
    "sSup": _scripts("msup", "sup"), "sSub": _scripts("msub", "sub"),
    "sSubSup": _scripts("msubsup", "sub", "sup"), "sPre": _pre_script,
    "rad": _radical, "nary": _nary, "d": _delimiter, "func": _function,
    "acc": _accent, "bar": _bar, "m": _matrix, "eqArr": _eq_array,
    "limLow": _scripts("munder", "lim"), "limUpp": _scripts("mover", "lim"),
    "box": _wrap("mrow"), "groupChr": _group_char, "borderBox": _wrap("menclose", notation="box"),
    "phant": _wrap("mphantom"),
}


# --- Plain text -----------------------------------------------------------------

def to_text(omml) -> str:
    """The equation read as one line of text, e.g. ``x = (-b ± √(b² - 4ac)) / 2a``."""
    if _name(omml) == "oMathPara":
        parts = [_text(c) for c in _content(omml)]
        return " ; ".join(p for p in parts if p)
    return _squash(_text(omml))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _t(el, name: str) -> str:
    arg = _arg(el, name)
    return _squash("".join(_text(c) for c in _content(arg))) if arg is not None else ""


def _simple(text: str) -> bool:
    return not re.search(r"[\s+\-−±×÷/=<>,;]", text)


def _paren(text: str) -> str:
    return text if _simple(text) else f"({text})"


def _script(text: str, table: dict, mark: str) -> str:
    if text and all(c in table for c in text):
        return "".join(table[c] for c in text)
    return f"{mark}{_paren(text)}"


def _text(el) -> str:
    handler = _TEXT.get(_name(el))
    if handler is not None:
        return handler(el)
    return "".join(_text(c) for c in _content(el)) if len(el) else _plain(el)


def _text_run(el) -> str:
    return _plain(el)


def _text_nary(el) -> str:
    char = _prop(el, "naryPr", "chr", "∫")
    sub = "" if _prop(el, "naryPr", "subHide") in ("1", "on", "true") else _t(el, "sub")
    sup = "" if _prop(el, "naryPr", "supHide") in ("1", "on", "true") else _t(el, "sup")
    out = char
    if sub:
        out += f" from {sub}"
    if sup:
        out += f" to {sup}"
    return f"{out} of {_t(el, 'e')}" if sub or sup else f"{out} {_t(el, 'e')}"


def _text_delimiter(el) -> str:
    begin = _prop(el, "dPr", "begChr", "(")
    end = _prop(el, "dPr", "endChr", ")")
    sep = _prop(el, "dPr", "sepChr", ",")
    args = [_squash("".join(_text(c) for c in _content(a))) for a in _content(el) if _name(a) == "e"]
    return f"{begin}{(sep + ' ').join(args) if sep else ' '.join(args)}{end}"


def _text_function(el) -> str:
    name, arg = _t(el, "fName"), _t(el, "e")
    return f"{name}{arg}" if arg.startswith("(") else f"{name} {arg}"


def _text_matrix(el) -> str:
    rows = [", ".join(_squash("".join(_text(x) for x in _content(c))) for c in _content(r) if _name(c) == "e")
            for r in _content(el) if _name(r) == "mr"]
    return "; ".join(rows)


def _text_eq_array(el) -> str:
    return "; ".join(_squash("".join(_text(x) for x in _content(c))) for c in _content(el) if _name(c) == "e")


def _text_radical(el) -> str:
    body, degree = _t(el, "e"), _t(el, "deg")
    if _prop(el, "radPr", "degHide") in ("1", "on", "true") or not degree:
        return f"√{_paren(body)}"
    return f"root {degree} of {_paren(body)}"


def _text_fraction(el) -> str:
    return f"{_paren(_t(el, 'num'))} / {_paren(_t(el, 'den'))}"


def _text_accent(el) -> str:
    char = _prop(el, "accPr", "chr", "̂")
    base = _t(el, "e")
    return base + char if char in _ACCENTS else f"{char}{_paren(base)}"


def _text_bar(el) -> str:
    return _t(el, "e") + ("̄" if _prop(el, "barPr", "pos", "bot") == "top" else "̲")


def _text_limit(mark: str):
    return lambda el: f"{_t(el, 'e')}{mark}{_paren(_t(el, 'lim'))}"


def _text_children(el) -> str:
    return _t(el, "e")


_TEXT = {
    "r": _text_run, "f": _text_fraction,
    "sSup": lambda el: _t(el, "e") + _script(_t(el, "sup"), _SUPERSCRIPT, "^"),
    "sSub": lambda el: _t(el, "e") + _script(_t(el, "sub"), _SUBSCRIPT, "_"),
    "sSubSup": lambda el: (_t(el, "e") + _script(_t(el, "sub"), _SUBSCRIPT, "_")
                           + _script(_t(el, "sup"), _SUPERSCRIPT, "^")),
    "sPre": lambda el: f"({_t(el, 'sub')},{_t(el, 'sup')}){_t(el, 'e')}",
    "rad": _text_radical, "nary": _text_nary, "d": _text_delimiter, "func": _text_function,
    "acc": _text_accent, "bar": _text_bar, "m": _text_matrix, "eqArr": _text_eq_array,
    "limLow": _text_limit("_"), "limUpp": _text_limit("^"),
    "box": _text_children, "groupChr": _text_children, "borderBox": _text_children, "phant": _text_children,
}
