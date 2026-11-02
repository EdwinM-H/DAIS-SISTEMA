"""Perfiles academicos de los docentes: avance, validaciones y datos oficiales (DAIS)."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.orm import selectinload

from models import db, Docente, CambioPerfil
from models.docente import CATEGORIAS, GRADOS, CONDICIONES
from services import perfil_service
from utils import gestion_required

perfiles_bp = Blueprint("perfiles", __name__, url_prefix="/perfiles")


@perfiles_bp.route("/")
@gestion_required
def index():
    filtro = request.args.get("filtro", "")
    docentes = (Docente.query.options(selectinload(Docente.temas), selectinload(Docente.cambios_perfil))
                .filter_by(estado="activo").order_by(Docente.apellidos, Docente.nombres).all())
    resumen = perfil_service.avance(docentes)
    if filtro == "incompletos":
        docentes = [d for d in docentes if not d.perfil_completo]
    elif filtro == "prelacion":
        docentes = [d for d in docentes if d.faltantes_prelacion()]
    pendientes = CambioPerfil.query.filter_by(estado="pendiente").count()
    return render_template("perfiles/index.html", docentes=docentes, resumen=resumen, filtro=filtro, pendientes=pendientes)


@perfiles_bp.route("/recordatorio", methods=["POST"])
@gestion_required
def recordatorio():
    n = perfil_service.recordar(Docente.query.filter_by(estado="activo").all())
    db.session.commit()
    flash(f"Recordatorio enviado a {n} docente(s) con perfil incompleto." if n else "No hay docentes con cuenta y perfil incompleto.", "info")
    return redirect(url_for("perfiles.index"))


@perfiles_bp.route("/validaciones")
@gestion_required
def validaciones():
    estado = request.args.get("estado", "pendiente")
    q = CambioPerfil.query.options(selectinload(CambioPerfil.docente))
    if estado in ("pendiente", "aprobado", "rechazado"):
        q = q.filter_by(estado=estado)
    else:
        q = q.filter(CambioPerfil.estado != "directo")
    return render_template("perfiles/validaciones.html", cambios=q.order_by(CambioPerfil.creado_en.desc()).limit(300).all(),
                           estado=estado)


@perfiles_bp.route("/validaciones/<int:cambio_id>", methods=["POST"])
@gestion_required
def revisar(cambio_id):
    cambio = db.get_or_404(CambioPerfil, cambio_id)
    try:
        perfil_service.revisar(cambio, request.form.get("accion") == "aprobar", request.form.get("motivo"), current_user)
        db.session.commit()
        flash("Cambio revisado.", "success")
    except perfil_service.PerfilError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("perfiles.validaciones"))


@perfiles_bp.route("/<int:docente_id>", methods=["GET", "POST"])
@gestion_required
def editar(docente_id):
    docente = db.get_or_404(Docente, docente_id)
    if request.method == "POST":
        try:
            if request.form.get("seccion") == "afinidad":
                perfil_service.guardar_afinidad(
                    docente, [int(x) for x in request.form.getlist("lineas") if x.isdigit()],
                    [int(x) for x in request.form.getlist("temas") if x.isdigit()],
                    request.form.get("linea_principal", type=int),
                    request.form.get("experiencia_anios", type=int), current_user)
            else:
                perfil_service.guardar_oficial(docente, request.form, current_user)
            db.session.commit()
            flash("Perfil académico actualizado.", "success")
        except (perfil_service.PerfilError, ValueError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("perfiles.editar", docente_id=docente.id))
    return render_template("perfiles/editar.html", docente=docente, areas=perfil_service.catalogo(),
                           categorias=CATEGORIAS, grados=GRADOS, condiciones=CONDICIONES)
