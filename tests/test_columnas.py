"""Seleccion manual de hoja y columnas al importar (Excel con titulos agrupados como la ficha oficial)."""

from models import Docente, Evaluacion, CriterioNorma, DocenteSemestre
from services.excel_service import leer_hoja, mapeo_automatico
from tests.conftest import login

HOJA = "EVALUACION INTEGRAL"


def _subir(client, ficha_xlsx, tipo, escala=None):
    data = {"tipo": tipo, "archivo": (open(ficha_xlsx, "rb"), "ficha.xlsx")}
    if escala:
        data["escala"] = escala
    return client.post("/importar/previsualizar", data=data, content_type="multipart/form-data")


def test_lectura_detecta_titulos_y_grupos(app, ficha_xlsx):
    info = leer_hoja(ficha_xlsx)
    assert info["hoja"] == HOJA and info["fila_titulos"] == 3
    assert info["etiquetas"][3].startswith("D · ENCUESTA ESTUDIANTES")
    assert "CUMPLIMIENTO DE NORMAS" in info["etiquetas"][12] and "AUTOEVALUACION" in info["etiquetas"][13]
    # Hay tres columnas 'NOTA /10': cada tipo toma solo la suya
    assert mapeo_automatico(info["cab"], "encuesta", info["grupos"])["valores"] == [3]
    assert mapeo_automatico(info["cab"], "autoevaluacion", info["grupos"])["valores"] == [13]
    normas = mapeo_automatico(info["cab"], "normas", info["grupos"])
    assert [normas[c] for c in ("reuniones", "silabos", "notas_config", "horas_lectivas", "puntualidad",
                                "subida_notas_erp", "designacion_delegados")] == [4, 5, 6, 7, 8, 9, 10]
    assert normas["nota"] == 12
    assert leer_hoja(ficha_xlsx, "CAPACITACIONES")["cab"][2] == "Nombre de la Capacitacion"


def test_usuario_elige_columnas_del_excel_oficial(client, app, ficha_xlsx):
    login(client, "directora")
    # 1) Docentes: se muestra la pantalla de columnas y el usuario elige B (nombre) y C (modalidad)
    html = _subir(client, ficha_xlsx, "docentes").get_data(as_text=True)
    assert "Elegir la informaci" in html and "B · DATOS" in html
    r = client.post("/importar/columnas", data={"hoja": HOJA, "fila_titulos": "3", "col_nombre": "1", "col_modalidad": "2"})
    assert "Datos a guardar" in r.get_data(as_text=True)
    client.post("/importar/confirmar")
    with app.app_context():
        assert Docente.query.count() == 5          # la fila 'PROMEDIO GENERAL' se ignora
        assert DocenteSemestre.query.filter_by(modalidad="Nombrado").count() == 1

    # 2) Encuesta: el usuario marca solo la columna D
    _subir(client, ficha_xlsx, "encuesta", escala="10")
    client.post("/importar/columnas", data={"hoja": HOJA, "fila_titulos": "3", "col_nombre": "1",
                                            "col_valores": ["3"], "escala": "10"})
    client.post("/importar/confirmar")
    # 3) Un criterio elegido a mano (columna H = horas lectivas)
    _subir(client, ficha_xlsx, "criterio_horas_lectivas", escala="puntaje")
    client.post("/importar/columnas", data={"hoja": HOJA, "fila_titulos": "3", "col_nombre": "1",
                                            "col_valores": ["7"], "escala": "puntaje"})
    client.post("/importar/confirmar")
    with app.app_context():
        doc = Docente.buscar_por_nombre("ACURIO GUTIERREZ MARIA ISABEL")
        assert Evaluacion.query.filter_by(docente_id=doc.id).one().encuesta == 8.24
        assert CriterioNorma.query.filter_by(docente_id=doc.id).one().horas_lectivas == 16.67
        malo = Docente.buscar_por_nombre("MAL DATO PRUEBA")
        assert Evaluacion.query.filter_by(docente_id=malo.id).one().encuesta is None   # 12 > 10 se rechaza


def test_cambiar_de_hoja_y_sin_identificacion(client, app, ficha_xlsx):
    login(client, "directora")
    _subir(client, ficha_xlsx, "encuesta")
    html = client.get(f"/importar/columnas?hoja=RANKING&fila_titulos=1").get_data(as_text=True)
    assert 'Muestra de la hoja "' in html
    r = client.post("/importar/columnas", data={"hoja": HOJA, "fila_titulos": "3", "col_valores": ["3"]})
    assert "Indique la columna con los apellidos" in r.get_data(as_text=True)
