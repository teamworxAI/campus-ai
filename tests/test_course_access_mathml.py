import re
import unittest
import xml.etree.ElementTree as ET

from lxml import etree

from campus_ai.course_access import mathml

NS = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
MML = "{http://www.w3.org/1998/Math/MathML}"


def r(text):
    return f"<m:r><m:t>{text}</m:t></m:r>"


def omml(body):
    return etree.fromstring(f"<m:oMath {NS}>{body}</m:oMath>")


# Hand-written OMML, shared with the parser and rebuild tests (bodies only, no wrapper).
QUADRATIC = ("<m:oMath>" + r("x = ") + "<m:f><m:num>" + r("-b ± ")
             + '<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>'
             + "<m:sSup><m:e>" + r("b") + "</m:e><m:sup>" + r("2") + "</m:sup></m:sSup>" + r(" - 4ac")
             + "</m:e></m:rad></m:num><m:den>" + r("2a") + "</m:den></m:f></m:oMath>")
SUM = ('<m:oMath><m:nary><m:naryPr><m:chr m:val="∑"/></m:naryPr><m:sub>' + r("i=1") + "</m:sub><m:sup>" + r("n")
       + "</m:sup><m:e><m:sSub><m:e>" + r("x") + "</m:e><m:sub>" + r("i") + "</m:sub></m:sSub></m:e></m:nary></m:oMath>")
FRACTION = ("<m:oMath><m:f><m:num><m:sSub><m:e>" + r("x") + "</m:e><m:sub>" + r("0") + "</m:sub></m:sSub></m:num><m:den>"
            + r("2") + "</m:den></m:f></m:oMath>")
MATRIX = ("<m:oMath><m:d><m:e><m:m>"
          + "".join("<m:mr>" + "".join(f"<m:e>{r(c)}</m:e>" for c in row) + "</m:mr>" for row in ("ab", "cd"))
          + "</m:m></m:e></m:d></m:oMath>")
UNKNOWN = "<m:oMath><m:wibble>" + r("hi") + "</m:wibble></m:oMath>"
QUADRATIC_TEXT = "x = (-b ± √(b² - 4ac)) / 2a"
SUM_TEXT = "∑ from i=1 to n of x_i"


def display(body: str) -> str:
    """An oMath body wrapped as a display equation."""
    return f"<m:oMathPara>{body}</m:oMathPara>"


def parse(xml: str) -> ET.Element:
    return ET.fromstring(xml)


class MathMlTests(unittest.TestCase):
    def test_quadratic_formula_structure(self):
        root = parse(mathml.to_mathml(root_of(display(QUADRATIC))))
        self.assertEqual(root.tag, MML + "math")
        self.assertEqual(root.get("display"), "block")
        frac = root.find(f".//{MML}mfrac")
        self.assertIsNotNone(frac)
        numerator, denominator = list(frac)
        self.assertIsNotNone(numerator.find(f".//{MML}msqrt//{MML}msup"))
        self.assertEqual([c.tag for c in denominator], [MML + "mn", MML + "mi"])
        self.assertEqual("".join(root.itertext()), "x=-b±b2-4ac2a")

    def test_quadratic_text(self):
        self.assertEqual(mathml.to_text(root_of(QUADRATIC)),
                         QUADRATIC_TEXT)
        self.assertEqual(mathml.to_text(root_of(display(QUADRATIC))), QUADRATIC_TEXT)

    def test_sum_with_limits(self):
        root = parse(mathml.to_mathml(root_of(SUM)))
        under_over = root.find(f".//{MML}munderover")
        self.assertEqual(under_over[0].tag, MML + "mo")
        self.assertEqual(under_over[0].text, "∑")
        self.assertEqual("".join(under_over[1].itertext()), "i=1")
        self.assertEqual(under_over[2].text, "n")
        self.assertIsNotNone(root.find(f".//{MML}msub"))
        self.assertEqual(mathml.to_text(root_of(SUM)), SUM_TEXT)

    def test_integral_puts_limits_beside_the_sign(self):
        body = "<m:nary><m:sub>" + r("0") + "</m:sub><m:sup>" + r("1") + "</m:sup><m:e>" + r("x") + "</m:e></m:nary>"
        root = parse(mathml.to_mathml(omml(body)))
        self.assertEqual(root.find(f".//{MML}msubsup/{MML}mo").text, "∫")

    def test_fraction_with_subscript(self):
        root = parse(mathml.to_mathml(root_of(FRACTION)))
        self.assertEqual(root.find(f".//{MML}mfrac")[0].tag, MML + "msub")
        self.assertEqual(mathml.to_text(root_of(FRACTION)), "x₀ / 2")

    def test_matrix_in_delimiters(self):
        root = parse(mathml.to_mathml(root_of(MATRIX)))
        rows = root.find(f".//{MML}mtable").findall(f"{MML}mtr")
        self.assertEqual([len(row.findall(f"{MML}mtd")) for row in rows], [2, 2])
        self.assertEqual([mo.text for mo in root.iter(MML + "mo")], ["(", ")"])
        self.assertEqual(mathml.to_text(root_of(MATRIX)), "(a, b; c, d)")

    def test_unknown_construct_degrades_to_text(self):
        root = parse(mathml.to_mathml(root_of(UNKNOWN)))
        self.assertEqual("".join(root.itertext()), "hi")
        self.assertIsNotNone(root.find(f".//{MML}mrow/{MML}mtext"))
        self.assertEqual(mathml.to_text(root_of(UNKNOWN)), "hi")

    def test_scripts_radicals_and_friends(self):
        cases = {
            "sSubSup": ("<m:sSubSup><m:e>" + r("x") + "</m:e><m:sub>" + r("1") + "</m:sub><m:sup>" + r("2")
                        + "</m:sup></m:sSubSup>", "msubsup", "x₁²"),
            "sPre": ("<m:sPre><m:sub>" + r("1") + "</m:sub><m:sup>" + r("2") + "</m:sup><m:e>" + r("C")
                     + "</m:e></m:sPre>", "mmultiscripts", "(1,2)C"),
            "rad": ("<m:rad><m:deg>" + r("3") + "</m:deg><m:e>" + r("x") + "</m:e></m:rad>", "mroot", "root 3 of x"),
            "func": ("<m:func><m:fName>" + r("sin") + "</m:fName><m:e>" + r("x") + "</m:e></m:func>", "mi", "sin x"),
            "acc": ("<m:acc><m:e>" + r("x") + "</m:e></m:acc>", "mover", "x̂"),
            "bar": ('<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>' + r("x") + "</m:e></m:bar>", "mover", "x̄"),
            "eqArr": ("<m:eqArr><m:e>" + r("y=1") + "</m:e><m:e>" + r("z=2") + "</m:e></m:eqArr>", "mtable", "y=1; z=2"),
            "limLow": ("<m:limLow><m:e>" + r("lim") + "</m:e><m:lim>" + r("n") + "</m:lim></m:limLow>", "munder", "lim_n"),
            "limUpp": ("<m:limUpp><m:e>" + r("x") + "</m:e><m:lim>" + r("n") + "</m:lim></m:limUpp>", "mover", "x^n"),
            "box": ("<m:box><m:e>" + r("x") + "</m:e></m:box>", "mi", "x"),
            "groupChr": ("<m:groupChr><m:e>" + r("xy") + "</m:e></m:groupChr>", "munder", "xy"),
            "borderBox": ("<m:borderBox><m:e>" + r("x") + "</m:e></m:borderBox>", "menclose", "x"),
        }
        for name, (body, tag, text) in cases.items():
            with self.subTest(name):
                el = omml(body)
                root = parse(mathml.to_mathml(el))
                self.assertIsNotNone(next(root.iter(MML + tag), None), mathml.to_mathml(el))
                self.assertEqual(mathml.to_text(el), text)

    def test_delimiter_characters_and_separators(self):
        body = ('<m:d><m:dPr><m:begChr m:val="["/><m:endChr m:val="]"/><m:sepChr m:val=";"/></m:dPr>'
                "<m:e>" + r("a") + "</m:e><m:e>" + r("b") + "</m:e></m:d>")
        root = parse(mathml.to_mathml(omml(body)))
        self.assertEqual([mo.text for mo in root.iter(MML + "mo")], ["[", ";", "]"])
        self.assertEqual(mathml.to_text(omml(body)), "[a; b]")

    def test_alttext_and_inline(self):
        root = parse(mathml.to_mathml(root_of(FRACTION), alttext="x0 over 2"))
        self.assertEqual(root.get("alttext"), "x0 over 2")
        self.assertIsNone(root.get("display"))


def add_equation(paragraph, xml: str) -> None:
    """Append hand-written OMML to a python-docx paragraph's w:p."""
    from docx.oxml import parse_xml
    paragraph._p.append(parse_xml(etree.tostring(root_of(xml))))


def root_of(xml: str):
    """An lxml element from a full OMML string (``<m:oMath>`` or ``<m:oMathPara>``)."""
    return etree.fromstring(re.sub(r"^<(m:\w+)>", lambda m: f"<{m.group(1)} {NS}>", xml, count=1))


if __name__ == "__main__":
    unittest.main()
