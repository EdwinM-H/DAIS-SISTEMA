"""Descarga de archivos almacenados, verificando que el usuario tenga acceso."""

from flask import Blueprint, send_file, abort
from flask_login import login_required, current_user

from models import db, Capacitacion, Investigacion, TesisVersion, Dictamen, CambioPerfil
from utils import ruta_absoluta

archivos_bp = Blueprint("archivos", __name__, url_prefix="/archivos")


def _es_parte_de_tesis(tesis):
    if current_user.es_gestion:
        return True
    if current_user.es_docente and any(m.docente_id == current_user.docente_id for m in tesis.miembros):
        return True
    if current_user.es_estudiante and current_user.estudiante in tesis.estudiantes:
        return True
    return False


@archivos_bp.route("/<tipo>/<int:item_id>")
@login_required
def descargar(tipo, item_id):
    if tipo in ("capacitacion", "investigacion"):
        item = db.get_or_404(Capacitacion if tipo == "capacitacion" else Investigacion, item_id)
        if not (current_user.es_gestion or item.docente_id == current_user.docente_id):
            abort(403)
        ruta, nombre = item.archivo_ruta, item.archivo_nombre
    elif tipo == "tesis":
        item = db.get_or_404(TesisVersion, item_id)
        if not _es_parte_de_tesis(item.tesis):
            abort(403)
        ruta, nombre = item.archivo_ruta, item.archivo_nombre
    elif tipo == "subsanacion":
        item = db.get_or_404(TesisVersion, item_id)
        if not _es_parte_de_tesis(item.tesis):
            abort(403)
        ruta, nombre = item.subsanacion_ruta, item.subsanacion_nombre
    elif tipo == "dictamen":
        item = db.get_or_404(Dictamen, item_id)
        if not _es_parte_de_tesis(item.tesis):
            abort(403)
        ruta, nombre = item.archivo_ruta, item.archivo_nombre
    elif tipo == "perfil":
        item = db.get_or_404(CambioPerfil, item_id)
        if not (current_user.es_gestion or item.docente_id == current_user.docente_id):
            abort(403)
        ruta, nombre = item.archivo_ruta, item.archivo_nombre
    else:
        abort(404)

    absoluta = ruta_absoluta(ruta)
    if not absoluta:
        abort(404)
    return send_file(absoluta, as_attachment=True, download_name=nombre or "archivo")
