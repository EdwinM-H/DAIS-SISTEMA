"""Proceso de evaluacion paso a paso: docentes -> encuesta -> criterios -> autoevaluacion -> calculo."""

import io

import openpyxl

from models import db, Docente, Evaluacion, CriterioNorma, Semestre, CRITERIOS_NORMA
from tests.conftest import login

DOCENTES = [("DOC-0101", "QUISPE LOPEZ", "ANA"), ("DOC-0102", "HUAMAN ROJAS", "LUIS"), ("DOC-0103", "CUBA DEL CASTILLO", "ROSA")]


def _xlsx(filas):
    wb = openpyxl.Workbook()
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _importar(client, tipo, filas, escala=None):
    data = {"tipo": tipo, "archivo": (_xlsx(filas), f"{tipo}.xlsx")}
    if escala:
        data["escala"] = escala
    r = client.post("/importar/previsualizar", data=data, content_type="multipart/form-data")
    assert r.status_code == 200, r.data[:300]
    r = client.post("/importar/confirmar")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def _cargar_docentes(client):
    _importar(client, "docentes", [["CODIGO", "APELLIDOS", "NOMBRES", "MODALIDAD"]] + [[c, a, n, "Contratado"] for c, a, n in DOCENTES])


def test_proceso_completo(client, app):
    login(client, "directora")
    _cargar_docentes(client)
    with app.app_context():
        assert Docente.query.count() == 3

    # Encuesta: dos semestres en columnas + filas repetidas por curso, escala /20
    _importar(client, "encuesta", [
        ["CODIGO", "APELLIDOS Y NOMBRES", "ENCUESTA SEMESTRE I", "ENCUESTA SEMESTRE II"],
        ["DOC-0101", "", 16, 18],             # (16+18)/2 = 17 -> 8.5
        [None, "LUIS HUAMAN ROJAS", 14, None],  # se reconoce por nombre en otro orden
        [None, "HUAMAN ROJAS LUIS", 16, None],  # segunda fila del mismo docente -> 15 -> 7.5
        [None, "ROSA CUBA DEL CASTILLO", 20, 20],
        [None, "DOCENTE INEXISTENTE", 15, 15],
    ], escala="20")
    with app.app_context():
        evs = {e.docente.codigo: e for e in Evaluacion.query.all()}
        assert evs["DOC-0101"].encuesta == 8.5 and evs["DOC-0102"].encuesta == 7.5 and evs["DOC-0103"].encuesta == 10
        assert evs["DOC-0101"].promedio_final is None          # aun no hay resultados

    # Criterios de normas uno por uno (puntualidad en porcentaje)
    for campo, _, maximo in CRITERIOS_NORMA:
        if campo == "puntualidad":
            _importar(client, f"criterio_{campo}", [["CODIGO", "CUMPLIMIENTO (%)"], ["DOC-0101", 100], ["DOC-0102", 50], ["DOC-0103", 80]], escala="porcentaje")
        else:
            _importar(client, f"criterio_{campo}", [["CODIGO", "PUNTAJE"]] + [[c, maximo] for c, _, _ in DOCENTES], escala="puntaje")
    with app.app_context():
        crit = CriterioNorma.query.join(Docente).filter(Docente.codigo == "DOC-0102").one()
        assert crit.puntualidad == 7.5 and crit.subtotal_normas == 92.5   # 50% de 15

    # Un puntaje mayor al peso del criterio se rechaza
    html = _importar(client, "criterio_reuniones", [["CODIGO", "PUNTAJE"], ["DOC-0101", 40]], escala="puntaje")
    assert "fuera de rango" in html

    # Falta autoevaluacion de un docente -> no se puede calcular sin excluir
    _importar(client, "autoevaluacion", [["CODIGO", "AUTOEVALUACION"], ["DOC-0101", 10], ["DOC-0102", 9]], escala="10")
    r = client.post("/evaluacion/calcular", data={}, follow_redirects=True)
    assert "Faltan datos de 1 docente" in r.get_data(as_text=True)
    with app.app_context():
        assert Semestre.query.first().estado_resultados == "pendiente"

    _importar(client, "autoevaluacion", [["CODIGO", "AUTOEVALUACION"], ["DOC-0103", 8]], escala="10")
    client.post("/evaluacion/calcular", data={})
    with app.app_context():
        sem = Semestre.query.first()
        assert sem.estado_resultados == "vigente"
        ev = Evaluacion.query.join(Docente).filter(Docente.codigo == "DOC-0102").one()
        assert ev.normas == 9.25 and ev.promedio_final == round(7.5 * .4 + 9.25 * .4 + 9 * .2, 4)
        assert ev.clasificacion == "Muy Bueno"

    # Cargar datos despues del calculo deja los resultados desactualizados
    _importar(client, "autoevaluacion", [["CODIGO", "AUTOEVALUACION"], ["DOC-0103", 9]], escala="10")
    with app.app_context():
        assert Semestre.query.first().estado_resultados == "desactualizado"
    r = client.post(f"/semestres/{1}/publicar", follow_redirects=True)
    assert "Primero calcule" in r.get_data(as_text=True)
    assert "desactualizado" in client.get("/ranking").get_data(as_text=True)


def test_calcular_excluyendo_incompletos(client, app):
    login(client, "directora")
    _cargar_docentes(client)
    _importar(client, "encuesta", [["CODIGO", "NOTA"], ["DOC-0101", 9]], escala="10")
    _importar(client, "normas", [["CODIGO", "REUNIONES", "SILABOS", "NOTAS/CONFIG", "HORAS LECTIVAS", "PUNTUALIDAD", "ERP", "DELEGADOS"],
                                 ["DOC-0101", 15, 20, 15, 20, 15, 10, 5]], escala="puntaje")
    _importar(client, "autoevaluacion", [["CODIGO", "NOTA"], ["DOC-0101", 10]], escala="10")
    client.post("/evaluacion/calcular", data={"excluir": "1"})
    with app.app_context():
        finales = {e.docente.codigo: e.promedio_final for e in Evaluacion.query.all()}
        assert finales == {"DOC-0101": 9.6}


def test_plantillas_se_pueden_reimportar(client, app):
    login(client, "directora")
    _cargar_docentes(client)
    for tipo in ["docentes", "encuesta", "autoevaluacion", "normas"] + [f"criterio_{c}" for c, _, _ in CRITERIOS_NORMA]:
        r = client.get(f"/importar/plantilla/{tipo}")
        assert r.status_code == 200 and r.data[:2] == b"PK", tipo
    # La plantilla de encuesta, llenada, se importa sin cambios de formato
    wb = openpyxl.load_workbook(io.BytesIO(client.get("/importar/plantilla/encuesta").data))
    ws = wb["DATOS"]
    for fila in ws.iter_rows(min_row=2):
        fila[2].value, fila[3].value = 8, 9
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    client.post("/importar/previsualizar", data={"tipo": "encuesta", "escala": "10", "archivo": (buf, "e.xlsx")},
                content_type="multipart/form-data")
    client.post("/importar/confirmar")
    with app.app_context():
        assert sorted(e.encuesta for e in Evaluacion.query.all()) == [8.5, 8.5, 8.5]
    assert "Proceso de evaluación" in client.get("/evaluacion/proceso").get_data(as_text=True)
