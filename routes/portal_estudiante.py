"""Portal del estudiante: seguimiento de su tesis."""

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

from models import db, Tesis
from services import tesis_service
from utils import estudiante_required, guardar_archivo

estudiante_bp = Blueprint("estudiante", __name__, url_prefix="/estudiante")


@estudiante_bp.route("/")
@estudiante_required
def inicio():
    tesis = current_user.estudiante.tesis
    if len(tesis) == 1:
        return redirect(url_for("estudiante.mi_tesis", tesis_id=tesis[0].id))
    return render_template("portal_estudiante/inicio.html", tesis=tesis)


def _tesis_propia(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    if current_user.estudiante not in tesis.estudiantes:
        abort(403)
    return tesis


@estudiante_bp.route("/tesis/<int:tesis_id>")
@estudiante_required
def mi_tesis(tesis_id):
    tesis = _tesis_propia(tesis_id)
    return render_template("portal_estudiante/tesis.html", tesis=tesis,
                           estado_revision=tesis_service.estado_revision(tesis),
                           textos_revision=tesis_service.ESTADOS_REVISION_TEXTO,
                           hay_observaciones=tesis_service.hay_observaciones_pendientes(tesis))


@estudiante_bp.route("/tesis/<int:tesis_id>/version", methods=["POST"])
@estudiante_required
def subir_version(tesis_id):
    tesis = _tesis_propia(tesis_id)
    try:
        ruta, nombre = guardar_archivo(request.files.get("archivo"), f"tesis/{tesis.id}", {"pdf", "docx", "doc"})
        if not ruta:
            raise ValueError("Seleccione el archivo (PDF o Word).")
        sub = guardar_archivo(request.files.get("subsanacion"), f"tesis/{tesis.id}", {"pdf", "docx", "doc"})
        tesis_service.subir_version(tesis, ruta, nombre, request.form.get("comentario"), current_user, sub)
        db.session.commit()
        flash("Documento enviado. Sus revisores fueron notificados.", "success")
    except (ValueError, tesis_service.TesisError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("estudiante.mi_tesis", tesis_id=tesis.id))
