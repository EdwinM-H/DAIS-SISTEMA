"""Reglas del proceso de tesis: asignaciones, dictamenes, versiones y bitacora."""

from datetime import datetime

from flask import url_for

from models import db, TesisMiembro, TesisVersion, TesisEvento, ROLES_TESIS, ESTADOS_REVISION
from utils import notificar, notificar_gestion

MAX_DICTAMINANTES = 3


class TesisError(Exception):
    pass


def registrar_evento(tesis, tipo, descripcion, usuario=None):
    db.session.add(TesisEvento(
        tesis_id=tesis.id, tipo=tipo, descripcion=descripcion,
        usuario_id=usuario.id if usuario else None,
    ))


def _notificar_estudiantes(tesis, titulo, mensaje=None):
    for est in tesis.estudiantes:
        if est.usuario:
            notificar(est.usuario, titulo, mensaje, url_for("estudiante.mi_tesis", tesis_id=tesis.id))


def asignar_miembro(tesis, docente, rol, usuario):
    if rol not in ROLES_TESIS:
        raise TesisError("Rol no valido.")
    if tesis.estado in ("sustentada", "anulada"):
        raise TesisError("La tesis ya fue cerrada; no se pueden asignar docentes.")
    existentes = {m.rol for m in tesis.miembros if m.docente_id == docente.id}
    if rol in existentes:
        raise TesisError(f"{docente.nombre_completo} ya es {ROLES_TESIS[rol].lower()} de esta tesis.")
    if rol == "dictaminante" and existentes & {"asesor", "coasesor"}:
        raise TesisError("El asesor de la tesis no puede ser dictaminante de la misma.")
    if rol in ("asesor", "coasesor") and "dictaminante" in existentes:
        raise TesisError("Un dictaminante no puede ser asesor de la misma tesis.")
    if rol == "asesor" and tesis.asesor:
        raise TesisError("La tesis ya tiene un asesor. Retirelo antes de asignar otro.")
    if rol == "dictaminante" and len(tesis.dictaminantes) >= MAX_DICTAMINANTES:
        raise TesisError(f"La tesis ya tiene {MAX_DICTAMINANTES} dictaminantes.")

    miembro = TesisMiembro(tesis=tesis, docente=docente, rol=rol, asignado_por_id=usuario.id)
    db.session.add(miembro)
    db.session.flush()
    tesis.recalcular_estado()
    registrar_evento(tesis, "asignacion", f"{docente.nombre_completo} asignado(a) como {ROLES_TESIS[rol].lower()}.", usuario)
    if docente.usuario:
        notificar(
            docente.usuario,
            f"Fue designado(a) {ROLES_TESIS[rol].lower()} de una tesis",
            f"{tesis.codigo}: {tesis.titulo}",
            url_for("docente.tesis_detalle", tesis_id=tesis.id),
        )
    _notificar_estudiantes(tesis, f"Se asigno un(a) {ROLES_TESIS[rol].lower()} a su tesis", docente.nombre_natural)
    return miembro


def retirar_miembro(miembro, usuario):
    tesis = miembro.tesis
    nombre, rol = miembro.docente.nombre_completo, miembro.rol_nombre.lower()
    db.session.delete(miembro)
    db.session.flush()
    db.session.refresh(tesis)
    tesis.recalcular_estado()
    registrar_evento(tesis, "retiro", f"{nombre} fue retirado(a) como {rol}.", usuario)


def registrar_revision(miembro, estado, observaciones, usuario, archivo=(None, None)):
    """El dictaminante (u otro miembro) emite su visto bueno u observaciones."""
    if estado not in ("observado", "visto_bueno"):
        raise TesisError("Seleccione 'Visto bueno' u 'Observado'.")
    if estado == "observado" and not (observaciones or "").strip():
        raise TesisError("Debe detallar las observaciones.")
    tesis = miembro.tesis
    if tesis.estado in ("sustentada", "anulada"):
        raise TesisError("La tesis ya fue cerrada.")
    if not tesis.versiones:
        raise TesisError("Aun no se ha subido ningun documento de tesis para revisar.")

    miembro.estado_revision = estado
    miembro.observaciones = (observaciones or "").strip() or None
    miembro.fecha_respuesta = datetime.now()
    if archivo[0]:
        miembro.archivo_ruta, miembro.archivo_nombre = archivo
    anterior = tesis.estado
    tesis.recalcular_estado()

    etiqueta = ESTADOS_REVISION[estado].lower()
    registrar_evento(
        tesis, "revision",
        f"{miembro.docente.nombre_completo} ({miembro.rol_nombre.lower()}) emitio: {etiqueta}."
        + (f" Observaciones: {miembro.observaciones}" if estado == "observado" else ""),
        usuario,
    )
    _notificar_estudiantes(tesis, f"Nueva revision de su tesis: {etiqueta}", miembro.observaciones)
    if tesis.estado == "dictamen_favorable" and anterior != "dictamen_favorable":
        registrar_evento(tesis, "dictamen", "Todos los dictaminantes otorgaron su visto bueno.", usuario)
        _notificar_estudiantes(tesis, "Su tesis obtuvo todos los vistos buenos")
        notificar_gestion(
            f"Tesis {tesis.codigo} con dictamen favorable", tesis.titulo,
            url_for("tesis.detalle", tesis_id=tesis.id),
        )


def subir_version(tesis, ruta, nombre, comentario, usuario):
    if tesis.estado in ("sustentada", "anulada"):
        raise TesisError("La tesis ya fue cerrada.")
    numero = (max((v.numero for v in tesis.versiones), default=0)) + 1
    version = TesisVersion(
        numero=numero, archivo_ruta=ruta, archivo_nombre=nombre,
        comentario=(comentario or "").strip() or None, subido_por_id=usuario.id,
    )
    tesis.versiones.insert(0, version)  # mantiene la coleccion ordenada (mas reciente primero)
    # Una nueva version reabre la revision de quienes la observaron
    reabiertos = []
    for m in tesis.dictaminantes:
        if m.estado_revision == "observado":
            m.estado_revision = "pendiente"
            reabiertos.append(m)
    db.session.flush()
    tesis.recalcular_estado()
    registrar_evento(tesis, "version", f"Se subio la version {numero} del documento.", usuario)
    for m in tesis.miembros:
        if m.docente.usuario and (m in reabiertos or m.estado_revision == "pendiente"):
            notificar(
                m.docente.usuario, f"Nueva version de la tesis {tesis.codigo}",
                f"Version {numero} lista para su revision.",
                url_for("docente.tesis_detalle", tesis_id=tesis.id),
            )
    return version


def programar_sustentacion(tesis, fecha, lugar, usuario):
    if tesis.estado not in ("dictamen_favorable", "sustentacion_programada"):
        raise TesisError("Solo se puede programar la sustentacion con dictamen favorable.")
    tesis.fecha_sustentacion = fecha
    tesis.lugar_sustentacion = lugar
    tesis.estado = "sustentacion_programada"
    registrar_evento(tesis, "sustentacion", f"Sustentacion programada para el {fecha:%d/%m/%Y %H:%M} en {lugar or 'lugar por definir'}.", usuario)
    _notificar_estudiantes(tesis, "Se programo la sustentacion de su tesis", f"{fecha:%d/%m/%Y %H:%M} - {lugar or ''}")
    for m in tesis.miembros:
        if m.rol == "jurado" and m.docente.usuario:
            notificar(m.docente.usuario, f"Sustentacion programada: {tesis.codigo}", f"{fecha:%d/%m/%Y %H:%M}",
                      url_for("docente.tesis_detalle", tesis_id=tesis.id))


def registrar_sustentacion(tesis, nota, usuario):
    if tesis.estado != "sustentacion_programada":
        raise TesisError("Primero debe programarse la sustentacion.")
    if nota is None or not 0 <= nota <= 20:
        raise TesisError("La nota de sustentacion debe estar entre 0 y 20.")
    tesis.nota_sustentacion = nota
    tesis.estado = "sustentada"
    registrar_evento(tesis, "sustentada", f"Tesis sustentada con nota {nota:.0f}.", usuario)
    _notificar_estudiantes(tesis, "Su tesis fue registrada como sustentada", f"Nota: {nota:.0f}")
