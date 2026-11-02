"""Creacion de cuentas de acceso para docentes y estudiantes."""

from models import db, Usuario, Docente
from utils import generar_password, generar_username


def crear_cuenta_docente(docente):
    """Crea (o reactiva) la cuenta de un docente. Devuelve (usuario, password_temporal | None)."""
    if docente.usuario:
        return docente.usuario, None
    usuario = Usuario(
        username=generar_username(docente.nombres, docente.apellidos),
        nombre_completo=docente.nombre_natural,
        email=docente.correo_institucional,
        rol="docente",
        docente_id=docente.id,
        debe_cambiar_password=True,
    )
    password = generar_password()
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.flush()
    return usuario, password


def crear_cuentas_docentes(docente_ids=None):
    """Crea cuentas para todos los docentes activos sin cuenta. Devuelve lista de credenciales."""
    q = Docente.query.filter_by(estado="activo")
    if docente_ids:
        q = q.filter(Docente.id.in_(docente_ids))
    credenciales = []
    for docente in q.order_by(Docente.apellidos, Docente.nombres).all():
        if docente.usuario:
            continue
        usuario, password = crear_cuenta_docente(docente)
        credenciales.append({
            "nombre": docente.nombre_completo, "codigo": docente.codigo,
            "username": usuario.username, "password": password,
        })
    db.session.commit()
    return credenciales


def crear_cuenta_estudiante(estudiante):
    if estudiante.usuario:
        return estudiante.usuario, None
    usuario = Usuario(
        username=generar_username(estudiante.nombres, estudiante.apellidos),
        nombre_completo=f"{estudiante.nombres} {estudiante.apellidos}",
        email=estudiante.correo,
        rol="estudiante",
        estudiante_id=estudiante.id,
        debe_cambiar_password=True,
    )
    password = generar_password()
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.flush()
    return usuario, password


def restablecer_password(usuario):
    password = generar_password()
    usuario.set_password(password)
    usuario.debe_cambiar_password = True
    return password
