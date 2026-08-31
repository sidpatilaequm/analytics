"""exporters.py — turn one report's computed results into a PDF, a PPTX, or
an XLSX. All three read the exact same normalized structure (see
`app.py:_render_boxes`), so a box that's wrong in one format is wrong (and
fixable) in exactly one place, not three.
"""

import io
import re


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def build_pdf(name, sections):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40, bottomMargin=40,
                             leftMargin=40, rightMargin=40)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=20)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=16, fontSize=14)
    body = styles["BodyText"]
    value_style = ParagraphStyle("V", parent=body, fontSize=16, spaceAfter=2)
    note_style = ParagraphStyle("N", parent=body, fontSize=9, textColor=colors.grey)
    err_style = ParagraphStyle("E", parent=body, textColor=colors.HexColor("#9E332B"))

    story = [Paragraph(_esc(name), title_style), Spacer(1, 10)]

    for sec in sections:
        story.append(Paragraph(_esc(sec["name"]), h2))
        if sec.get("desc"):
            story.append(Paragraph(_esc(sec["desc"]), body))
        story.append(Spacer(1, 6))
        for box in sec["boxes"]:
            story.append(Paragraph(f"<b>{_esc(box['title'] or 'Untitled')}</b>", body))
            if box.get("error"):
                story.append(Paragraph(_esc(box["error"]), err_style))
            elif box["kind"] == "value":
                story.append(Paragraph(_esc(box.get("text", "—")), value_style))
                if box.get("note"):
                    story.append(Paragraph(_esc(box["note"]), note_style))
            elif box["kind"] in ("chart", "table") and box.get("rows"):
                rows = [[_cell(v) for v in r] for r in box["rows"]]
                t = Table(rows, hAlign="LEFT")
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7ECEA")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DDDA")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]))
                story.append(t)
            elif box["kind"] == "note" and box.get("text"):
                story.append(Paragraph(_esc(box["text"]), body))
            story.append(Spacer(1, 10))
        story.append(Spacer(1, 14))

    doc.build(story)
    return buf.getvalue()


def _esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;") \
        .replace("<", "&lt;").replace(">", "&gt;")


def _cell(v):
    return "—" if v is None else str(v)


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------
def build_pptx(name, sections):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(2.9), Inches(12), Inches(1.5))
    p = tb.text_frame.paragraphs[0]
    p.text = name
    p.font.size = Pt(40)
    p.font.bold = True

    for sec in sections:
        slide = prs.slides.add_slide(blank)
        title = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.8))
        tp = title.text_frame.paragraphs[0]
        tp.text = sec["name"]
        tp.font.size = Pt(28)
        tp.font.bold = True

        y = 1.3
        for box in sec["boxes"]:
            if y > 6.6:
                slide = prs.slides.add_slide(blank)
                y = 0.5

            if box.get("error"):
                tb = slide.shapes.add_textbox(Inches(0.5), Inches(y), Inches(12), Inches(0.6))
                tb.text_frame.text = f"{box['title']}: {box['error']}"
                y += 0.7
                continue

            if box["kind"] == "value":
                vb = slide.shapes.add_textbox(Inches(0.5), Inches(y), Inches(5.8), Inches(1.3))
                tf = vb.text_frame
                tf.word_wrap = True
                tf.paragraphs[0].text = box["title"] or ""
                tf.paragraphs[0].font.size = Pt(12)
                tf.paragraphs[0].font.color.rgb = RGBColor(0x5A, 0x66, 0x63)
                p2 = tf.add_paragraph()
                p2.text = box.get("text", "—")
                p2.font.size = Pt(30)
                p2.font.bold = True
                y += 1.4

            elif box["kind"] in ("chart", "table") and box.get("rows"):
                rows = box["rows"][:13]  # keep one slide readable
                r, c = len(rows), max(len(x) for x in rows)
                label = slide.shapes.add_textbox(Inches(0.5), Inches(y), Inches(6), Inches(0.4))
                label.text_frame.text = box["title"] or ""
                label.text_frame.paragraphs[0].font.bold = True
                y += 0.45
                height = min(0.32 * r, 4.8)
                shape = slide.shapes.add_table(r, c, Inches(0.5), Inches(y),
                                                Inches(12.3), Inches(height))
                tbl = shape.table
                for ri in range(r):
                    for ci in range(c):
                        v = rows[ri][ci] if ci < len(rows[ri]) else None
                        cell = tbl.cell(ri, ci)
                        cell.text = "—" if v is None else str(v)
                        cell.text_frame.paragraphs[0].font.size = Pt(11)
                y += height + 0.35

            elif box.get("text"):
                nb = slide.shapes.add_textbox(Inches(0.5), Inches(y), Inches(12.3), Inches(1))
                nb.text_frame.word_wrap = True
                nb.text_frame.text = f"{box['title']}: {box['text']}" if box["title"] else box["text"]
                y += 1

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# XLSX
# --------------------------------------------------------------------------
def build_xlsx(name, sections):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    wb.remove(wb.active)
    used = set()

    for sec in sections:
        base = re.sub(r"[\[\]\*\?/\\:]", "", sec["name"] or "Section")[:28] or "Section"
        sheet_name, i = base, 2
        while sheet_name in used:
            sheet_name = f"{base[:26]}-{i}"
            i += 1
        used.add(sheet_name)
        ws = wb.create_sheet(sheet_name)

        row = 1
        for box in sec["boxes"]:
            ws.cell(row=row, column=1, value=box["title"] or "Untitled").font = Font(bold=True)
            row += 1
            if box.get("error"):
                ws.cell(row=row, column=1, value=f"Error: {box['error']}")
                row += 2
                continue
            if box["kind"] == "value":
                ws.cell(row=row, column=1, value=box.get("text", "—"))
                if box.get("note"):
                    ws.cell(row=row, column=2, value=box["note"])
                row += 2
            elif box["kind"] in ("chart", "table") and box.get("rows"):
                for ri, r in enumerate(box["rows"]):
                    for ci, v in enumerate(r):
                        cell = ws.cell(row=row + ri, column=1 + ci, value=v)
                        if ri == 0:
                            cell.font = Font(bold=True)
                            cell.fill = PatternFill("solid", fgColor="E7ECEA")
                row += len(box["rows"]) + 2
            elif box.get("text"):
                ws.cell(row=row, column=1, value=box["text"])
                row += 2
        for col in range(1, 9):
            ws.column_dimensions[chr(64 + col)].width = 22

    if not wb.sheetnames:
        wb.create_sheet("Report")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()