import glob
import os
import shutil

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from flask_login import current_user

from models import db, Importacion, Semestre
from models.importacion import TIPOS_IMPORTACION
from services import excel_service
from utils import gestion_required, extension, nombre_temporal_seguro

importacion_bp = Blueprint("importacion", __name__)


def _archivo_disponible():
    candidatos = sorted(glob.glob(os.path.join(current_app.config["DATA_FOLDER"], "*.xlsx")))
    return candidatos[0] if candidatos else None


def _ruta_temporal_valida(ruta):
    base = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    real = os.path.realpath(ruta or "")
    return real.startswith(base + os.sep) and os.path.isfile(real)


def _limpiar_preview():
    datos = session.pop("import_preview", None)
    if datos and _ruta_temporal_valida(datos.get("filepath")):
        try:
            os.remove(datos["filepath"])
        except OSError:
            pass


def _semestre():
    sid = session.get("semestre_id")
    return db.session.get(Semestre, sid) if sid else None


@importacion_bp.route("/importar")
@gestion_required
def index():
    disponible = _archivo_disponible()
    return render_template(
        "importacion/index.html",
        semestre_actual=_semestre(),
        historial=Importacion.query.order_by(Importacion.fecha_importacion.desc()).limit(20).all(),
        archivo_disponible=os.path.basename(disponible) if disponible else None,
        tipos=TIPOS_IMPORTACION,
    )


def _previsualizar(filepath, filename, tipo):
    if tipo == "ficha_integral":
        preview = excel_service.analizar_ficha_integral(filepath)
    else:
        preview = excel_service.analizar_tabla(filepath, tipo)
    session["import_preview"] = {"filepath": filepath, "filename": filename, "tipo": tipo}
    return render_template("importacion/preview.html", preview=preview, tipo=tipo,
                           tipo_nombre=TIPOS_IMPORTACION[tipo], filename=filename, semestre_actual=_semestre())


@importacion_bp.route("/importar/previsualizar", methods=["POST"])
@gestion_required
def previsualizar():
    if not _semestre():
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("importacion.index"))
    tipo = request.form.get("tipo", "ficha_integral")
    if tipo not in TIPOS_IMPORTACION:
        flash("Tipo de importacion no reconocido.", "danger")
        return redirect(url_for("importacion.index"))
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Seleccione un archivo.", "danger")
        return redirect(url_for("importacion.index"))
    permitidas = current_app.config["EXTENSIONES_IMPORTACION"]
    if extension(archivo.filename) not in permitidas or (tipo == "ficha_integral" and extension(archivo.filename) != "xlsx"):
        flash("Formato no permitido. Use .xlsx (o .csv para importaciones simples).", "danger")
        return redirect(url_for("importacion.index"))

    _limpiar_preview()
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_temporal_seguro(archivo.filename))
    archivo.save(filepath)
    return _previsualizar(filepath, archivo.filename, tipo)


@importacion_bp.route("/importar/usar-disponible", methods=["POST"])
@gestion_required
def usar_disponible():
    if not _semestre():
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("importacion.index"))
    disponible = _archivo_disponible()
    if not disponible:
        flash("No hay ningun Excel en la carpeta data/.", "danger")
        return redirect(url_for("importacion.index"))
    _limpiar_preview()
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_temporal_seguro(os.path.basename(disponible)))
    shutil.copyfile(disponible, filepath)
    return _previsualizar(filepath, os.path.basename(disponible), "ficha_integral")


@importacion_bp.route("/importar/confirmar", methods=["POST"])
@gestion_required
def confirmar():
    semestre = _semestre()
    datos = session.get("import_preview")
    if not semestre or not datos or not _ruta_temporal_valida(datos.get("filepath")):
        flash("La vista previa expiro. Vuelva a cargar el archivo.", "warning")
        return redirect(url_for("importacion.index"))

    tipo = datos["tipo"]
    if tipo == "ficha_integral":
        result = excel_service.importar_ficha_integral(datos["filepath"], semestre.id, current_user.id)
    else:
        result = excel_service.importar_tabla(datos["filepath"], tipo, semestre.id, current_user.id)
    _limpiar_preview()
    return render_template("importacion/resultado.html", result=result, tipo_nombre=TIPOS_IMPORTACION[tipo],
                           filename=datos["filename"], semestre_actual=semestre)


@importacion_bp.route("/importar/cancelar", methods=["POST"])
@gestion_required
def cancelar():
    _limpiar_preview()
    flash("Importacion cancelada.", "info")
    return redirect(url_for("importacion.index"))


@importacion_bp.route("/importar/<int:imp_id>")
@gestion_required
def detalle(imp_id):
    imp = db.get_or_404(Importacion, imp_id)
    return render_template("importacion/detalle.html", imp=imp)
