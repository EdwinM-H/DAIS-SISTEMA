"""Gestion de tesis por el DAIS (Departamento Academico): designaciones, resoluciones y plazos."""

from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from models import (
    db, Tesis, TesisMiembro, Estudiante, Docente, Feriado, Semestre, TemaInvestigacion, LineaInvestigacion,
)
from models.docente import titulo
from models.tesis import (
    ETAPAS_TESIS, ROLES_TESIS, MODALIDADES_TESIS, REGIMENES, TIPOS_RESOLUCION, RESULTADOS_DICTAMEN,
)
from services import tesis_service, asignacion_service, parametros, calendario, perfil_service
from services.cuentas_service import crear_cuenta_estudiante
from services.excel_service import a_numero
from services.oficio_service import generar_oficio
from utils import gestion_required, direccion_required, guardar_archivo, semestre_sesion

tesis_bp = Blueprint("tesis", __name__, url_prefix="/tesis")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _fecha(valor, con_hora=False):
    if not valor:
        return None
    try:
        if con_hora:
            return datetime.strptime(valor, "%Y-%m-%dT%H:%M")
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


def _redir(tesis_id):
    return redirect(url_for("tesis.detalle", tesis_id=tesis_id))


def _ejecutar(tesis_id, accion, exito):
    """Ejecuta una accion del servicio con commit y mensajes uniformes."""
    try:
        accion()
        db.session.commit()
        if exito:
            flash(exito, "success")
    except (tesis_service.TesisError, ValueError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _redir(tesis_id)


# ----------------------------------------------------------------------
# Listado y registro
# ----------------------------------------------------------------------
@tesis_bp.route("/")
@gestion_required
def index():
    alertas = tesis_service.revisar_plazos(current_user)
    etapa = request.args.get("etapa", "")
    q = request.args.get("q", "").strip()
    query = Tesis.query.options(selectinload(Tesis.estudiantes),
                                selectinload(Tesis.miembros).joinedload(TesisMiembro.docente))
    if etapa in ETAPAS_TESIS:
        query = query.filter(Tesis.etapa == etapa)
    if q:
        query = query.filter(db.or_(Tesis.titulo.ilike(f"%{q}%"), Tesis.codigo.ilike(f"%{q}%"),
                                    Tesis.estudiantes.any(Estudiante.apellidos.ilike(f"%{q}%"))))
    tesis = query.order_by(Tesis.creado_en.desc()).all()
    conteo = dict(db.session.query(Tesis.etapa, db.func.count(Tesis.id)).group_by(Tesis.etapa).all())
    pendientes = {t.id: tesis_service.necesidades(t) for t in tesis}
    return render_template("tesis/index.html", tesis=tesis, etapa=etapa, q=q, etapas=ETAPAS_TESIS, conteo=conteo,
                           alertas=alertas, pendientes=pendientes, roles=ROLES_TESIS)


def _docentes_activos():
    return Docente.query.filter_by(estado="activo").order_by(Docente.apellidos, Docente.nombres).all()


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


def _aplicar_tematica(tesis):
    temas = TemaInvestigacion.query.filter(
        TemaInvestigacion.id.in_([int(x) for x in request.form.getlist("temas") if x.isdigit()] or [0])).all()
    linea = db.session.get(LineaInvestigacion, request.form.get("linea_id", type=int) or 0)
    if not linea and temas:
        linea = temas[0].linea
    tesis.linea_id = linea.id if linea else None
    tesis.area_id = linea.area_id if linea else None
    tesis.temas = [t for t in temas if not linea or t.linea_id == linea.id] or temas
    tesis.palabras_clave = request.form.get("palabras_clave", "").strip() or None


def _form(tesis):
    return render_template("tesis/formulario.html", tesis=tesis, docentes=_docentes_activos(),
                           areas=perfil_service.catalogo(), modalidades=MODALIDADES_TESIS, regimenes=REGIMENES)


@tesis_bp.route("/nueva", methods=["GET", "POST"])
@gestion_required
def crear():
    if request.method == "GET":
        return _form(None)
    titulo_tesis = request.form.get("titulo", "").strip()
    estudiantes, errores = [], []
    for prefijo in ("e1_", "e2_"):
        est, err = _estudiante_desde_form(prefijo)
        if err:
            errores.append(err)
        if est:
            estudiantes.append(est)
    if not titulo_tesis:
        errores.append("El título es obligatorio.")
    if not estudiantes:
        errores.append("Registre al menos un tesista.")
    modalidad = request.form.get("modalidad", "tesis")
    regimen = request.form.get("regimen", "vigente")
    if modalidad not in MODALIDADES_TESIS or regimen not in REGIMENES:
        errores.append("Modalidad o régimen no válido.")
    if errores:
        db.session.rollback()
        for e in errores:
            flash(e, "danger")
        return _form(None)

    sem = semestre_sesion()
    tesis = Tesis(codigo=Tesis.siguiente_codigo(date.today().year), titulo=titulo_tesis,
                  resumen=request.form.get("resumen", "").strip() or None, modalidad=modalidad, regimen=regimen,
                  etapa="asesor", fecha_registro=date.today(), semestre_id=sem.id if sem else None,
                  creado_por_id=current_user.id)
    _aplicar_tematica(tesis)
    tesis.estudiantes = estudiantes
    db.session.add(tesis)
    db.session.flush()
    tesis_service.registrar_evento(tesis, "registro", f"{tesis.modalidad_nombre} registrada.", current_user)

    asesor = request.form.get("asesor_id", "")
    try:
        if asesor.isdigit():
            tesis_service.designar(tesis, db.session.get(Docente, int(asesor)), "asesor", current_user)
        elif asesor == "auto":
            tesis_service.proponer_automaticamente(tesis, current_user, rol="asesor")
    except tesis_service.TesisError as exc:
        flash(str(exc), "warning")
    db.session.commit()
    flash(f"Tesis {tesis.codigo} registrada.", "success")
    return _redir(tesis.id)


@tesis_bp.route("/<int:tesis_id>")
@gestion_required
def detalle(tesis_id):
    tesis_service.revisar_plazos(current_user)
    tesis = db.get_or_404(Tesis, tesis_id)
    return render_template(
        "tesis/detalle.html", tesis=tesis, necesidades=tesis_service.necesidades(tesis),
        estado_revision=tesis_service.estado_revision(tesis), textos_revision=tesis_service.ESTADOS_REVISION_TEXTO,
        roles=ROLES_TESIS, tipos_resolucion=TIPOS_RESOLUCION, resultados=RESULTADOS_DICTAMEN,
        semaforo=calendario.semaforo, hoy=date.today(), hay_observaciones=tesis_service.hay_observaciones_pendientes(tesis),
    )


@tesis_bp.route("/<int:tesis_id>/editar", methods=["GET", "POST"])
@gestion_required
def editar(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    if request.method == "POST":
        tesis.titulo = request.form.get("titulo", "").strip() or tesis.titulo
        tesis.resumen = request.form.get("resumen", "").strip() or None
        _aplicar_tematica(tesis)
        tesis_service.registrar_evento(tesis, "edicion", "Datos generales actualizados.", current_user)
        db.session.commit()
        flash("Tesis actualizada.", "success")
        return _redir(tesis.id)
    return _form(tesis)


# ----------------------------------------------------------------------
# Designaciones
# ----------------------------------------------------------------------
@tesis_bp.route("/<int:tesis_id>/proponer", methods=["POST"])
@gestion_required
def proponer(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    rol = request.form.get("rol") or None

    def accion():
        creados = tesis_service.proponer_automaticamente(tesis, current_user, rol=rol)
        flash("Propuesta automática: " + "; ".join(f"{m.docente.nombre_completo} ({m.rol_nombre.lower()})" for m in creados), "success")

    return _ejecutar(tesis.id, accion, None)


@tesis_bp.route("/<int:tesis_id>/candidatos/<rol>")
@gestion_required
def candidatos(tesis_id, rol):
    tesis = db.get_or_404(Tesis, tesis_id)
    if rol not in ROLES_TESIS:
        return _redir(tesis.id)
    elegibles, descartados = asignacion_service.candidatos(tesis, rol)
    return render_template("tesis/candidatos.html", tesis=tesis, rol=rol, rol_nombre=ROLES_TESIS[rol],
                           elegibles=elegibles, descartados=descartados, puntos=asignacion_service.PUNTOS)


@tesis_bp.route("/<int:tesis_id>/designar", methods=["POST"])
@gestion_required
def designar(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    docente = db.get_or_404(Docente, request.form.get("docente_id", type=int) or 0)
    rol = request.form.get("rol", "")
    candidato = next((c for c in asignacion_service.candidatos(tesis, rol)[0] if c["docente"].id == docente.id), None)
    return _ejecutar(tesis.id, lambda: tesis_service.designar(tesis, docente, rol, current_user, candidato),
                     f"{docente.nombre_completo} designado(a). Se le notificó para aceptar.")


@tesis_bp.route("/miembro/<int:miembro_id>/reemplazar", methods=["POST"])
@direccion_required
def reemplazar(miembro_id):
    miembro = db.get_or_404(TesisMiembro, miembro_id)
    return _ejecutar(miembro.tesis_id, lambda: tesis_service.reemplazar(miembro, request.form.get("motivo"), current_user),
                     "Docente reemplazado. Se propuso automáticamente a otro docente.")


@tesis_bp.route("/miembro/<int:miembro_id>/retirar", methods=["POST"])
@direccion_required
def retirar(miembro_id):
    miembro = db.get_or_404(TesisMiembro, miembro_id)
    return _ejecutar(miembro.tesis_id, lambda: tesis_service.retirar(miembro, current_user), "Designación retirada.")


@tesis_bp.route("/<int:tesis_id>/oficio/<rol>")
@gestion_required
def oficio(tesis_id, rol):
    tesis = db.get_or_404(Tesis, tesis_id)
    buf, nombre = generar_oficio(tesis, rol)
    return send_file(buf, as_attachment=True, download_name=nombre, mimetype=DOCX_MIME)


# ----------------------------------------------------------------------
# Documentos, resoluciones y decisiones
# ----------------------------------------------------------------------
@tesis_bp.route("/<int:tesis_id>/version", methods=["POST"])
@gestion_required
def subir_version(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)

    def accion():
        ruta, nombre = guardar_archivo(request.files.get("archivo"), f"tesis/{tesis.id}", {"pdf", "docx", "doc"})
        if not ruta:
            raise ValueError("Seleccione el documento (PDF o Word).")
        sub = guardar_archivo(request.files.get("subsanacion"), f"tesis/{tesis.id}", {"pdf", "docx", "doc"})
        tesis_service.subir_version(tesis, ruta, nombre, request.form.get("comentario"), current_user, sub)

    return _ejecutar(tesis.id, accion, "Documento registrado y notificado a los dictaminantes.")


@tesis_bp.route("/<int:tesis_id>/resolucion", methods=["POST"])
@gestion_required
def resolucion(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    return _ejecutar(tesis.id, lambda: tesis_service.registrar_resolucion(
        tesis, request.form.get("tipo"), request.form.get("numero"), _fecha(request.form.get("fecha")), current_user),
        "Resolución registrada.")


@tesis_bp.route("/<int:tesis_id>/decision", methods=["POST"])
@direccion_required
def decision(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    return _ejecutar(tesis.id, lambda: tesis_service.decision_decano(
        tesis, request.form.get("decision"), request.form.get("sustento"), current_user), "Decisión registrada.")


@tesis_bp.route("/<int:tesis_id>/sustentacion", methods=["POST"])
@gestion_required
def sustentacion(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    accion = request.form.get("accion")
    if accion == "programar":
        fecha = _fecha(request.form.get("fecha_sustentacion"), con_hora=True)

        def programar():
            if not fecha:
                raise ValueError("Indique fecha y hora de la sustentación.")
            tesis_service.programar_sustentacion(tesis, fecha, request.form.get("lugar"),
                                                 request.form.get("modalidad_sustentacion"), current_user)
        return _ejecutar(tesis.id, programar, "Sustentación programada y notificada.")
    if accion == "notas":
        notas = {m.id: a_numero(request.form.get(f"nota_{m.id}")) for m in tesis.jurado}
        return _ejecutar(tesis.id, lambda: tesis_service.registrar_notas(
            tesis, notas, request.form.get("con_observaciones") == "1", current_user), "Resultado de la sustentación registrado.")
    if accion == "conformidad":
        return _ejecutar(tesis.id, lambda: tesis_service.conformidad_observaciones(tesis, current_user),
                         "Conformidad registrada. Proceso concluido.")
    return _redir(tesis.id)


@tesis_bp.route("/<int:tesis_id>/anular", methods=["POST"])
@direccion_required
def anular(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    return _ejecutar(tesis.id, lambda: tesis_service.anular(tesis, request.form.get("motivo"), current_user), "Tesis anulada.")


# ----------------------------------------------------------------------
# Asignacion masiva
# ----------------------------------------------------------------------
@tesis_bp.route("/asignacion", methods=["GET", "POST"])
@gestion_required
def asignacion():
    tesis_lista = [t for t in Tesis.query.order_by(Tesis.creado_en).all() if tesis_service.necesidades(t)]
    if request.method == "POST":
        elegidas = {int(x) for x in request.form.getlist("tesis_id") if x.isdigit()}
        total, errores = 0, []
        for t in tesis_lista:
            if t.id not in elegidas:
                continue
            try:
                total += len(tesis_service.proponer_automaticamente(t, current_user))
            except tesis_service.TesisError as exc:
                errores.append(f"{t.codigo}: {exc}")
        db.session.commit()
        flash(f"Se realizaron {total} designaciones automáticas.", "success" if total else "info")
        for e in errores:
            flash(e, "warning")
        return redirect(url_for("tesis.asignacion"))
    # Simulacion: las propuestas se calculan una tras otra para repartir la carga
    propuestas = []
    for t in tesis_lista:
        filas = []
        for rol, n in tesis_service.necesidades(t):
            filas.append((rol, asignacion_service.proponer(t, rol, n)))
        propuestas.append({"tesis": t, "filas": filas})
    return render_template("tesis/asignacion.html", propuestas=propuestas, roles=ROLES_TESIS)


# ----------------------------------------------------------------------
# Configuracion
# ----------------------------------------------------------------------
@tesis_bp.route("/configuracion", methods=["GET", "POST"])
@direccion_required
def configuracion():
    if request.method == "POST":
        seccion = request.form.get("seccion")
        try:
            if seccion == "parametros":
                for p in parametros.todos():
                    valor = request.form.get(p["clave"], "").strip()
                    if valor != "":
                        parametros.guardar(p["clave"], valor)
            elif seccion == "feriado":
                f = _fecha(request.form.get("fecha"))
                if not f:
                    raise ValueError("Fecha no válida.")
                if not Feriado.query.filter_by(fecha=f).first():
                    db.session.add(Feriado(fecha=f, descripcion=request.form.get("descripcion", "").strip() or None))
            elif seccion == "quitar_feriado":
                f = db.session.get(Feriado, request.form.get("feriado_id", type=int) or 0)
                if f:
                    db.session.delete(f)
            elif seccion == "semestre":
                s = db.get_or_404(Semestre, request.form.get("semestre_id", type=int) or 0)
                s.fecha_inicio = _fecha(request.form.get("fecha_inicio"))
                s.fecha_fin = _fecha(request.form.get("fecha_fin"))
                if s.fecha_inicio and s.fecha_fin and s.fecha_fin < s.fecha_inicio:
                    raise ValueError("La fecha de fin debe ser posterior a la de inicio.")
            db.session.commit()
            flash("Configuración guardada.", "success")
        except (ValueError, KeyError) as exc:
            db.session.rollback()
            flash(f"No se pudo guardar: {exc}", "danger")
        return redirect(url_for("tesis.configuracion"))
    return render_template("tesis/configuracion.html", parametros=parametros.todos(),
                           feriados=Feriado.query.order_by(Feriado.fecha).all(), semestres=Semestre.ordenados())


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
@gestion_required
def agregar_estudiante(tesis_id):
    tesis = db.get_or_404(Tesis, tesis_id)
    est, err = _estudiante_desde_form("")
    if err or not est:
        flash(err or "Indique el código del estudiante.", "danger")
        db.session.rollback()
    elif est in tesis.estudiantes:
        flash("El estudiante ya forma parte de la tesis.", "info")
    elif len(tesis.estudiantes) >= 2:
        flash("Una tesis admite como máximo dos tesistas de la misma escuela (Art. 52).", "warning")
    else:
        tesis.estudiantes.append(est)
        tesis_service.registrar_evento(tesis, "estudiante", f"Se agregó al tesista {est.nombre_completo}.", current_user)
        db.session.commit()
        flash("Tesista agregado.", "success")
    return _redir(tesis.id)
