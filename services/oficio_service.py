"""Oficio del DAIS al Decanato con la propuesta de asesor/dictaminantes en orden de prelacion (Art. 71, 97)."""

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from services.utils_texto import fecha_larga

AZUL = RGBColor(0x12, 0x30, 0x5A)


def _titulo(doc, texto, tam=12, centro=True):
    p = doc.add_paragraph()
    if centro:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(texto)
    r.bold = True
    r.font.size = Pt(tam)
    r.font.color.rgb = AZUL
    return p


def generar_oficio(tesis, rol="dictaminante"):
    """Devuelve (BytesIO, nombre_archivo)."""
    miembros = [m for m in tesis.miembros if m.rol == rol and m.activo]
    miembros.sort(key=lambda m: m.docente.clave_prelacion)
    etapa = "del proyecto de tesis" if tesis.etapa in ("asesor", "proyecto") else "de la tesis"
    if tesis.modalidad == "suficiencia":
        etapa = "del trabajo de suficiencia profesional"

    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(11)

    _titulo(doc, "UNIVERSIDAD ANDINA DEL CUSCO", 13)
    _titulo(doc, "DEPARTAMENTO ACADÉMICO DE INGENIERÍA DE SISTEMAS", 11)
    doc.add_paragraph()
    p = doc.add_paragraph(f"Cusco, {fecha_larga(date.today())}")
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph("OFICIO N.° ____-2026-DAIS-FI-UAC").runs[0].bold = True
    doc.add_paragraph("Señor(a):\nDecano(a) de la Facultad de Ingeniería y Arquitectura\nPresente.-")

    rol_txt = {"dictaminante": "dictaminantes", "asesor": "asesor", "dirimente": "docente dirimente",
               "replicante": "replicantes"}.get(rol, rol)
    asunto = doc.add_paragraph()
    asunto.add_run("Asunto: ").bold = True
    asunto.add_run(f"Propuesta de {rol_txt} {etapa} {tesis.codigo}")

    tesistas = ", ".join(e.nombre_completo.upper() for e in tesis.estudiantes)
    doc.add_paragraph(
        "Tengo el agrado de dirigirme a usted para proponer, conforme al Reglamento Marco para obtener el "
        "Grado Académico de Bachiller y el Título Profesional (Res. N.° 256-CU-2024-UAC), a los docentes "
        f"{'que se indican' if len(miembros) > 1 else 'que se indica'}, considerando la naturaleza del tema de "
        "investigación, la disponibilidad docente y el orden de prelación (categoría docente, antigüedad en la "
        "Universidad, antigüedad en la colegiatura y años de experiencia profesional)."
    )

    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for etiqueta, valor in [
        ("Título", tesis.titulo),
        ("Tesista(s)", tesistas or "-"),
        ("Modalidad", tesis.modalidad_nombre),
        ("Línea de investigación", tesis.linea.nombre if tesis.linea else "-"),
        ("Asesor", tesis.asesor.docente.nombre_natural.upper() if tesis.asesor else "-"),
    ]:
        fila = t.add_row().cells
        fila[0].text, fila[1].text = etiqueta, valor
        fila[0].paragraphs[0].runs[0].bold = True
    doc.add_paragraph()

    tabla = doc.add_table(rows=1, cols=4)
    tabla.style = "Table Grid"
    for i, h in enumerate(["Prelación", "Docente", "Categoría", "Rol en la sustentación" if rol == "dictaminante" else "Rol"]):
        tabla.rows[0].cells[i].text = h
        tabla.rows[0].cells[i].paragraphs[0].runs[0].bold = True
    for i, m in enumerate(miembros, start=1):
        rol_sust = m.rol_nombre
        if rol == "dictaminante" and len(miembros) >= 3:
            rol_sust = "Presidente" if i == 1 else ("Secretario(a) de actas" if i == len(miembros) else "Miembro")
        fila = tabla.add_row().cells
        fila[0].text = str(i)
        fila[1].text = f"{m.docente.grado_academico + ' ' if m.docente.grado_academico else ''}{m.docente.nombre_natural.upper()}"
        fila[2].text = m.docente.categoria_docente or "-"
        fila[3].text = rol_sust
    doc.add_paragraph()
    doc.add_paragraph("Sin otro particular, hago propicia la ocasión para expresarle las muestras de mi especial consideración.")
    doc.add_paragraph("\n\nAtentamente,\n\n\n______________________________\nDirector(a) del Departamento Académico de Ingeniería de Sistemas")

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf, f"OFICIO_PROPUESTA_{rol.upper()}_{tesis.codigo}.docx"
