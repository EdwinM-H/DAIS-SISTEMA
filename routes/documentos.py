import os

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
    current_app,
    abort,
)
from flask_login import current_user
from utils import gestion_required
from sqlalchemy.orm import joinedload

from models import db, Docente, Evaluacion, Semestre, DocenteSemestre, DocumentoGenerado
from services.ficha_service import (
    FichaError,
    plantilla_disponible,
    construir_mapeo,
    generar_docx_bytes,
    generar_zip_bytes,
    guardar_copia_local,
    calcular_posicion_mapa,
)

documentos_bp = Blueprint("documentos", __name__)

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docentes_del_semestre(semestre_id):
    """Docentes del semestre activo con evaluacion, posicion y estado de ficha."""
    participaciones = (
        DocenteSemestre.query.options(joinedload(DocenteSemestre.docente))
        .filter_by(semestre_id=semestre_id)
        .join(Docente, DocenteSemestre.docente_id == Docente.id)
        .order_by(Docente.apellidos, Docente.nombres)
        .all()
    )

    posiciones = calcular_posicion_mapa(semestre_id)
    generados = {
        g.docente_id: g
        for g in DocumentoGenerado.query.filter_by(semestre_id=semestre_id)
        .order_by(DocumentoGenerado.fecha_generacion.desc())
        .all()
    }

    evaluaciones = {e.docente_id: e for e in Evaluacion.query.filter_by(semestre_id=semestre_id)}
    lista = []
    for part in participaciones:
        doc = part.docente
        if not doc:
            continue
        ev = evaluaciones.get(doc.id)
        registro = generados.get(doc.id)
        completa = bool(ev and ev.promedio_final is not None)
        lista.append({
            "docente": doc,
            "modalidad": part.modalidad or "",
            "evaluacion": ev,
            "promedio_final": ev.promedio_final if ev else None,
            "clasificacion": ev.clasificacion if ev else None,
            "posicion": posiciones.get(doc.id),
            "generada": registro is not None,
            "registro": registro,
            "con_datos": completa,
        })
    return lista


@documentos_bp.route("/documentos")
@gestion_required
def index():
    semestre_id = session.get("semestre_id")
    semestre_actual = db.session.get(Semestre, semestre_id) if semestre_id else None

    if not semestre_actual:
        return render_template("documentos.html", semestre_actual=None)

    docentes_lista = _docentes_del_semestre(semestre_actual.id)

    historial = (
        DocumentoGenerado.query.options(
            joinedload(DocumentoGenerado.docente), joinedload(DocumentoGenerado.semestre)
        )
        .filter_by(semestre_id=semestre_actual.id)
        .order_by(DocumentoGenerado.fecha_generacion.desc())
        .limit(30)
        .all()
    )

    total = len(docentes_lista)
    con_datos = sum(1 for d in docentes_lista if d["con_datos"])
    generadas = sum(1 for d in docentes_lista if d["generada"])

    return render_template(
        "documentos.html",
        semestre_actual=semestre_actual,
        docentes_lista=docentes_lista,
        historial=historial,
        resumen={
            "total": total,
            "con_datos": con_datos,
            "generadas": generadas,
            "pendientes": max(con_datos - generadas, 0),
        },
        plantilla_ok=plantilla_disponible(),
    )


@documentos_bp.route("/documentos/preview/<int:docente_id>")
@gestion_required
def preview(docente_id):
    semestre_id = session.get("semestre_id")
    if not semestre_id:
        abort(400)
    try:
        contexto = construir_mapeo(docente_id, semestre_id)
    except FichaError as exc:
        return render_template("documentos_preview.html", error=str(exc)), 200

    return render_template("documentos_preview.html", ctx=contexto)


@documentos_bp.route("/documentos/generar/<int:docente_id>/<int:semestre_id>")
@gestion_required
def generar_individual(docente_id, semestre_id):
    try:
        buffer, filename, contexto = generar_docx_bytes(docente_id, semestre_id)
    except FichaError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("documentos.index"))

    ruta_rel, nombre_guardado = guardar_copia_local(
        current_app, buffer, filename, contexto["semestre"].codigo
    )

    db.session.add(DocumentoGenerado(
        semestre_id=semestre_id,
        docente_id=docente_id,
        usuario_id=current_user.id,
        nombre_archivo=nombre_guardado,
        ruta_archivo=ruta_rel,
        tipo="individual",
    ))
    db.session.commit()

    flash("Ficha generada correctamente: {}".format(nombre_guardado), "success")

    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype=DOCX_MIMETYPE)


def _procesar_multiple(docentes_ids):
    """Flujo comun para generacion multiple. Devuelve respuesta send_file o redirect."""
    semestre_id = session.get("semestre_id")
    if not semestre_id:
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("documentos.index"))

    ids_validos = []
    for valor in docentes_ids:
        try:
            ids_validos.append(int(valor))
        except (TypeError, ValueError):
            continue

    if not ids_validos:
        flash("Seleccione al menos un docente.", "warning")
        return redirect(url_for("documentos.index"))

    try:
        zip_buffer, nombre_zip, generados, fallos = generar_zip_bytes(ids_validos, semestre_id)
    except FichaError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("documentos.index"))

    for filename, ctx in generados:
        copia = _clonar_buffer_zip_member(zip_buffer, filename)
        ruta_rel, nombre_guardado = guardar_copia_local(
            current_app, copia, filename, ctx["semestre"].codigo
        )
        db.session.add(DocumentoGenerado(
            semestre_id=ctx["semestre"].id,
            docente_id=ctx["docente"].id,
            usuario_id=current_user.id,
            nombre_archivo=nombre_guardado,
            ruta_archivo=ruta_rel,
            tipo="masivo",
        ))
    db.session.commit()

    cantidad = len(generados)
    if cantidad == 1:
        flash("1 ficha generada correctamente.", "success")
    else:
        flash("{} fichas generadas correctamente.".format(cantidad), "success")

    if fallos:
        nombres = ", ".join(nombre for nombre, _ in fallos[:4])
        extra = "" if len(fallos) <= 4 else " y {} mas.".format(len(fallos) - 4)
        flash(
            "{} ficha(s) no pudieron generarse por falta de informacion: {}{}.".format(
                len(fallos), nombres, extra
            ),
            "warning",
        )

    flash("Se genero el archivo ZIP correctamente: {}".format(nombre_zip), "info")
    zip_buffer.seek(0)
    return send_file(zip_buffer, as_attachment=True, download_name=nombre_zip, mimetype="application/zip")


def _clonar_buffer_zip_member(zip_buffer, filename):
    import io
    import zipfile

    data = None
    with zipfile.ZipFile(zip_buffer, "r") as zf:
        data = zf.read(filename)
    buffer = io.BytesIO(data)
    buffer.seek(0)
    return buffer


@documentos_bp.route("/documentos/generar-multiple", methods=["POST"])
@gestion_required
def generar_multiple():
    return _procesar_multiple(request.form.getlist("docentes_ids"))


@documentos_bp.route("/documentos/masivo", methods=["POST"])
@gestion_required
def generar_masivo():
    """Genera las fichas de todos los docentes con datos del semestre activo."""
    semestre_id = session.get("semestre_id")
    if not semestre_id:
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("documentos.index"))

    ids = [
        row.docente_id
        for row in DocenteSemestre.query.with_entities(DocenteSemestre.docente_id)
        .filter_by(semestre_id=semestre_id)
        .all()
    ]
    if not ids:
        flash("No hay docentes registrados en este semestre.", "warning")
        return redirect(url_for("documentos.index"))

    return _procesar_multiple(ids)


@documentos_bp.route("/documentos/download/<int:documento_id>")
@gestion_required
def download(documento_id):
    registro = db.session.get(DocumentoGenerado, documento_id)
    if not registro:
        abort(404)

    ruta_completa = os.path.join(current_app.config["GENERATED_FOLDER"], registro.ruta_archivo)
    if not os.path.exists(ruta_completa):
        # Regenerar en caliente si la copia local ya no existe
        try:
            buffer, filename, contexto = generar_docx_bytes(registro.docente_id, registro.semestre_id)
        except FichaError:
            flash("El archivo ya no esta disponible y no pudo regenerarse.", "danger")
            return redirect(url_for("documentos.index"))
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype=DOCX_MIMETYPE)

    return send_file(
        ruta_completa,
        as_attachment=True,
        download_name=registro.nombre_archivo,
        mimetype=DOCX_MIMETYPE,
    )


@documentos_bp.route("/documentos/historial")
@gestion_required
def historial():
    semestre_id = session.get("semestre_id")
    semestre_actual = db.session.get(Semestre, semestre_id) if semestre_id else None
    if not semestre_actual:
        return render_template("documentos_historial.html", semestre_actual=None, registros=[])

    registros = (
        DocumentoGenerado.query.options(
            joinedload(DocumentoGenerado.docente), joinedload(DocumentoGenerado.semestre)
        )
        .filter_by(semestre_id=semestre_actual.id)
        .order_by(DocumentoGenerado.fecha_generacion.desc())
        .all()
    )
    return render_template(
        "documentos_historial.html", semestre_actual=semestre_actual, registros=registros
    )
