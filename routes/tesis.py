"""Gestion de tesis por la Direccion del DAIS."""

from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from models import (
    db, Tesis, TesisMiembro, Estudiante, Docente, Semestre, ESTADOS_TESIS, ROLES_TESIS,
)
from models.docente import titulo
from services import tesis_service
from services.cuentas_service import crear_cuenta_estudiante
from services.excel_service import a_numero
from utils import gestion_required, direccion_required, guardar_archivo, semestre_sesion

tesis_bp = Blueprint("tesis", __name__, url_prefix="/tesis")


def _carga_docentes():
    """Numero de tesis activas por docente y rol (para repartir equitativamente)."""
    filas = (
        db.session.query(TesisMiembro.docente_id, TesisMiembro.rol, db.func.count(TesisMiembro.id))
        .join(Tesis).filter(Tesis.estado.notin_(("sustentada", "anulada")))
        .group_by(TesisMiembro.docente_id, TesisMiembro.rol).all()
    )
    carga = {}
    for did, rol, n in filas:
        carga.setdefault(did, {})[rol] = n
    return carga


@tesis_bp.route("/")
@gestion_required
def index():
    estado = request.args.get("estado", "")
    q = request.args.get("q", "").strip()
    query = Tesis.query.options(
        selectinload(Tesis.estudiantes), selectinload(Tesis.miembros).joinedload(TesisMiembro.docente)
    )
    if estado in ESTADOS_TESIS:
        query = query.filter(Tesis.estado == estado)
    if q:
        query = query.filter(db.or_(
            Tesis.titulo.ilike(f"%{q}%"), Tesis.codigo.ilike(f"%{q}%"),
            Tesis.estudiantes.any(Estudiante.apellidos.ilike(f"%{q}%")),
        ))
    tesis = query.order_by(Tesis.creado_en.desc()).all()
    conteo = dict(db.session.query(Tesis.estado, db.func.count(Tesis.id)).group_by(Tesis.estado).all())
    return render_template("tesis/index.html", tesis=tesis, estado=estado, q=q, estados=ESTADOS_TESIS, conteo=conteo)


def _estudiante_desde_form(prefijo=""):
    codigo = request.form.get(prefijo + "codigo", "").strip()
    if not codigo:
        return None, None
    est = Estudiante.query.filter_by(codigo=codigo).first()
    if est:
        return est, None
    nombres = titulo(request.form.get(prefijo + "nombres", "").strip())
    apellidos = titulo(request.form.get(prefijo + "apellidos", "").strip())
    if not nombres or not apellidos:
        return None, f"Complete nombres y apellidos del estudiante {codigo}."
    est = Estudiante(codigo=codigo, nombres=nombres, apellidos=apellidos,
                     correo=request.form.get(prefijo + "correo", "").strip() or None,
                     escuela="Escuela Profesional de Ingenieria de Sistemas")
    db.session.add(est)
    db.session.flush()
    return est, None


@tesis_bp.route("/nueva", methods=["GET", "POST"])
@direccion_required
def crear():
    if request.method == "POST":
        titulo_tesis = request.form.get("titulo", "").strip()
        if not titulo_tesis:
            flash("El titulo es obligatorio.", "danger")
            return render_template("tesis/formulario.html", tesis=None, docentes=_docentes_activos())
        estudiantes, errores = [], []
        for prefijo in ("e1_", "e2_"):
            est, err = _estudiante_desde_form(prefijo)
            if err:
                errores.append(err)
            if est:
                estudiantes.append(est)
        if not estudiantes:
            errores.append("Registre al menos un estudiante (codigo, nombres y apellidos).")
        if errores:
            db.session.rollback()
            for e in errores:
                flash(e, "danger")
            return render_template("tesis/formulario.html", tesis=None, docentes=_docentes_activos())

        sem = semestre_sesion()
        tesis = Tesis(
            codigo=Tesis.siguiente_codigo(date.today().year),
            titulo=titulo_tesis,
            resumen=request.form.get("resumen", "").strip() or None,
            linea_investigacion=request.form.get("linea_investigacion", "").strip() or None,
            modalidad=request.form.get("modalidad", "").strip() or "Tesis",
            resolucion=request.form.get("resolucion", "").strip() or None,
            fecha_registro=date.today(),
            fecha_limite_revision=_fecha(request.form.get("fecha_limite_revision")),
            semestre_id=sem.id if sem else None,
            creado_por_id=current_user.id,
        )
        tesis.estudiantes = estudiantes
        db.session.add(tesis)
        db.session.flush()
        tesis_service.registrar_evento(tesis, "registro", "Proyecto de tesis registrado.", current_user)

        asesor_id = request.form.get("asesor_id", "")
        if asesor_id.isdigit():
            try:
                tesis_service.asignar_miembro(tesis, db.session.get(Docente, int(asesor_id)), "asesor", current_user)
            except tesis_service.TesisError as exc:
                flash(str(exc), "warning")
        db.session.commit()
        flash(f"Tesis {tesis.codigo} registrada.", "success")
        return redirect(url_for("tesis.detalle", tesis_id=tesis.id))
    return render_template("tesis/formulario.html", tesis=None, docentes=_docentes_activos())


def _docentes_activos():
    return Docente.query.filter_by(estado="activo").order_by(Docente.apellidos, Docente.nombres).all()


def _fecha(valor, con_hora=False):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%dT%H:%M" if con_hora else "%Y-%m-%d") if con_hora \
            else datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


@tesis_bp.route("/<int:tesis_id>")
@gestion_required
def detalle(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    return render_template("tesis/detalle.html", tesis=tesis, docentes=_docentes_activos(),
                           roles=ROLES_TESIS, carga=_carga_docentes())


@tesis_bp.route("/<int:tesis_id>/editar", methods=["GET", "POST"])
@direccion_required
def editar(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    if request.method == "POST":
        tesis.titulo = request.form.get("titulo", "").strip() or tesis.titulo
        tesis.resumen = request.form.get("resumen", "").strip() or None
        tesis.linea_investigacion = request.form.get("linea_investigacion", "").strip() or None
        tesis.modalidad = request.form.get("modalidad", "").strip() or tesis.modalidad
        tesis.resolucion = request.form.get("resolucion", "").strip() or None
        tesis.fecha_limite_revision = _fecha(request.form.get("fecha_limite_revision"))
        tesis_service.registrar_evento(tesis, "edicion", "Datos generales actualizados.", current_user)
        db.session.commit()
        flash("Tesis actualizada.", "success")
        return redirect(url_for("tesis.detalle", tesis_id=tesis.id))
    return render_template("tesis/formulario.html", tesis=tesis, docentes=_docentes_activos())


@tesis_bp.route("/<int:tesis_id>/asignar", methods=["POST"])
@direccion_required
def asignar(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    rol = request.form.get("rol", "")
    ids = [int(x) for x in request.form.getlist("docente_id") if x.isdigit()]
    if not ids:
        flash("Seleccione al menos un docente.", "warning")
    for did in ids:
        docente = db.session.get(Docente, did)
        if not docente:
            continue
        try:
            tesis_service.asignar_miembro(tesis, docente, rol, current_user)
            flash(f"{docente.nombre_completo} asignado(a) como {ROLES_TESIS.get(rol, rol).lower()}.", "success")
        except tesis_service.TesisError as exc:
            flash(str(exc), "danger")
    db.session.commit()
    return redirect(url_for("tesis.detalle", tesis_id=tesis.id))


@tesis_bp.route("/miembro/<int:miembro_id>/retirar", methods=["POST"])
@direccion_required
def retirar(miembro_id):
    miembro = db.get_or_404(TesisMiembro, miembro_id)
    tesis_id = miembro.tesis_id
    tesis_service.retirar_miembro(miembro, current_user)
    db.session.commit()
    flash("Docente retirado de la tesis.", "info")
    return redirect(url_for("tesis.detalle", tesis_id=tesis_id))


@tesis_bp.route("/<int:tesis_id>/version", methods=["POST"])
@gestion_required
def subir_version(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    try:
        ruta, nombre = guardar_archivo(request.files.get("archivo"), f"tesis/{tesis.id}", {"pdf", "docx", "doc"})
        if not ruta:
            raise ValueError("Seleccione el archivo de la tesis (PDF o Word).")
        tesis_service.subir_version(tesis, ruta, nombre, request.form.get("comentario"), current_user)
        db.session.commit()
        flash("Nueva version registrada y notificada a los revisores.", "success")
    except (ValueError, tesis_service.TesisError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("tesis.detalle", tesis_id=tesis.id))


@tesis_bp.route("/<int:tesis_id>/sustentacion", methods=["POST"])
@direccion_required
def sustentacion(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    accion = request.form.get("accion")
    try:
        if accion == "programar":
            fecha = _fecha(request.form.get("fecha_sustentacion"), con_hora=True)
            if not fecha:
                raise tesis_service.TesisError("Indique fecha y hora de la sustentacion.")
            tesis_service.programar_sustentacion(tesis, fecha, request.form.get("lugar", "").strip(), current_user)
            flash("Sustentacion programada.", "success")
        elif accion == "registrar":
            tesis_service.registrar_sustentacion(tesis, a_numero(request.form.get("nota")), current_user)
            flash("Sustentacion registrada.", "success")
        db.session.commit()
    except tesis_service.TesisError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("tesis.detalle", tesis_id=tesis.id))


@tesis_bp.route("/<int:tesis_id>/anular", methods=["POST"])
@direccion_required
def anular(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    motivo = request.form.get("motivo", "").strip()
    if not motivo:
        flash("Indique el motivo de la anulacion.", "warning")
    else:
        tesis.estado = "anulada"
        tesis_service.registrar_evento(tesis, "anulacion", f"Tesis anulada: {motivo}", current_user)
        db.session.commit()
        flash("Tesis anulada.", "info")
    return redirect(url_for("tesis.detalle", tesis_id=tesis.id))


# ----------------------------------------------------------------------
# Estudiantes
# ----------------------------------------------------------------------
@tesis_bp.route("/estudiantes")
@gestion_required
def estudiantes():
    q = request.args.get("q", "").strip()
    query = Estudiante.query.options(joinedload(Estudiante.usuario), selectinload(Estudiante.tesis))
    if q:
        query = query.filter(db.or_(Estudiante.codigo.ilike(f"%{q}%"), Estudiante.apellidos.ilike(f"%{q}%"),
                                    Estudiante.nombres.ilike(f"%{q}%")))
    return render_template("tesis/estudiantes.html", estudiantes=query.order_by(Estudiante.apellidos).all(), q=q)


@tesis_bp.route("/estudiantes/<int:estudiante_id>/cuenta", methods=["POST"])
@direccion_required
def cuenta_estudiante(estudiante_id):
    from services.cuentas_service import restablecer_password

    est = db.get_or_404(Estudiante, estudiante_id)
    if est.usuario:
        password = restablecer_password(est.usuario)
        usuario = est.usuario
    else:
        usuario, password = crear_cuenta_estudiante(est)
    db.session.commit()
    return render_template("usuarios/credenciales.html", titulo="Acceso del estudiante", credenciales=[{
        "nombre": est.nombre_completo, "codigo": est.codigo, "username": usuario.username, "password": password,
    }])


@tesis_bp.route("/<int:tesis_id>/estudiante", methods=["POST"])
@direccion_required
def agregar_estudiante(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    est, err = _estudiante_desde_form("")
    if err or not est:
        flash(err or "Indique el codigo del estudiante.", "danger")
        db.session.rollback()
    elif est in tesis.estudiantes:
        flash("El estudiante ya forma parte de la tesis.", "info")
    elif len(tesis.estudiantes) >= 2:
        flash("Una tesis admite como maximo dos estudiantes.", "warning")
    else:
        tesis.estudiantes.append(est)
        tesis_service.registrar_evento(tesis, "estudiante", f"Se agrego al estudiante {est.nombre_completo}.", current_user)
        db.session.commit()
        flash("Estudiante agregado.", "success")
    return redirect(url_for("tesis.detalle", tesis_id=tesis.id))
