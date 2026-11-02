"""Proceso de tesis segun el Reglamento Marco 256-CU-2024-UAC y asignacion automatica."""

import io
import re
from datetime import date, datetime, timedelta

import pytest

from models import db, Docente, Tesis, TesisMiembro, Dictamen, Feriado, Semestre, CambioPerfil, Estudiante
from services import tesis_service, asignacion_service, calendario, perfil_service
from services.cuentas_service import crear_cuenta_docente
from tests.conftest import login

PDF = b"%PDF-1.4 prueba"


def _docente(codigo, nombres, apellidos, categoria="Asociado", ingreso=2010, colegiatura=2008, experiencia=10, temas=()):
    d = Docente(codigo=codigo, nombres=nombres, apellidos=apellidos, categoria_docente=categoria,
                anio_ingreso=ingreso, colegiatura_anio=colegiatura, experiencia_anios=experiencia, grado_academico="Maestro")
    d.temas = list(temas)
    d.lineas = list({t.linea for t in temas})
    db.session.add(d)
    db.session.flush()
    u, _ = crear_cuenta_docente(d)
    u.set_password("Docente2026")
    u.debe_cambiar_password = False
    return d


@pytest.fixture()
def plana(app, catalogo):
    t = catalogo["temas"]
    docentes = {
        "asesor": _docente("D01", "Ana", "Asesora Uno", "Principal", 2000, 1995, 25, [t["ml"]]),
        "ml1": _docente("D02", "Beto", "Datos Dos", "Asociado", 2005, 2003, 15, [t["ml"]]),
        "ml2": _docente("D03", "Carla", "Datos Tres", "Principal", 2012, 2010, 12, [t["ml"], t["bi"]]),
        "bi": _docente("D04", "Dante", "Negocios Cuatro", "Auxiliar", 2015, 2014, 8, [t["bi"]]),
        "itil": _docente("D05", "Elsa", "Gestion Cinco", "Contratado", 2018, 2016, 6, [t["itil"]]),
        "auto": _docente("D06", "Fito", "Software Seis", "Contratado", 2016, 2012, 9, [t["auto"]]),
    }
    decano = _docente("D07", "Gina", "Decana Siete", "Principal", 1995, 1990, 30, [t["ml"]])
    decano.es_autoridad, decano.cargo_autoridad = True, "Decano"
    licencia = _docente("D08", "Hugo", "Licencia Ocho", "Principal", 1998, 1994, 28, [t["ml"]])
    licencia.licencia_desde, licencia.licencia_hasta = date.today() - timedelta(days=5), date.today() + timedelta(days=60)
    db.session.commit()
    return docentes


def _tesis(app, catalogo, usuario_id=1, modalidad="tesis"):
    est = Estudiante(codigo="020100", nombres="Carla", apellidos="Mamani Huaman")
    tesis = Tesis(codigo="TES-2026-0001", titulo="Modelo de machine learning para predecir la desercion estudiantil",
                  modalidad=modalidad, etapa="asesor", fecha_registro=date.today(), palabras_clave="desercion, prediccion")
    tesis.linea = catalogo["lineas"]["datos"]
    tesis.area_id = catalogo["lineas"]["datos"].area_id
    tesis.temas = [catalogo["temas"]["ml"]]
    tesis.estudiantes = [est]
    db.session.add(tesis)
    db.session.commit()
    return tesis


def _usuario(docente):
    return docente.usuario


# ----------------------------------------------------------------------
# Reglas puras
# ----------------------------------------------------------------------
def test_nota_final_descarta_discordante_y_redondea_a_favor():
    assert tesis_service.calcular_nota_final([15, 16, 10]) == (16, [10.0])     # 10 difiere en 5 de 15
    assert tesis_service.calcular_nota_final([14, 15, 15]) == (15, [])         # 14.67 -> 15
    assert tesis_service.calcular_nota_final([14, 15]) == (15, [])             # 14.5 -> 15 (a favor)
    assert tesis_service.calificacion_texto(13) == "Desaprobado"
    assert tesis_service.calificacion_texto(17) == "Aprobado con distinción"
    assert tesis_service.calificacion_texto(19).startswith("Aprobado con excelencia")


def test_dias_habiles_excluyen_fines_de_semana_feriados_y_vacaciones(app):
    lunes = date(2026, 9, 7)
    assert calendario.sumar_habiles(lunes, 5) == date(2026, 9, 14)            # salta sabado y domingo
    db.session.add(Feriado(fecha=date(2026, 9, 9), descripcion="Feriado"))
    db.session.commit()
    assert calendario.sumar_habiles(lunes, 5) == date(2026, 9, 15)
    sem = Semestre.query.first()
    sem.fecha_inicio, sem.fecha_fin = date(2026, 8, 17), date(2026, 9, 11)     # despues: vacaciones
    otro = Semestre.crear(2027, "I")
    otro.fecha_inicio, otro.fecha_fin = date(2026, 10, 5), date(2027, 1, 30)
    db.session.add(otro)
    db.session.commit()
    assert calendario.sumar_habiles(lunes, 5) == date(2026, 10, 6)            # vacaciones no cuentan


def test_prelacion_categoria_antiguedad_colegiatura(app, plana):
    orden = sorted(plana.values(), key=lambda d: d.clave_prelacion)
    assert [d.codigo for d in orden] == ["D01", "D03", "D02", "D04", "D06", "D05"]


def test_candidatos_excluyen_y_priorizan_afinidad(app, catalogo, plana):
    tesis = _tesis(app, catalogo)
    tesis_service.designar(tesis, plana["asesor"], "asesor", None)
    db.session.commit()
    elegibles, descartados = asignacion_service.candidatos(tesis, "dictaminante")
    motivos = {d["docente"].codigo: d["motivo"] for d in descartados}
    assert "Art. 73" in motivos["D07"] and motivos["D08"] == "De licencia" and "Ya participa" in motivos["D01"]
    codigos = [c["docente"].codigo for c in elegibles]
    assert set(codigos[:2]) == {"D02", "D03"}                     # mismo tema: Machine learning
    assert codigos.index("D04") < codigos.index("D05")            # misma linea antes que otra area
    # Propuesta final ordenada por prelacion (Principal antes que Asociado)
    assert [c["docente"].codigo for c in asignacion_service.proponer(tesis, "dictaminante", 2)] == ["D03", "D02"]


def test_cupo_maximo_de_dictamenes(app, catalogo, plana):
    from services import parametros
    parametros.guardar("cupo_dictamenes", 1)
    otra = _tesis(app, catalogo)
    otra.codigo, otra.etapa = "TES-OTRA", "proyecto"
    db.session.add(TesisMiembro(tesis=otra, docente=plana["ml2"], rol="dictaminante", estado_designacion="aceptado"))
    db.session.commit()
    nueva = Tesis(codigo="TES-NUEVA", titulo="Otra tesis de machine learning", etapa="proyecto", temas=[catalogo["temas"]["ml"]])
    db.session.add(nueva)
    db.session.commit()
    _, descartados = asignacion_service.candidatos(nueva, "dictaminante")
    assert any(d["docente"].codigo == "D03" and "Cupo completo" in d["motivo"] for d in descartados)


# ----------------------------------------------------------------------
# Flujo completo por la web
# ----------------------------------------------------------------------
def _como(client, docente):
    client.get("/logout")
    login(client, docente.usuario.username, "Docente2026")


def test_flujo_completo_tesis_ordinaria(client, app, catalogo, plana):
    login(client, "directora")
    temas = [str(catalogo["temas"]["ml"].id)]
    r = client.post("/tesis/nueva", data={
        "titulo": "Modelo de machine learning para predecir la desercion estudiantil", "modalidad": "tesis",
        "regimen": "vigente", "linea_id": str(catalogo["lineas"]["datos"].id), "temas": temas,
        "palabras_clave": "desercion, prediccion", "e1_codigo": "020100", "e1_nombres": "Carla",
        "e1_apellidos": "Mamani Huaman", "asesor_id": "auto",
    })
    assert r.status_code == 302
    tesis = Tesis.query.one()
    tid = tesis.id
    asesor = tesis.asesor
    assert asesor.automatico and asesor.estado_designacion == "propuesto"

    # 1) El asesor acepta -> pasa a dictamen del proyecto
    _como(client, asesor.docente)
    assert "Requieren su atención" in client.get("/docente/tesis").get_data(as_text=True)
    client.post(f"/docente/tesis/designacion/{asesor.id}", data={"respuesta": "acepto"})
    db.session.expire_all()
    assert db.session.get(Tesis, tid).etapa == "proyecto"

    # 2) Propuesta automatica de 2 dictaminantes; uno declara impedimento y se repone otro
    client.get("/logout")
    login(client, "directora")
    client.post(f"/tesis/{tid}/proponer", data={"rol": "dictaminante"})
    tesis = db.session.get(Tesis, tid)
    d1, d2 = tesis.dictaminantes
    assert {d1.docente.codigo, d2.docente.codigo} == {"D02", "D03"}
    _como(client, d2.docente)
    client.post(f"/docente/tesis/designacion/{d2.id}", data={"respuesta": "impedimento", "motivo": "Parentesco con el tesista"})
    db.session.expire_all()
    tesis = db.session.get(Tesis, tid)
    assert db.session.get(TesisMiembro, d2.id).estado_designacion == "impedimento"
    activos = tesis.dictaminantes
    assert len(activos) == 2 and d2.docente_id not in [m.docente_id for m in activos]
    for m in activos:
        _como(client, m.docente)
        client.post(f"/docente/tesis/designacion/{m.id}", data={"respuesta": "acepto"})

    # 3) El tesista sube el proyecto: se abren 2 dictamenes con plazo de 10 dias habiles
    client.get("/logout")
    login(client, "directora")
    est = db.session.get(Tesis, tid).estudiantes[0]
    html = client.post(f"/tesis/estudiantes/{est.id}/cuenta").get_data(as_text=True)
    usuario_est, clave_est = re.findall(r'<span class="cred-box">([^<]+)</span>', html)[:2]
    client.get("/logout")
    login(client, usuario_est, clave_est)
    client.post("/cuenta/contrasena", data={"actual": clave_est, "nueva": "Tesista2026", "confirmar": "Tesista2026"})
    client.post(f"/estudiante/tesis/{tid}/version", data={"archivo": (io.BytesIO(PDF), "proyecto.pdf")}, content_type="multipart/form-data")
    db.session.expire_all()
    pendientes = Dictamen.query.filter_by(tesis_id=tid, etapa="proyecto", resultado=None).all()
    assert len(pendientes) == 2 and all(d.limite == calendario.sumar_habiles(date.today(), 10) for d in pendientes)

    # 4) Un dictaminante observa, el otro da suficiente -> el tesista subsana (con documento obligatorio)
    obs, ok = pendientes
    _como(client, obs.miembro.docente)
    client.post(f"/docente/tesis/dictamen/{obs.id}", data={"resultado": "con_observaciones", "observaciones": "Precisar la población"})
    _como(client, ok.miembro.docente)
    client.post(f"/docente/tesis/dictamen/{ok.id}", data={"resultado": "suficiente"})
    client.get("/logout")
    login(client, usuario_est, "Tesista2026")
    html = client.get(f"/estudiante/tesis/{tid}").get_data(as_text=True)
    assert "Precisar la población" in html and "levantamiento de observaciones" in html.lower()
    r = client.post(f"/estudiante/tesis/{tid}/version", data={"archivo": (io.BytesIO(PDF), "v2.pdf")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Adjunte el documento" in r.get_data(as_text=True)
    client.post(f"/estudiante/tesis/{tid}/version", data={"archivo": (io.BytesIO(PDF), "v2.pdf"),
                "subsanacion": (io.BytesIO(PDF), "subsanacion.pdf")}, content_type="multipart/form-data")
    db.session.expire_all()
    ronda2 = Dictamen.query.filter_by(tesis_id=tid, etapa="proyecto", ronda=2).all()
    assert len(ronda2) == 1 and ronda2[0].miembro_id == obs.miembro_id            # solo quien observo
    assert ronda2[0].limite == calendario.sumar_habiles(date.today(), 7)
    _como(client, obs.miembro.docente)
    client.post(f"/docente/tesis/dictamen/{ronda2[0].id}", data={"resultado": "suficiente"})
    db.session.expire_all()
    assert db.session.get(Tesis, tid).etapa == "inscripcion"

    # 5) Inscripcion del tema -> 1 anio para presentar la tesis
    client.get("/logout")
    login(client, "directora")
    client.post(f"/tesis/{tid}/resolucion", data={"tipo": "inscripcion", "numero": "100-2026-FIA", "fecha": date.today().isoformat()})
    tesis = db.session.get(Tesis, tid)
    assert tesis.etapa == "desarrollo" and tesis.fecha_limite_entrega.year == date.today().year + 1

    # 6) El tesista presenta la tesis: continuan los 2 dictaminantes y falta el tercero
    client.get("/logout")
    login(client, usuario_est, "Tesista2026")
    client.post(f"/estudiante/tesis/{tid}/version", data={"archivo": (io.BytesIO(PDF), "tesis.pdf")}, content_type="multipart/form-data")
    db.session.expire_all()
    tesis = db.session.get(Tesis, tid)
    assert tesis.etapa == "dictamen" and tesis_service.necesidades(tesis) == [("dictaminante", 1)]
    client.get("/logout")
    login(client, "directora")
    client.post(f"/tesis/{tid}/proponer", data={"rol": "dictaminante"})
    db.session.expire_all()
    tercero = [m for m in db.session.get(Tesis, tid).dictaminantes if m.estado_designacion == "propuesto"][0]
    _como(client, tercero.docente)
    client.post(f"/docente/tesis/designacion/{tercero.id}", data={"respuesta": "acepto"})
    db.session.expire_all()
    for d in Dictamen.query.filter_by(tesis_id=tid, etapa="tesis", resultado=None).all():
        assert d.limite == calendario.sumar_habiles(date.today(), 15)
        _como(client, d.miembro.docente)
        client.post(f"/docente/tesis/dictamen/{d.id}", data={"resultado": "suficiente"})
    db.session.expire_all()
    tesis = db.session.get(Tesis, tid)
    assert tesis.etapa == "apto" and len(tesis.jurado) == 3

    # 7) Sustentacion: requiere resolucion de apto; preside el de mayor prelacion
    client.get("/logout")
    login(client, "directora")
    fecha = (datetime.now() + timedelta(days=10)).replace(hour=10, minute=0).strftime("%Y-%m-%dT%H:%M")
    r = client.post(f"/tesis/{tid}/sustentacion", data={"accion": "programar", "fecha_sustentacion": fecha}, follow_redirects=True)
    assert "resolución de declaración de apto" in r.get_data(as_text=True)
    client.post(f"/tesis/{tid}/resolucion", data={"tipo": "apto", "numero": "200-2026", "fecha": date.today().isoformat()})
    client.post(f"/tesis/{tid}/sustentacion", data={"accion": "programar", "fecha_sustentacion": fecha, "modalidad_sustentacion": "virtual"})
    tesis = db.session.get(Tesis, tid)
    assert tesis.etapa == "sustentacion"
    jurado = tesis.jurado
    assert jurado[0].docente.clave_prelacion <= jurado[-1].docente.clave_prelacion
    notas = {f"nota_{m.id}": n for m, n in zip(jurado, ("15", "16", "10"))}
    client.post(f"/tesis/{tid}/sustentacion", data={"accion": "notas", "con_observaciones": "1", **notas})
    tesis = db.session.get(Tesis, tid)
    assert tesis.nota_sustentacion == 16 and tesis.calificacion == "Aprobado" and tesis.etapa == "observaciones"
    client.post(f"/tesis/{tid}/sustentacion", data={"accion": "conformidad"})
    assert db.session.get(Tesis, tid).etapa == "titulado"

    # 8) Oficio Word con la propuesta y paginas de gestion
    r = client.get(f"/tesis/{tid}/oficio/dictaminante")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    for url in [f"/tesis/{tid}", "/tesis/", f"/tesis/{tid}/candidatos/dirimente", "/tesis/asignacion", "/tesis/configuracion"]:
        assert client.get(url).status_code == 200, url


def test_dirimente_reemplaza_dictamen_insuficiente(app, catalogo, plana):
    tesis = _tesis(app, catalogo)
    a = tesis_service.designar(tesis, plana["asesor"], "asesor", None)
    tesis_service.responder_designacion(a, True, None, None)
    for m in tesis_service.proponer_automaticamente(tesis, None, rol="dictaminante"):
        tesis_service.responder_designacion(m, True, None, None)
    tesis_service.subir_version(tesis, "x.pdf", "x.pdf", None, plana["asesor"].usuario)
    d_ins, d_suf = Dictamen.query.filter_by(tesis_id=tesis.id).all()
    tesis_service.emitir_dictamen(d_ins, "insuficiente", "Tema no pertinente", None)
    tesis_service.emitir_dictamen(d_suf, "suficiente", None, None)
    assert tesis.decision_pendiente == "dirimente" and tesis_service.necesidades(tesis) == [("dirimente", 1)]
    dirimente = tesis_service.proponer_automaticamente(tesis, None, rol="dirimente")[0]
    tesis_service.responder_designacion(dirimente, True, None, None)
    d_dir = Dictamen.query.filter_by(miembro_id=dirimente.id).one()
    tesis_service.emitir_dictamen(d_dir, "suficiente", None, None)
    db.session.commit()
    assert tesis.etapa == "inscripcion"
    assert d_ins.miembro.estado_designacion == "reemplazado" and dirimente.rol == "dictaminante"


def test_designacion_sin_respuesta_se_repone_automaticamente(app, catalogo, plana):
    tesis = _tesis(app, catalogo)
    m = tesis_service.designar(tesis, plana["asesor"], "asesor", None)
    m.fecha_designacion = datetime.now() - timedelta(days=20)
    db.session.commit()
    tesis_service.revisar_plazos()
    assert m.estado_designacion == "impedimento" and "Sin respuesta" in m.motivo_impedimento
    assert tesis.asesor and tesis.asesor.docente_id != plana["asesor"].id


def test_suficiencia_profesional_tiene_tres_dictaminantes(app, catalogo, plana):
    tesis = _tesis(app, catalogo, modalidad="suficiencia")
    a = tesis_service.designar(tesis, plana["asesor"], "asesor", None)
    tesis_service.responder_designacion(a, True, None, None)
    assert tesis.etapa == "dictamen" and tesis_service.necesidades(tesis) == [("dictaminante", 3)]


# ----------------------------------------------------------------------
# Perfil academico
# ----------------------------------------------------------------------
def test_perfil_academico_docente_y_validacion_dais(client, app, catalogo, plana):
    docente = plana["itil"]
    _como(client, docente)
    temas = [str(catalogo["temas"]["ml"].id), str(catalogo["temas"]["bi"].id)]
    client.post("/docente/perfil-academico", data={
        "temas": temas, "linea_principal": str(catalogo["lineas"]["datos"].id), "experiencia_anios": "11",
        "grado_academico": "Doctor", "colegiatura_numero": "CIP 12345", "colegiatura_anio": "2001",
        "sustento": (io.BytesIO(PDF), "constancia.pdf"),
    }, content_type="multipart/form-data")
    db.session.expire_all()
    docente = db.session.get(Docente, docente.id)
    assert {t.nombre for t in docente.temas} == {"Machine learning", "Inteligencia de negocios"}
    assert docente.experiencia_anios == 11 and docente.linea_principal.nombre == "Ciencia de datos"
    assert docente.grado_academico == "Maestro" and docente.colegiatura_anio == 2016    # aun sin validar
    pendientes = CambioPerfil.query.filter_by(docente_id=docente.id, estado="pendiente").all()
    assert {c.campo for c in pendientes} == {"grado_academico", "colegiatura"}

    client.get("/logout")
    login(client, "operador")
    assert client.get("/perfiles/").status_code == 200 and client.get("/perfiles/validaciones").status_code == 200
    for c in pendientes:
        client.post(f"/perfiles/validaciones/{c.id}", data={"accion": "aprobar"})
    db.session.expire_all()
    docente = db.session.get(Docente, docente.id)
    assert docente.grado_academico == "Doctor" and docente.colegiatura_anio == 2001 and docente.colegiatura_numero == "CIP 12345"
    assert client.get(f"/perfiles/{docente.id}").status_code == 200


def test_licencia_validada_excluye_de_propuestas(app, catalogo, plana):
    docente = plana["ml1"]
    hoy = date.today()
    c = perfil_service.solicitar_cambio(docente, "licencia", f"{hoy.isoformat()}|{(hoy + timedelta(days=30)).isoformat()}", docente.usuario)
    db.session.commit()
    tesis = _tesis(app, catalogo)
    assert "D02" in [x["docente"].codigo for x in asignacion_service.candidatos(tesis, "dictaminante")[0]]
    perfil_service.revisar(c, True, None, plana["asesor"].usuario)
    db.session.commit()
    _, descartados = asignacion_service.candidatos(tesis, "dictaminante")
    assert any(d["docente"].codigo == "D02" and d["motivo"] == "De licencia" for d in descartados)


def test_docente_con_perfil_incompleto_es_dirigido_a_completarlo(client, app):
    d = Docente(codigo="DX", nombres="Ivan", apellidos="Nuevo")
    db.session.add(d)
    db.session.flush()
    u, _ = crear_cuenta_docente(d)
    u.set_password("Docente2026")
    u.debe_cambiar_password = False
    db.session.commit()
    r = login(client, u.username, "Docente2026")
    assert r.headers["Location"].endswith("/docente/perfil-academico")
    assert "Complete su perfil académico" in client.get("/docente/").get_data(as_text=True)
