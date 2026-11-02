import shutil

from models import db, Docente, Evaluacion, CriterioNorma, Capacitacion, Investigacion, Semestre, normalizar_nombre, clasificar
from services.excel_service import importar_ficha_integral, analizar_ficha_integral, dividir_nombre
from services.evaluacion_service import calcular_ranking, analisis_docente
from services.ficha_service import construir_mapeo, generar_docx_bytes


def _importar(ficha_xlsx):
    sem = Semestre.query.first()
    return sem, importar_ficha_integral(ficha_xlsx, sem.id, None)


def test_normalizacion_independiente_del_orden():
    assert normalizar_nombre("ACURIO GUTIERREZ MARIA ISABEL") == normalizar_nombre("María Isabel Acurio Gutiérrez")


def test_dividir_nombre_con_particulas():
    assert dividir_nombre("CUBA DEL CASTILLO MARIA YORNET") == ("Maria Yornet", "Cuba Del Castillo")
    assert dividir_nombre("ACURIO GUTIERREZ MARIA ISABEL") == ("Maria Isabel", "Acurio Gutierrez")


def test_clasificacion_por_umbral():
    assert clasificar(9.2) == "Excelente"
    assert clasificar(8.0) == "Muy Bueno"
    assert clasificar(7.47) == "Bueno"
    assert clasificar(None) is None


def test_analisis_rechaza_fuera_de_rango_e_ignora_totales(app, ficha_xlsx):
    a = analizar_ficha_integral(ficha_xlsx)
    assert a["error"] is None
    assert len(a["registros"]) == 4
    assert [r["nombre"] for r in a["rechazados"]] == ["MAL DATO PRUEBA"]
    assert len(a["capacitaciones"]) == 2          # "No tiene" se descarta
    assert len(a["investigaciones"]) == 1


def test_importacion_completa_y_reimportacion_sin_duplicados(app, ficha_xlsx):
    sem, res = _importar(ficha_xlsx)
    assert res["importados"] == 4 and res["rechazados"] == 1
    assert res["capacitaciones"] == 2 and res["investigaciones"] == 1
    acurio = Docente.buscar_por_nombre("Maria Isabel Acurio Gutierrez")
    ev = Evaluacion.query.filter_by(docente_id=acurio.id).one()
    assert ev.promedio_final == 9.2878 and ev.clasificacion == "Excelente"
    crit = CriterioNorma.query.filter_by(docente_id=acurio.id).one()
    assert crit.subtotal_normas == 99.795

    # Editar el nombre (otro orden / tildes) no debe provocar duplicados al reimportar
    acurio.nombres = "María Isabel"
    db.session.commit()
    copia = ficha_xlsx.replace("ficha.xlsx", "ficha2.xlsx")
    shutil.copyfile(ficha_xlsx, copia)
    res2 = importar_ficha_integral(copia, sem.id, None)
    assert res2["importados"] == 0 and res2["actualizados"] == 4
    assert Docente.query.count() == 4
    assert Capacitacion.query.count() == 2 and Investigacion.query.count() == 1


def test_ranking_con_empates_comparte_puesto(app, ficha_xlsx):
    sem, _ = _importar(ficha_xlsx)
    ranking = calcular_ranking(sem.id)
    puestos = [(r["docente"].apellidos, r["posicion"]) for r in ranking]
    assert puestos[0] == ("Cuba Del Castillo", 1)
    assert puestos[1] == ("Acurio Gutierrez", 2)
    assert [p for _, p in puestos[2:]] == [3, 3]   # empate exacto


def test_analisis_puntos_de_mejora(app, ficha_xlsx):
    sem, _ = _importar(ficha_xlsx)
    doc = Docente.buscar_por_nombre("ARDILES ROMERO VELIA")
    a = analisis_docente(doc.id, sem.id)
    assert a["puesto"] == 3 and a["total"] == 4
    claves = [m["clave"] for m in a["mejoras"]]
    assert claves[0] == "horas_lectivas" or claves[0] == "encuesta"
    assert "reuniones" in claves and "silabos" not in claves
    assert any(f["clave"] == "autoevaluacion" for f in a["fortalezas"])
    assert a["siguiente_clasificacion"] == "Excelente"
    assert a["max_alcanzable"] <= 10


def test_ficha_word_completa(app, ficha_xlsx):
    sem, _ = _importar(ficha_xlsx)
    doc = Docente.buscar_por_nombre("ACURIO GUTIERREZ MARIA ISABEL")
    ctx = construir_mapeo(doc.id, sem.id)
    assert ctx["mapping"]["POSICION"] == "2 de 4"
    assert "Power BI Avanzado" in ctx["mapping"]["CAPACITACIONES"]
    assert "Modelamiento de indicadores" in ctx["mapping"]["PUBLICACIONES"]
    buffer, nombre, _ = generar_docx_bytes(doc.id, sem.id)
    assert nombre.startswith("FICHA_ACURIO_GUTIERREZ") and buffer.getbuffer().nbytes > 10000
