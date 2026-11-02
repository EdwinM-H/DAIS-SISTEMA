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


def test_cuenta_docente_sin_vinculo_muestra_mensaje_y_se_puede_vincular(client, app):
    d = Docente(codigo="DOC-0001", nombres="Ana", apellidos="Quispe Lopez")
    db.session.add(d)
    u = Usuario(username="aquispe", nombre_completo="Ana Quispe Lopez", rol="docente", debe_cambiar_password=False)
    u.set_password("Docente2026")
    db.session.add(u)
    db.session.commit()
    login(client, "aquispe", "Docente2026")
    for url in ("/docente/", "/docente/tesis", "/docente/perfil-academico", "/"):
        r = client.get(url, follow_redirects=True)
        assert r.status_code == 409 and "no está vinculada" in r.get_data(as_text=True), url
    client.get("/logout")
    login(client, "directora")
    assert "Sin vínculo" in client.get("/usuarios/").get_data(as_text=True)
    client.post(f"/usuarios/{u.id}/vincular", data={"docente_id": str(d.id)})
    client.get("/logout")
    login(client, "aquispe", "Docente2026")
    assert client.get("/docente/").status_code == 200


def test_campana_y_cambio_de_clave_desde_ventana(client, app):
    from models import Notificacion

    login(client, "directora")
    u = Usuario.query.filter_by(username="directora").first()
    db.session.add(Notificacion(usuario_id=u.id, titulo="Aviso de prueba", mensaje="Detalle", url="/ranking"))
    db.session.commit()
    html = client.get("/docentes").get_data(as_text=True)
    assert "popover-notif" in html and "Aviso de prueba" in html and 'id="dlgPassword"' in html

    # Error: vuelve a la misma pagina y reabre la ventana
    r = client.post("/cuenta/contrasena", data={"actual": "mala", "nueva": "OtraClave9", "confirmar": "OtraClave9", "volver": "/docentes?"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/docentes?cambiar_clave=1")
    # Exito: regresa a la pagina donde estaba
    r = client.post("/cuenta/contrasena", data={"actual": "Clave2026", "nueva": "OtraClave9", "confirmar": "OtraClave9", "volver": "/docentes?"})
    assert r.headers["Location"].endswith("/docentes")
    assert Usuario.query.filter_by(username="directora").first().check_password("OtraClave9")
    # Redireccion externa no permitida
    r = client.post("/notificaciones/marcar-leidas", data={"volver": "https://evil.example"})
    assert r.headers["Location"].endswith("/notificaciones")
    assert Notificacion.query.filter_by(leida=False).count() == 0


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
        # Sin "Calcular resultados" aun no hay promedio
        assert ev.normas == 9.5 and ev.promedio_final is None and ev.editado_manual
    client.get("/logout")
    login(client, "directora")
    client.post("/evaluacion/calcular", data={})
    with app.app_context():
        from models import Evaluacion
        ev = Evaluacion.query.filter_by(docente_id=doc_id).one()
        assert ev.promedio_final == 9.0 and ev.clasificacion == "Excelente"
    client.get("/logout")
    login(client, "operador")
    # Fuera de rango -> rechazado
    client.post(f"/docentes/{doc_id}/evaluacion", data={**datos, "encuesta": "15"})
    with app.app_context():
        from models import Evaluacion
        assert Evaluacion.query.filter_by(docente_id=doc_id).one().encuesta == 8
