"""Build test fixtures (PNG, DOCX, PDF) in code so no binary files live in the repo."""

import io

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from PIL import Image, ImageDraw


def make_png(w=200, h=120, color=(30, 120, 200), mode="RGB", fmt="PNG") -> bytes:
    img = Image.new(mode, (w, h), color)
    ImageDraw.Draw(img).rectangle(
        [w // 4, h // 4, w // 2, h // 2], fill="white" if mode == "RGB" else None
    )
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def add_picture(paragraph, png: bytes, alt: str | None = None):
    shape = paragraph.add_run().add_picture(io.BytesIO(png))
    if alt:
        shape._inline.docPr.set("descr", alt)
    return shape


_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _inline(graphic: str) -> str:
    return (
        f'<w:drawing {_NS}><wp:inline><wp:extent cx="914400" cy="914400"/>'
        f'<wp:docPr id="99" name="obj"/><a:graphic>{graphic}</a:graphic></wp:inline></w:drawing>'
    )


def add_raw_image(doc, paragraph, blob: bytes, content_type: str, name="image9.emf"):
    """Attach an image part python-docx can't create itself (e.g. EMF)."""
    part = Part(PackURI(f"/word/media/{name}"), content_type, blob, doc.part.package)
    rid = doc.part.relate_to(part, RT.IMAGE)
    graphic = (
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:blipFill><a:blip r:embed="{rid}"/></pic:blipFill></pic:pic></a:graphicData>'
    )
    paragraph.add_run()._r.append(parse_xml(_inline(graphic)))


CHART_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:chart>
<c:title><c:tx><c:rich><a:p><a:r><a:t>停机时间</a:t></a:r></a:p></c:rich></c:tx></c:title>
<c:plotArea><c:barChart>
<c:ser><c:tx><c:strRef><c:strCache><c:pt idx="0"><c:v>2023</c:v></c:pt></c:strCache>
</c:strRef></c:tx>
<c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>Q1</c:v></c:pt><c:pt idx="1"><c:v>Q2</c:v></c:pt>
</c:strCache></c:strRef></c:cat>
<c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>12</c:v></c:pt><c:pt idx="1"><c:v>8</c:v></c:pt>
</c:numCache></c:numRef></c:val></c:ser>
</c:barChart></c:plotArea></c:chart></c:chartSpace>"""


def add_chart(doc, paragraph, xml: str = CHART_XML):
    ct = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
    part = Part(PackURI("/word/charts/chart1.xml"), ct, xml.encode(), doc.part.package)
    rid = doc.part.relate_to(part, RT.CHART)
    graphic = (
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
        f'<c:chart r:id="{rid}"/></a:graphicData>'
    )
    paragraph.add_run()._r.append(parse_xml(_inline(graphic)))


def new_docx():
    return Document()
