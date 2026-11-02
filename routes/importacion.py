"""Proceso de evaluacion: carga de datos por pasos (docentes, dimensiones y criterios) y calculo."""

import glob
import os
import shutil

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, current_app, send_file,
)
from flask_login import current_user

from models import db, Importacion, Semestre, CRITERIOS_NORMA
from models.evaluacion import DIMENSIONES
from models.importacion import TIPOS_IMPORTACION
from services import excel_service, proceso_service
from services.plantillas_service import generar_plantilla
from utils import gestion_required, direccion_required, extension, nombre_temporal_seguro

importacion_bp = Blueprint("importacion", __name__)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def _opciones():
    escala = request.form.get("escala") or request.args.get("escala") or ""
    return {"escala": escala} if escala in ("10", "20", "5", "100", "puntaje", "porcentaje") else {}


@importacion_bp.route("/evaluacion/proceso")
@importacion_bp.route("/importar")
@gestion_required
def index():
    semestre = _semestre()
    disponible = _archivo_disponible()
    estado = proceso_service.estado_proceso(semestre) if semestre else None
    historial = []
    if semestre:
        historial = (Importacion.query.filter_by(semestre_id=semestre.id)
                     .order_by(Importacion.fecha_importacion.desc()).limit(15).all())
    return render_template(
        "importacion/index.html",
        semestre_actual=semestre, estado=estado, historial=historial,
        archivo_disponible=os.path.basename(disponible) if disponible else None,
        criterios=CRITERIOS_NORMA, dimensiones=DIMENSIONES, tipos=TIPOS_IMPORTACION,
    )


def _previsualizar(filepath, filename, tipo, opciones):
    if tipo == "ficha_integral":
        preview = excel_service.analizar_ficha_integral(filepath)
    else:
        preview = excel_service.analizar_tabla(filepath, tipo, opciones)
    session["import_preview"] = {"filepath": filepath, "filename": filename, "tipo": tipo, "opciones": opciones}
    return render_template("importacion/preview.html", preview=preview, tipo=tipo, opciones=opciones,
                           tipo_nombre=TIPOS_IMPORTACION[tipo], filename=filename, semestre_actual=_semestre(),
                           campo_criterio=excel_service.tipo_criterio(tipo), criterios=CRITERIOS_NORMA,
                           maximo_criterio=excel_service.MAX_CRITERIO.get(excel_service.tipo_criterio(tipo)))


@importacion_bp.route("/importar/previsualizar", methods=["POST"])
@gestion_required
def previsualizar():
    if not _semestre():
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("importacion.index"))
    tipo = request.form.get("tipo", "")
    if tipo not in TIPOS_IMPORTACION:
        flash("Tipo de importacion no reconocido.", "danger")
        return redirect(url_for("importacion.index"))
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        flash("Seleccione un archivo.", "danger")
        return redirect(url_for("importacion.index"))
    ext = extension(archivo.filename)
    if ext not in current_app.config["EXTENSIONES_IMPORTACION"] or (tipo == "ficha_integral" and ext != "xlsx"):
        flash("Formato no permitido. Use .xlsx (o .csv).", "danger")
        return redirect(url_for("importacion.index"))

    _limpiar_preview()
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], nombre_temporal_seguro(archivo.filename))
    archivo.save(filepath)
    if tipo == "ficha_integral":
        return _previsualizar(filepath, archivo.filename, tipo, {})
    # Paso intermedio: el usuario elige hoja, fila de titulos y que columna es cada dato
    session["import_preview"] = {"filepath": filepath, "filename": archivo.filename, "tipo": tipo, "opciones": _opciones()}
    return _pantalla_columnas()


def _pantalla_columnas(hoja=None, fila_titulos=None):
    datos = session["import_preview"]
    tipo, opciones = datos["tipo"], datos.get("opciones") or {}
    try:
        info = excel_service.leer_hoja(datos["filepath"], hoja or opciones.get("hoja"),
                                       fila_titulos or opciones.get("fila_titulos"))
    except Exception as exc:
        flash(f"No se pudo leer el archivo: {exc}", "danger")
        return redirect(url_for("importacion.index"))
    mismo = opciones.get("columnas") and opciones.get("hoja") == info["hoja"] and opciones.get("fila_titulos") == info["fila_titulos"]
    if mismo:
        actual = opciones["columnas"]
    else:
        auto = excel_service.mapeo_automatico(info["cab"], tipo, info["grupos"])
        actual = {k: v for k, v in auto.items() if v is not None and v != []}
    return render_template(
        "importacion/columnas.html",
        info=info, tipo=tipo, tipo_nombre=TIPOS_IMPORTACION[tipo], filename=datos["filename"],
        semestre_actual=_semestre(), opciones=opciones, actual=actual,
        campos_identidad=excel_service.CAMPOS_IDENTIDAD, campos=excel_service.campos_mapeo(tipo),
        usa_valores=excel_service.usa_valores(tipo), campo_criterio=excel_service.tipo_criterio(tipo),
        maximo_criterio=excel_service.MAX_CRITERIO.get(excel_service.tipo_criterio(tipo)),
        muestra=info["filas"][:8],
    )


@importacion_bp.route("/importar/columnas", methods=["GET", "POST"])
@gestion_required
def columnas():
    datos = session.get("import_preview")
    if not datos or not _ruta_temporal_valida(datos.get("filepath")) or datos["tipo"] == "ficha_integral":
        flash("La carga expiro. Vuelva a subir el archivo.", "warning")
        return redirect(url_for("importacion.index"))
    if request.method == "GET":
        return _pantalla_columnas(request.args.get("hoja"), request.args.get("fila_titulos", type=int))

    tipo = datos["tipo"]
    seleccion = {}
    for campo, _ in excel_service.CAMPOS_IDENTIDAD + excel_service.campos_mapeo(tipo):
        valor = request.form.get(f"col_{campo}", "")
        if valor.isdigit():
            seleccion[campo] = int(valor)
    if excel_service.usa_valores(tipo):
        seleccion["valores"] = [int(v) for v in request.form.getlist("col_valores") if v.isdigit()]
    opciones = {
        "hoja": request.form.get("hoja"),
        "fila_titulos": request.form.get("fila_titulos", type=int),
        "columnas": seleccion,
    }
    escala = request.form.get("escala", "")
    if escala in ("10", "20", "5", "100", "puntaje", "porcentaje"):
        opciones["escala"] = escala
    datos["opciones"] = opciones
    session["import_preview"] = datos
    session.modified = True
    return _previsualizar(datos["filepath"], datos["filename"], tipo, opciones)


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
    return _previsualizar(filepath, os.path.basename(disponible), "ficha_integral", {})


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
        result = excel_service.importar_tabla(datos["filepath"], tipo, semestre.id, current_user.id, datos.get("opciones"))
    _limpiar_preview()
    return render_template("importacion/resultado.html", result=result, tipo=tipo, tipo_nombre=TIPOS_IMPORTACION[tipo],
                           filename=datos["filename"], semestre_actual=semestre)


@importacion_bp.route("/importar/cancelar", methods=["POST"])
@gestion_required
def cancelar():
    _limpiar_preview()
    flash("Importacion cancelada.", "info")
    return redirect(url_for("importacion.index"))


@importacion_bp.route("/importar/plantilla/<tipo>")
@gestion_required
def plantilla(tipo):
    semestre = _semestre()
    if not semestre or tipo not in TIPOS_IMPORTACION or tipo == "ficha_integral":
        flash("Plantilla no disponible.", "warning")
        return redirect(url_for("importacion.index"))
    buf, nombre = generar_plantilla(tipo, semestre, _opciones().get("escala"))
    return send_file(buf, as_attachment=True, download_name=nombre, mimetype=XLSX_MIME)


@importacion_bp.route("/evaluacion/calcular", methods=["POST"])
@direccion_required
def calcular():
    semestre = _semestre()
    if not semestre:
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("importacion.index"))
    try:
        r = proceso_service.calcular_resultados(semestre, excluir_incompletos=request.form.get("excluir") == "1")
        mensaje = f"Resultados calculados para {r['calculados']} docente(s)."
        if r["excluidos"]:
            mensaje += f" {r['excluidos']} quedaron sin resultado por datos incompletos."
        flash(mensaje, "success")
        return redirect(url_for("ranking.index"))
    except proceso_service.ProcesoError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("importacion.index"))


@importacion_bp.route("/importar/<int:imp_id>")
@gestion_required
def detalle(imp_id):
    imp = db.get_or_404(Importacion, imp_id)
    return render_template("importacion/detalle.html", imp=imp)
