from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from flask_login import current_user
from sqlalchemy.orm import joinedload

from models import (
    db, Docente, DocenteSemestre, Evaluacion, CriterioNorma, CRITERIOS_NORMA, Semestre,
)
from models.docente import ESCUELA_DEFAULT, titulo
from services.evaluacion_service import analisis_docente, historial_docente, mapa_posiciones
from services.excel_service import a_numero
from services.proceso_service import recalcular_docente
from utils import gestion_required, direccion_required

docentes_bp = Blueprint("docentes", __name__)

CAMPOS_TEXTO = ("especialidad", "grado_academico", "categoria_docente", "correo_institucional",
                "telefono", "departamento", "dni")


@docentes_bp.route("/docentes")
@gestion_required
def index():
    semestre_id = session.get("semestre_id")
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")
    solo_semestre = request.args.get("todos") != "1"

    query = Docente.query.options(joinedload(Docente.usuario))
    if semestre_id and solo_semestre:
        query = query.join(DocenteSemestre).filter(DocenteSemestre.semestre_id == semestre_id)
    if q:
        patron = f"%{q}%"
        query = query.filter(db.or_(
            Docente.nombres.ilike(patron), Docente.apellidos.ilike(patron),
            Docente.codigo.ilike(patron), Docente.nombre_normalizado.ilike(f"%{q.upper()}%"),
        ))
    if estado in ("activo", "inactivo"):
        query = query.filter(Docente.estado == estado)
    docentes = query.order_by(Docente.apellidos, Docente.nombres).all()

    evaluaciones, modalidades, posiciones = {}, {}, {}
    if semestre_id:
        evaluaciones = {e.docente_id: e for e in Evaluacion.query.filter_by(semestre_id=semestre_id)}
        modalidades = dict(db.session.query(DocenteSemestre.docente_id, DocenteSemestre.modalidad)
                           .filter_by(semestre_id=semestre_id).all())
        posiciones = mapa_posiciones(semestre_id)

    filas = [{
        "docente": d,
        "evaluacion": evaluaciones.get(d.id),
        "estado": evaluaciones[d.id].estado_evaluacion if d.id in evaluaciones else "Pendiente",
        "modalidad": modalidades.get(d.id) or "",
        "posicion": posiciones.get(d.id),
    } for d in docentes]

    return render_template("docentes/lista.html", filas=filas, q=q, estado=estado, solo_semestre=solo_semestre)


def _leer_formulario(docente):
    docente.nombres = titulo(request.form.get("nombres", "").strip()) or docente.nombres
    docente.apellidos = titulo(request.form.get("apellidos", "").strip()) or docente.apellidos
    for campo in CAMPOS_TEXTO:
        setattr(docente, campo, request.form.get(campo, "").strip() or None)
    docente.escuela = request.form.get("escuela", "").strip() or ESCUELA_DEFAULT
    anio = request.form.get("anio_ingreso", "").strip()
    docente.anio_ingreso = int(anio) if anio.isdigit() and 1950 <= int(anio) <= 2100 else None
    if request.form.get("estado") in ("activo", "inactivo"):
        docente.estado = request.form["estado"]


def _validar_unicos(docente):
    if docente.dni and Docente.query.filter(Docente.dni == docente.dni, Docente.id != (docente.id or 0)).first():
        return f"El DNI {docente.dni} ya esta registrado."
    duplicado = Docente.buscar_por_nombre(f"{docente.apellidos} {docente.nombres}")
    if duplicado and duplicado.id != docente.id:
        return f"Ya existe un docente con ese nombre ({duplicado.codigo})."
    return None


@docentes_bp.route("/docentes/crear", methods=["GET", "POST"])
@gestion_required
def crear():
    docente = Docente(codigo=Docente.siguiente_codigo(), nombres="", apellidos="", escuela=ESCUELA_DEFAULT)
    if request.method == "POST":
        docente.codigo = request.form.get("codigo", "").strip() or Docente.siguiente_codigo()
        _leer_formulario(docente)
        error = None
        if not docente.nombres or not docente.apellidos:
            error = "Nombres y apellidos son obligatorios."
        elif Docente.query.filter_by(codigo=docente.codigo).first():
            error = f"Ya existe un docente con codigo {docente.codigo}."
        else:
            error = _validar_unicos(docente)
        if error:
            flash(error, "danger")
            return render_template("docentes/formulario.html", docente=docente, nuevo=True)

        db.session.add(docente)
        db.session.flush()
        semestre_id = session.get("semestre_id")
        if semestre_id:
            db.session.add(DocenteSemestre(docente_id=docente.id, semestre_id=semestre_id,
                                           modalidad=request.form.get("modalidad", "").strip() or None))
        db.session.commit()
        flash("Docente registrado correctamente.", "success")
        return redirect(url_for("docentes.detalle", docente_id=docente.id))
    return render_template("docentes/formulario.html", docente=docente, nuevo=True)


@docentes_bp.route("/docentes/<int:docente_id>")
@gestion_required
def detalle(docente_id):
    docente = db.get_or_404(Docente, docente_id)
    semestre_id = session.get("semestre_id")
    analisis = analisis_docente(docente.id, semestre_id) if semestre_id else None
    part = DocenteSemestre.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first() if semestre_id else None
    return render_template(
        "docentes/detalle.html",
        docente=docente,
        analisis=analisis,
        participacion=part,
        historial=historial_docente(docente.id),
    )


@docentes_bp.route("/docentes/<int:docente_id>/editar", methods=["GET", "POST"])
@gestion_required
def editar(docente_id):
    docente = db.get_or_404(Docente, docente_id)
    if request.method == "POST":
        _leer_formulario(docente)
        error = _validar_unicos(docente)
        if error:
            db.session.rollback()
            flash(error, "danger")
            return redirect(url_for("docentes.editar", docente_id=docente.id))
        semestre_id = session.get("semestre_id")
        if semestre_id:
            part = DocenteSemestre.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
            modalidad = request.form.get("modalidad", "").strip() or None
            if part:
                part.modalidad = modalidad
            elif request.form.get("participa") == "1":
                db.session.add(DocenteSemestre(docente_id=docente.id, semestre_id=semestre_id, modalidad=modalidad))
        if docente.usuario:
            docente.usuario.nombre_completo = docente.nombre_natural
            docente.usuario.email = docente.correo_institucional
            if docente.estado == "inactivo":
                docente.usuario.activo = False
        db.session.commit()
        flash("Datos del docente actualizados.", "success")
        return redirect(url_for("docentes.detalle", docente_id=docente.id))
    part = None
    if session.get("semestre_id"):
        part = DocenteSemestre.query.filter_by(docente_id=docente.id, semestre_id=session["semestre_id"]).first()
    return render_template("docentes/formulario.html", docente=docente, nuevo=False, participacion=part)


@docentes_bp.route("/docentes/<int:docente_id>/evaluacion", methods=["GET", "POST"])
@gestion_required
def evaluacion(docente_id):
    """Registro o correccion manual de la evaluacion del semestre de trabajo."""
    docente = db.get_or_404(Docente, docente_id)
    semestre_id = session.get("semestre_id")
    if not semestre_id:
        flash("Seleccione un semestre primero.", "warning")
        return redirect(url_for("docentes.detalle", docente_id=docente_id))
    semestre = db.session.get(Semestre, semestre_id)
    ev = Evaluacion.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first()
    crit = CriterioNorma.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first()

    if request.method == "POST":
        errores = []

        def nota(campo, maximo):
            valor = a_numero(request.form.get(campo))
            if valor is not None and not 0 <= valor <= maximo:
                errores.append(f"{campo.replace('_', ' ').capitalize()}: debe estar entre 0 y {maximo}.")
            return valor

        encuesta = nota("encuesta", 10)
        autoeval = nota("autoevaluacion", 10)
        valores_crit = {c: nota(c, maximo) for c, _, maximo in CRITERIOS_NORMA}
        normas_manual = nota("normas", 10)
        if errores:
            for e in errores:
                flash(e, "danger")
            return redirect(url_for("docentes.evaluacion", docente_id=docente_id))

        if not ev:
            ev = Evaluacion(docente_id=docente_id, semestre_id=semestre_id)
            db.session.add(ev)
        if any(v is not None for v in valores_crit.values()):
            if not crit:
                crit = CriterioNorma(docente_id=docente_id, semestre_id=semestre_id)
                db.session.add(crit)
            for c, v in valores_crit.items():
                setattr(crit, c, v)
            crit.calcular_subtotal()
            ev.normas = crit.nota_normas if all(v is not None for v in valores_crit.values()) else None
        else:
            ev.normas = normas_manual
        ev.encuesta = encuesta
        ev.autoevaluacion = autoeval
        # El promedio solo se recalcula si el semestre ya tiene resultados calculados
        recalcular_docente(ev, crit, semestre)
        ev.observaciones = request.form.get("observaciones", "").strip() or None
        ev.editado_manual = True
        if not DocenteSemestre.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first():
            db.session.add(DocenteSemestre(docente_id=docente_id, semestre_id=semestre_id))
        db.session.commit()
        if semestre.fecha_calculo:
            flash("Evaluacion guardada. Promedio y clasificacion del docente recalculados.", "success")
        else:
            flash("Evaluacion guardada. El promedio se obtendra al calcular los resultados del semestre.", "success")
        return redirect(url_for("docentes.detalle", docente_id=docente_id))

    return render_template("docentes/evaluacion.html", docente=docente, semestre=semestre,
                           ev=ev, crit=crit, criterios=CRITERIOS_NORMA)


@docentes_bp.route("/docentes/<int:docente_id>/cuenta", methods=["POST"])
@direccion_required
def crear_cuenta(docente_id):
    from services.cuentas_service import crear_cuenta_docente, restablecer_password

    docente = db.get_or_404(Docente, docente_id)
    if docente.usuario:
        password = restablecer_password(docente.usuario)
        docente.usuario.activo = True
        usuario = docente.usuario
        mensaje = "Contrasena restablecida"
    else:
        usuario, password = crear_cuenta_docente(docente)
        mensaje = "Cuenta creada"
    db.session.commit()
    return render_template("usuarios/credenciales.html", credenciales=[{
        "nombre": docente.nombre_completo, "codigo": docente.codigo,
        "username": usuario.username, "password": password,
    }], titulo=mensaje)


@docentes_bp.route("/docentes/<int:docente_id>/eliminar", methods=["POST"])
@direccion_required
def eliminar(docente_id):
    docente = db.get_or_404(Docente, docente_id)
    if docente.evaluaciones or docente.tesis_roles:
        abort(400, "No se puede eliminar un docente con evaluaciones o tesis; desactivelo.")
    if docente.usuario:
        db.session.delete(docente.usuario)
    db.session.delete(docente)
    db.session.commit()
    flash("Docente eliminado.", "info")
    return redirect(url_for("docentes.index"))
