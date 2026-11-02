"""Plantillas Excel para cada paso del proceso de evaluacion (con los docentes ya listados)."""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from models import DocenteSemestre, Docente, CRITERIOS_NORMA
from services.excel_service import tipo_criterio, MAX_CRITERIO, ETIQUETA_CRITERIO

AZUL = PatternFill("solid", fgColor="12305A")
GRIS = PatternFill("solid", fgColor="EEF2F7")
BORDE = Border(*(Side(style="thin", color="C9D3E0"),) * 4)
CORTO = {
    "reuniones": "REUNIONES", "silabos": "SILABOS", "notas_config": "NOTAS/CONFIG",
    "horas_lectivas": "HORAS LECTIVAS", "puntualidad": "PUNTUALIDAD",
    "subida_notas_erp": "ERP", "designacion_delegados": "DELEGADOS",
}


def _columnas(tipo, escala):
    campo = tipo_criterio(tipo)
    if tipo == "docentes":
        return ["CODIGO", "APELLIDOS", "NOMBRES", "DNI", "CORREO", "MODALIDAD", "GRADO ACADEMICO",
                "CATEGORIA", "CONDICION", "AÑO DE INGRESO", "AÑO DE COLEGIATURA", "AÑOS DE EXPERIENCIA"], None
    if tipo == "encuesta":
        return ["CODIGO", "APELLIDOS Y NOMBRES", "ENCUESTA SEMESTRE I (/10)", "ENCUESTA SEMESTRE II (/10)"], (0, 10)
    if tipo == "autoevaluacion":
        return ["CODIGO", "APELLIDOS Y NOMBRES", "AUTOEVALUACION SEMESTRE I (/10)", "AUTOEVALUACION SEMESTRE II (/10)"], (0, 10)
    if campo:
        maximo = MAX_CRITERIO[campo]
        if escala == "porcentaje":
            return ["CODIGO", "APELLIDOS Y NOMBRES", f"{CORTO[campo]} - CUMPLIMIENTO (%)"], (0, 100)
        return ["CODIGO", "APELLIDOS Y NOMBRES", f"{CORTO[campo]} - PUNTAJE (0-{maximo})"], (0, maximo)
    if tipo == "normas":
        return ["CODIGO", "APELLIDOS Y NOMBRES"] + [f"{CORTO[c]} ({m})" for c, _, m in CRITERIOS_NORMA], None
    raise ValueError("Tipo de plantilla no valido")


def generar_plantilla(tipo, semestre, escala=None):
    """Devuelve (BytesIO, nombre_archivo)."""
    cols, rango = _columnas(tipo, escala)
    wb = Workbook()
    ws = wb.active
    ws.title = "DATOS"
    ws.append(cols)
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = AZUL
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        celda.border = BORDE
    ws.row_dimensions[1].height = 34

    docentes = (
        Docente.query.join(DocenteSemestre).filter(DocenteSemestre.semestre_id == semestre.id)
        .order_by(Docente.apellidos, Docente.nombres).all()
    )
    modalidades = {p.docente_id: p.modalidad for p in DocenteSemestre.query.filter_by(semestre_id=semestre.id)}
    for d in docentes:
        if tipo == "docentes":
            ws.append([d.codigo, d.apellidos.upper(), d.nombres.upper(), d.dni or "", d.correo_institucional or "",
                       modalidades.get(d.id) or "", d.grado_academico or "", d.categoria_docente or "",
                       (d.condicion or "").capitalize(), d.anio_ingreso or "", d.colegiatura_anio or "",
                       d.experiencia_anios if d.experiencia_anios is not None else ""])
        else:
            ws.append([d.codigo, f"{d.apellidos} {d.nombres}".upper()] + [None] * (len(cols) - 2))

    anchos = {"CODIGO": 12, "APELLIDOS Y NOMBRES": 42, "APELLIDOS": 26, "NOMBRES": 24, "CORREO": 30}
    for i, c in enumerate(cols, start=1):
        letra = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[letra].width = anchos.get(c, 20)
    for fila in ws.iter_rows(min_row=2, max_row=max(ws.max_row, 2)):
        for celda in fila:
            celda.border = BORDE
        for celda in fila[:2]:
            celda.fill = GRIS
    ws.freeze_panes = "C2"

    if rango:
        dv = DataValidation(type="decimal", operator="between", formula1=str(rango[0]), formula2=str(rango[1]),
                            showErrorMessage=True, errorTitle="Valor fuera de rango",
                            error=f"Ingrese un numero entre {rango[0]} y {rango[1]}.")
        ws.add_data_validation(dv)
        dv.add(f"C2:{ws.cell(row=1, column=len(cols)).column_letter}{max(len(docentes), 1) + 200}")
    elif tipo == "normas":
        for i, (c, _, maximo) in enumerate(CRITERIOS_NORMA, start=3):
            letra = ws.cell(row=1, column=i).column_letter
            dv = DataValidation(type="decimal", operator="between", formula1="0", formula2=str(maximo),
                                showErrorMessage=True, error=f"Puntaje entre 0 y {maximo}.")
            ws.add_data_validation(dv)
            dv.add(f"{letra}2:{letra}{max(len(docentes), 1) + 200}")

    ayuda = wb.create_sheet("INSTRUCCIONES")
    lineas = _instrucciones(tipo, escala)
    for linea in lineas:
        ayuda.append([linea])
    ayuda.column_dimensions["A"].width = 110
    ayuda["A1"].font = Font(bold=True, size=13, color="12305A")

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, f"PLANTILLA_{tipo.upper()}_{semestre.codigo}.xlsx"


def _instrucciones(tipo, escala):
    base = [
        "Instrucciones de llenado",
        "",
        "- No cambie los titulos de las columnas. El sistema reconoce al docente por CODIGO o por APELLIDOS Y NOMBRES.",
        "- Puede agregar filas: si un docente aparece varias veces (por ejemplo, una fila por curso), sus valores se promedian.",
        "- Deje la celda vacia si no tiene el dato; nunca escriba texto en las columnas de notas.",
    ]
    campo = tipo_criterio(tipo)
    if tipo in ("encuesta", "autoevaluacion"):
        base.append("- Complete la nota de cada semestre (0 a 10). El sistema promedia ambos semestres. Si solo tiene un semestre, deje el otro vacio.")
    elif campo:
        maximo = MAX_CRITERIO[campo]
        base.append(f"- Criterio: {ETIQUETA_CRITERIO[campo]} (peso {maximo} de 100 en cumplimiento de normas).")
        if escala == "porcentaje":
            base.append(f"- Escriba el porcentaje de cumplimiento (0 a 100). El sistema lo convierte a puntaje sobre {maximo}.")
        else:
            base.append(f"- Escriba el puntaje obtenido (0 a {maximo}).")
    elif tipo == "normas":
        base.append("- Escriba el puntaje de cada criterio sobre su peso. La nota de normas es la suma (sobre 100) dividida entre 10.")
    elif tipo == "docentes":
        base.append("- Liste a todos los docentes que se evaluaran en el semestre. CODIGO, APELLIDOS y NOMBRES son obligatorios.")
    return base
