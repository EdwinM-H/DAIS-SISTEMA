import io
import re

from models import db, Docente, Semestre, Usuario, Tesis, Capacitacion, Notificacion
from services.excel_service import importar_ficha_integral
from services.cuentas_service import crear_cuenta_docente
from tests.conftest import login


def _cuenta(docente, password="Docente2026"):
    usuario, _ = crear_cuenta_docente(docente)
    usuario.set_password(password)
    usuario.debe_cambiar_password = False
    db.session.commit()
    return usuario


def test_login_redireccion_segura_y_roles(client, app):
    r = client.post("/login?next=https://evil.example", data={"username": "directora", "password": "Clave2026"})
    assert r.status_code == 302 and "evil" not in r.headers["Location"]
    assert client.get("/usuarios/").status_code == 200
    client.get("/logout")
    login(client, "operador")
    assert client.get("/usuarios/").status_code == 403          # operador no administra usuarios
    assert client.get("/importar").status_code == 200


def test_cuenta_temporal_obliga_cambio_de_contrasena(client, app):
    with app.app_context():
        doc = Docente(codigo="DOC-0001", nombres="Ana", apellidos="Quispe Lopez")
        db.session.add(doc)
        db.session.flush()
        usuario, password = crear_cuenta_docente(doc)
        db.session.commit()
        username = usuario.username
    assert username == "aquispe"
    login(client, username, password)
    assert client.get("/docente/").headers["Location"].endswith("/cuenta/contrasena")
    r = client.post("/cuenta/contrasena", data={"actual": password, "nueva": "NuevaClave1", "confirmar": "NuevaClave1"})
    assert r.status_code == 302
    assert client.get("/docente/").status_code == 200


def test_portal_docente_resultados_solo_si_publicados(client, app, ficha_xlsx):
    with app.app_context():
        sem = Semestre.query.first()
        importar_ficha_integral(ficha_xlsx, sem.id, None)
        doc = Docente.buscar_por_nombre("ARDILES ROMERO VELIA")
        _cuenta(doc)
        username = doc.usuario.username
    login(client, username, "Docente2026")
    html = client.get("/docente/").get_data(as_text=True)
    assert "Aun no hay resultados publicados" in html
    with app.app_context():
        Semestre.query.first().publicado = True
        db.session.commit()
    html = client.get("/docente/").get_data(as_text=True)
    assert "Puntos a mejorar" in html and "Puesto" in html
    assert client.get("/docentes").status_code == 403            # no accede a la gestion


def test_docente_registra_capacitacion_con_certificado(client, app):
    with app.app_context():
        doc = Docente(codigo="DOC-0001", nombres="Ana", apellidos="Quispe Lopez")
        db.session.add(doc)
        db.session.flush()
        _cuenta(doc)
        username, doc_id = doc.usuario.username, doc.id
    login(client, username, "Docente2026")
    r = client.post("/docente/capacitaciones/guardar", data={
        "nombre": "Diplomado en IA", "anio": "2025", "horas": "120", "tipo": "Diplomado",
        "archivo": (io.BytesIO(b"%PDF-1.4 prueba"), "certificado.pdf"),
    }, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        cap = Capacitacion.query.filter_by(docente_id=doc_id).one()
        assert cap.estado_validacion == "pendiente" and cap.archivo_ruta
        cap_id = cap.id
    assert client.get(f"/archivos/capacitacion/{cap_id}").status_code == 200
    # Un archivo no permitido se rechaza
    client.post("/docente/capacitaciones/guardar", data={
        "nombre": "Otro", "anio": "2025", "archivo": (io.BytesIO(b"MZ"), "virus.exe"),
    }, content_type="multipart/form-data")
    with app.app_context():
        assert Capacitacion.query.count() == 1
    # La gestion valida y el docente recibe notificacion
    client.get("/logout")
    login(client, "operador")
    client.post(f"/produccion/capacitaciones/{cap_id}/validar", data={"estado": "validado"})
    with app.app_context():
        assert db.session.get(Capacitacion, cap_id).estado_validacion == "validado"
        assert Notificacion.query.filter(Notificacion.titulo.like("%validado%")).count() == 1


def test_flujo_completo_de_tesis(client, app):
    with app.app_context():
        docentes = []
        for i, (n, a) in enumerate([("Luis", "Asesor Uno"), ("Rosa", "Dictaminante Dos"), ("Hugo", "Dictaminante Tres")]):
            d = Docente(codigo=f"DOC-000{i + 1}", nombres=n, apellidos=a)
            db.session.add(d)
            db.session.flush()
            _cuenta(d)
            docentes.append((d.id, d.usuario.username))
    login(client, "directora")
    r = client.post("/tesis/nueva", data={
        "titulo": "Sistema de recomendacion academica", "e1_codigo": "020100", "e1_nombres": "Carla",
        "e1_apellidos": "Mamani Huaman", "asesor_id": str(docentes[0][0]),
    })
    assert r.status_code == 302
    with app.app_context():
        tesis = Tesis.query.one()
        tesis_id = tesis.id
        assert tesis.asesor.docente_id == docentes[0][0] and tesis.estado == "registrada"

    # El asesor no puede ser dictaminante de la misma tesis
    client.post(f"/tesis/{tesis_id}/asignar", data={"rol": "dictaminante", "docente_id": [str(docentes[0][0])]})
    client.post(f"/tesis/{tesis_id}/asignar", data={"rol": "dictaminante", "docente_id": [str(docentes[1][0]), str(docentes[2][0])]})
    with app.app_context():
        tesis = db.session.get(Tesis, tesis_id)
        assert len(tesis.dictaminantes) == 2 and tesis.estado == "en_dictamen"
        estudiante_id = tesis.estudiantes[0].id

    # Acceso del estudiante
    html = client.post(f"/tesis/estudiantes/{estudiante_id}/cuenta").get_data(as_text=True)
    cajas = re.findall(r'<span class="cred-box">([^<]+)</span>', html)
    est_user, est_pass = cajas[0], cajas[1]
    client.get("/logout")

    # El estudiante sube su tesis
    login(client, est_user, est_pass)
    client.post("/cuenta/contrasena", data={"actual": est_pass, "nueva": "Tesista2026", "confirmar": "Tesista2026"})
    r = client.post(f"/estudiante/tesis/{tesis_id}/version", data={"archivo": (io.BytesIO(b"%PDF"), "tesis.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    client.get("/logout")

    # Dictaminante 1 observa, el estudiante corrige, ambos dan visto bueno
    with app.app_context():
        tesis = db.session.get(Tesis, tesis_id)
        m1, m2 = tesis.dictaminantes
        ids = {m.docente_id: m.id for m in (m1, m2)}
    login(client, docentes[1][1], "Docente2026")
    assert "Mi dictamen" in client.get(f"/docente/tesis/{tesis_id}").get_data(as_text=True)
    client.post(f"/docente/tesis/revision/{ids[docentes[1][0]]}", data={"estado": "observado", "observaciones": "Mejorar el marco teorico"})
    client.get("/logout")
    with app.app_context():
        assert db.session.get(Tesis, tesis_id).estado == "observada"

    login(client, est_user, "Tesista2026")
    html = client.get(f"/estudiante/tesis/{tesis_id}").get_data(as_text=True)
    assert "Mejorar el marco teorico" in html
    client.post(f"/estudiante/tesis/{tesis_id}/version", data={"archivo": (io.BytesIO(b"%PDF v2"), "tesis_v2.pdf")},
                content_type="multipart/form-data")
    client.get("/logout")
    with app.app_context():
        assert db.session.get(Tesis, tesis_id).estado == "en_dictamen"

    for did, uname in docentes[1:]:
        login(client, uname, "Docente2026")
        client.post(f"/docente/tesis/revision/{ids[did]}", data={"estado": "visto_bueno"})
        client.get("/logout")
    with app.app_context():
        tesis = db.session.get(Tesis, tesis_id)
        assert tesis.estado == "dictamen_favorable" and tesis.progreso_dictamen == (2, 2)

    # Un docente ajeno no puede ver la tesis
    with app.app_context():
        otro = Docente(codigo="DOC-0099", nombres="Ajeno", apellidos="Sin Rol")
        db.session.add(otro)
        db.session.flush()
        _cuenta(otro)
        uname = otro.usuario.username
    login(client, uname, "Docente2026")
    assert client.get(f"/docente/tesis/{tesis_id}").status_code == 403
    client.get("/logout")

    # Programar y registrar sustentacion
    login(client, "directora")
    client.post(f"/tesis/{tesis_id}/sustentacion", data={"accion": "programar", "fecha_sustentacion": "2026-12-01T10:00", "lugar": "Aula 101"})
    client.post(f"/tesis/{tesis_id}/sustentacion", data={"accion": "registrar", "nota": "17"})
    with app.app_context():
        tesis = db.session.get(Tesis, tesis_id)
        assert tesis.estado == "sustentada" and tesis.nota_sustentacion == 17
        assert len(tesis.eventos) >= 8


def test_paginas_de_gestion_responden(client, app, ficha_xlsx):
    with app.app_context():
        importar_ficha_integral(ficha_xlsx, Semestre.query.first().id, None)
        doc_id = Docente.query.first().id
    login(client, "directora")
    for url in ["/", "/docentes", f"/docentes/{doc_id}", f"/docentes/{doc_id}/evaluacion", "/ranking", "/importar",
                "/semestres", "/historial", "/documentos", "/usuarios/", "/produccion/capacitaciones",
                "/produccion/investigaciones", "/tesis/", "/tesis/estudiantes", "/notificaciones"]:
        assert client.get(url).status_code == 200, url


def test_edicion_manual_de_evaluacion_recalcula(client, app):
    with app.app_context():
        d = Docente(codigo="DOC-0001", nombres="Ana", apellidos="Quispe")
        db.session.add(d)
        db.session.commit()
        doc_id = d.id
    login(client, "operador")
    datos = {"encuesta": "8", "autoevaluacion": "10", "reuniones": "15", "silabos": "20", "notas_config": "15",
             "horas_lectivas": "20", "puntualidad": "10", "subida_notas_erp": "10", "designacion_delegados": "5"}
    client.post(f"/docentes/{doc_id}/evaluacion", data=datos)
    with app.app_context():
        from models import Evaluacion
        ev = Evaluacion.query.filter_by(docente_id=doc_id).one()
        assert ev.normas == 9.5 and ev.promedio_final == round(8 * .4 + 9.5 * .4 + 10 * .2, 4)
        assert ev.promedio_final == 9.0 and ev.clasificacion == "Excelente" and ev.editado_manual
    # Fuera de rango -> rechazado
    client.post(f"/docentes/{doc_id}/evaluacion", data={**datos, "encuesta": "15"})
    with app.app_context():
        from models import Evaluacion
        assert Evaluacion.query.filter_by(docente_id=doc_id).one().encuesta == 8
