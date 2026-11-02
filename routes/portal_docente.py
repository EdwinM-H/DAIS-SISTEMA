"""Portal del docente: resultados de evaluacion, produccion academica y tesis."""

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

from models import (
    db, Semestre, Evaluacion, Capacitacion, Investigacion, Tesis, TesisMiembro,
)
from models.produccion import TIPOS_CAPACITACION, TIPOS_INVESTIGACION, SUBTIPOS_INVESTIGACION
from services import tesis_service
from services.evaluacion_service import analisis_docente, historial_docente
from services.excel_service import a_numero
from utils import docente_required, guardar_archivo, eliminar_archivo, notificar_gestion

docente_bp = Blueprint("docente", __name__, url_prefix="/docente")


def _docente():
    return current_user.docente


def _semestres_publicados(docente):
    """Semestres publicados en los que el docente tiene evaluacion (mas reciente primero)."""
    sems = (
        Semestre.query.join(Evaluacion, Evaluacion.semestre_id == Semestre.id)
        .filter(Evaluacion.docente_id == docente.id, Semestre.publicado.is_(True))
        .all()
    )
    return sorted(sems, key=lambda s: s.orden, reverse=True)


@docente_bp.route("/")
@docente_required
def inicio():
    docente = _docente()
    semestres = _semestres_publicados(docente)
    sid = request.args.get("semestre", type=int)
    semestre = next((s for s in semestres if s.id == sid), semestres[0] if semestres else None)
    analisis = analisis_docente(docente.id, semestre.id) if semestre else None

    historial = [h for h in historial_docente(docente.id) if h["semestre"].publicado]
    tesis_pendientes = [
        m for m in docente.tesis_roles
        if m.rol == "dictaminante" and m.estado_revision == "pendiente"
        and m.tesis.estado not in ("sustentada", "anulada") and m.tesis.versiones
    ]
    return render_template(
        "portal_docente/inicio.html",
        docente=docente, semestre=semestre, semestres=semestres, analisis=analisis, historial=historial,
        tesis_pendientes=tesis_pendientes,
        resumen_produccion={
            "capacitaciones": len(docente.capacitaciones),
            "horas": sum(c.horas or 0 for c in docente.capacitaciones),
            "investigaciones": len(docente.investigaciones),
            "pendientes": sum(1 for x in docente.capacitaciones + docente.investigaciones if x.estado_validacion != "validado"),
        },
    )


# ----------------------------------------------------------------------
# Capacitaciones e investigaciones (CRUD comun)
# ----------------------------------------------------------------------
def _anio_form():
    valor = request.form.get("anio", "").strip()
    if not valor.isdigit() or not 1950 <= int(valor) <= datetime.now().year + 1:
        raise ValueError("Indique un anio valido.")
    return int(valor)


def _fecha_form(nombre):
    valor = request.form.get(nombre, "").strip()
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Fecha invalida.")


def _aplicar_archivo(item, carpeta):
    archivo = request.files.get("archivo")
    if archivo and archivo.filename:
        ruta, nombre = guardar_archivo(archivo, carpeta)
        eliminar_archivo(item.archivo_ruta)
        item.archivo_ruta, item.archivo_nombre = ruta, nombre


def _propio(modelo, item_id):
    item = db.get_or_404(modelo, item_id)
    if item.docente_id != current_user.docente_id:
        abort(403)
    return item


@docente_bp.route("/capacitaciones")
@docente_required
def capacitaciones():
    docente = _docente()
    anio = request.args.get("anio", type=int)
    items = [c for c in docente.capacitaciones if not anio or c.anio == anio]
    por_anio = {}
    for c in sorted(items, key=lambda c: (-c.anio, c.nombre)):
        por_anio.setdefault(c.anio, []).append(c)
    resumen = {}
    for c in docente.capacitaciones:
        r = resumen.setdefault(c.anio, {"cantidad": 0, "horas": 0})
        r["cantidad"] += 1
        r["horas"] += c.horas or 0
    return render_template("portal_docente/capacitaciones.html", por_anio=por_anio, anio=anio,
                           resumen=dict(sorted(resumen.items(), reverse=True)), tipos=TIPOS_CAPACITACION)


@docente_bp.route("/capacitaciones/guardar", methods=["POST"])
@docente_bp.route("/capacitaciones/<int:item_id>/guardar", methods=["POST"])
@docente_required
def guardar_capacitacion(item_id=None):
    item = _propio(Capacitacion, item_id) if item_id else Capacitacion(docente_id=current_user.docente_id)
    if item_id and item.estado_validacion == "validado" and item.origen == "excel":
        flash("Este registro fue cargado por el DAIS y ya esta validado.", "warning")
        return redirect(url_for("docente.capacitaciones"))
    try:
        nombre = request.form.get("nombre", "").strip()
        if not nombre:
            raise ValueError("Indique el nombre de la capacitacion.")
        item.nombre = nombre[:400]
        item.anio = _anio_form()
        item.tipo = request.form.get("tipo") or None
        item.institucion = request.form.get("institucion", "").strip() or None
        horas = a_numero(request.form.get("horas"))
        if horas is not None and not 0 <= horas <= 5000:
            raise ValueError("Horas fuera de rango.")
        item.horas = horas
        item.fecha_inicio = _fecha_form("fecha_inicio")
        item.fecha_fin = _fecha_form("fecha_fin")
        if item.fecha_inicio and item.fecha_fin and item.fecha_fin < item.fecha_inicio:
            raise ValueError("La fecha de fin no puede ser anterior a la de inicio.")
        _aplicar_archivo(item, f"docentes/{current_user.docente_id}/capacitaciones")
        item.estado_validacion = "pendiente"
        item.observacion_validacion = None
        item.origen = "docente"
        db.session.add(item)
        if not item_id:
            notificar_gestion("Nueva capacitacion registrada", f"{current_user.nombre_completo}: {item.nombre[:120]}",
                              url_for("produccion.index", tipo="capacitaciones"), roles=("admin", "director", "operador"))
        db.session.commit()
        flash("Capacitacion guardada. Quedara visible en su ficha cuando el DAIS la valide.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("docente.capacitaciones", anio=request.form.get("volver_anio") or None))


@docente_bp.route("/capacitaciones/<int:item_id>/eliminar", methods=["POST"])
@docente_required
def eliminar_capacitacion(item_id):
    item = _propio(Capacitacion, item_id)
    if item.estado_validacion == "validado":
        flash("No se puede eliminar un registro ya validado. Solicitelo al DAIS.", "warning")
    else:
        eliminar_archivo(item.archivo_ruta)
        db.session.delete(item)
        db.session.commit()
        flash("Capacitacion eliminada.", "info")
    return redirect(url_for("docente.capacitaciones"))


@docente_bp.route("/investigaciones")
@docente_required
def investigaciones():
    docente = _docente()
    tipo = request.args.get("tipo", "")
    items = [i for i in docente.investigaciones if not tipo or i.tipo == tipo]
    return render_template("portal_docente/investigaciones.html", items=items, tipo=tipo,
                           tipos=TIPOS_INVESTIGACION, subtipos=SUBTIPOS_INVESTIGACION)


@docente_bp.route("/investigaciones/guardar", methods=["POST"])
@docente_bp.route("/investigaciones/<int:item_id>/guardar", methods=["POST"])
@docente_required
def guardar_investigacion(item_id=None):
    item = _propio(Investigacion, item_id) if item_id else Investigacion(docente_id=current_user.docente_id)
    if item_id and item.estado_validacion == "validado" and item.origen == "excel":
        flash("Este registro fue cargado por el DAIS y ya esta validado.", "warning")
        return redirect(url_for("docente.investigaciones"))
    try:
        titulo_inv = request.form.get("titulo", "").strip()
        if not titulo_inv:
            raise ValueError("Indique el titulo del trabajo.")
        item.titulo = titulo_inv[:600]
        item.anio = _anio_form()
        item.tipo = request.form.get("tipo") if request.form.get("tipo") in TIPOS_INVESTIGACION else "Otro"
        item.subtipo = request.form.get("subtipo") or None
        item.medio = request.form.get("medio", "").strip() or None
        item.enlace = request.form.get("enlace", "").strip() or None
        if item.enlace and not item.enlace.lower().startswith(("http://", "https://", "doi:", "10.")):
            raise ValueError("El enlace debe ser una URL (http/https) o un DOI.")
        item.rol_autor = request.form.get("rol_autor", "").strip() or None
        _aplicar_archivo(item, f"docentes/{current_user.docente_id}/investigaciones")
        item.estado_validacion = "pendiente"
        item.observacion_validacion = None
        item.origen = "docente"
        db.session.add(item)
        if not item_id:
            notificar_gestion("Nueva publicacion/investigacion registrada", f"{current_user.nombre_completo}: {item.titulo[:120]}",
                              url_for("produccion.index", tipo="investigaciones"), roles=("admin", "director", "operador"))
        db.session.commit()
        flash("Registro guardado. Quedara visible en su ficha cuando el DAIS lo valide.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("docente.investigaciones"))


@docente_bp.route("/investigaciones/<int:item_id>/eliminar", methods=["POST"])
@docente_required
def eliminar_investigacion(item_id):
    item = _propio(Investigacion, item_id)
    if item.estado_validacion == "validado":
        flash("No se puede eliminar un registro ya validado. Solicitelo al DAIS.", "warning")
    else:
        eliminar_archivo(item.archivo_ruta)
        db.session.delete(item)
        db.session.commit()
        flash("Registro eliminado.", "info")
    return redirect(url_for("docente.investigaciones"))


# ----------------------------------------------------------------------
# Tesis
# ----------------------------------------------------------------------
@docente_bp.route("/tesis")
@docente_required
def tesis():
    roles = sorted(_docente().tesis_roles, key=lambda m: (m.tesis.estado in ("sustentada", "anulada"), -m.tesis.id))
    return render_template("portal_docente/tesis.html", roles=roles)


def _membresias(tesis_obj):
    return [m for m in tesis_obj.miembros if m.docente_id == current_user.docente_id]


@docente_bp.route("/tesis/<int:tesis_id>")
@docente_required
def tesis_detalle(tesis_id):
    tesis_obj = db.get_or_404(Tesis, tesis_id)
    mios = _membresias(tesis_obj)
    if not mios:
        abort(403)
    return render_template("portal_docente/tesis_detalle.html", tesis=tesis_obj, mios=mios)


@docente_bp.route("/tesis/revision/<int:miembro_id>", methods=["POST"])
@docente_required
def revision(miembro_id):
    miembro = db.get_or_404(TesisMiembro, miembro_id)
    if miembro.docente_id != current_user.docente_id:
        abort(403)
    try:
        archivo = guardar_archivo(request.files.get("archivo"), f"tesis/{miembro.tesis_id}/dictamenes", {"pdf", "docx", "doc"})
        tesis_service.registrar_revision(miembro, request.form.get("estado"), request.form.get("observaciones"),
                                         current_user, archivo)
        db.session.commit()
        flash("Su revision fue registrada y notificada al estudiante.", "success")
    except (ValueError, tesis_service.TesisError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("docente.tesis_detalle", tesis_id=miembro.tesis_id))


# ----------------------------------------------------------------------
# Perfil
# ----------------------------------------------------------------------
@docente_bp.route("/perfil", methods=["GET", "POST"])
@docente_required
def perfil():
    docente = _docente()
    if request.method == "POST":
        for campo in ("telefono", "correo_institucional", "especialidad", "grado_academico"):
            setattr(docente, campo, request.form.get(campo, "").strip() or None)
        current_user.email = docente.correo_institucional
        db.session.commit()
        flash("Perfil actualizado.", "success")
        return redirect(url_for("docente.perfil"))
    return render_template("portal_docente/perfil.html", docente=docente)
