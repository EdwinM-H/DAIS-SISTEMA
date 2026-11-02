"""Revision por la gestion del DAIS de la produccion academica declarada por los docentes."""

from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload

from models import db, Capacitacion, Investigacion, Docente, ESTADOS_VALIDACION
from utils import gestion_required, notificar

produccion_bp = Blueprint("produccion", __name__, url_prefix="/produccion")

MODELOS = {"capacitaciones": Capacitacion, "investigaciones": Investigacion}


@produccion_bp.route("/<tipo>")
@gestion_required
def index(tipo):
    modelo = MODELOS.get(tipo)
    if not modelo:
        return redirect(url_for("produccion.index", tipo="capacitaciones"))
    estado = request.args.get("estado", "pendiente")
    anio = request.args.get("anio", "")
    docente_id = request.args.get("docente", "")

    q = modelo.query.options(joinedload(modelo.docente))
    if estado in ESTADOS_VALIDACION:
        q = q.filter(modelo.estado_validacion == estado)
    if anio.isdigit():
        q = q.filter(modelo.anio == int(anio))
    if docente_id.isdigit():
        q = q.filter(modelo.docente_id == int(docente_id))
    items = q.order_by(modelo.anio.desc(), modelo.creado_en.desc()).limit(500).all()

    anios = [a for (a,) in db.session.query(modelo.anio).distinct().order_by(modelo.anio.desc()).all()]
    conteo = dict(db.session.query(modelo.estado_validacion, db.func.count(modelo.id)).group_by(modelo.estado_validacion).all())
    docentes = Docente.query.order_by(Docente.apellidos).all()
    return render_template("produccion/index.html", tipo=tipo, items=items, estado=estado, anio=anio,
                           docente_id=docente_id, anios=anios, conteo=conteo, docentes=docentes,
                           estados=ESTADOS_VALIDACION)


@produccion_bp.route("/<tipo>/<int:item_id>/validar", methods=["POST"])
@gestion_required
def validar(tipo, item_id):
    modelo = MODELOS.get(tipo)
    if not modelo:
        return redirect(url_for("produccion.index", tipo="capacitaciones"))
    item = db.get_or_404(modelo, item_id)
    estado = request.form.get("estado")
    observacion = request.form.get("observacion", "").strip()
    if estado not in ("validado", "observado"):
        flash("Accion no valida.", "danger")
    elif estado == "observado" and not observacion:
        flash("Indique el motivo de la observacion.", "warning")
    else:
        item.estado_validacion = estado
        item.observacion_validacion = observacion or None
        item.fecha_validacion = datetime.now()
        item.validado_por_id = current_user.id
        nombre = getattr(item, "nombre", None) or getattr(item, "titulo", "")
        if item.docente.usuario:
            destino = "docente.capacitaciones" if tipo == "capacitaciones" else "docente.investigaciones"
            notificar(
                item.docente.usuario,
                f"Su registro fue {'validado' if estado == 'validado' else 'observado'}",
                f"{nombre[:150]}" + (f" — {observacion}" if observacion else ""),
                url_for(destino),
            )
        db.session.commit()
        flash("Registro actualizado.", "success")
    return redirect(request.referrer or url_for("produccion.index", tipo=tipo))
