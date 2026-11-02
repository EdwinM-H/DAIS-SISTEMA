from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload

from models import db, Usuario, Docente, ROLES
from services.cuentas_service import crear_cuentas_docentes, restablecer_password
from utils import direccion_required, generar_password, password_valida, url_segura, VALIDACION_PASSWORD

usuarios_bp = Blueprint("usuarios", __name__, url_prefix="/usuarios")

ROLES_CREABLES = ("admin", "director", "operador")


@usuarios_bp.route("/")
@direccion_required
def index():
    rol = request.args.get("rol", "")
    q = request.args.get("q", "").strip()
    query = Usuario.query.options(joinedload(Usuario.docente), joinedload(Usuario.estudiante))
    if rol in ROLES:
        query = query.filter_by(rol=rol)
    if q:
        query = query.filter(db.or_(Usuario.username.ilike(f"%{q}%"), Usuario.nombre_completo.ilike(f"%{q}%")))
    usuarios = query.order_by(Usuario.rol, Usuario.nombre_completo).all()
    sin_cuenta = Docente.query.filter(Docente.estado == "activo", ~Docente.usuario.has()).count()
    docentes_libres = Docente.query.filter(~Docente.usuario.has()).order_by(Docente.apellidos).all()
    return render_template("usuarios/index.html", usuarios=usuarios, roles=ROLES, rol=rol, q=q, sin_cuenta=sin_cuenta,
                           docentes_libres=docentes_libres)


@usuarios_bp.route("/crear", methods=["GET", "POST"])
@direccion_required
def crear():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        nombre = request.form.get("nombre_completo", "").strip()
        rol = request.form.get("rol", "operador")
        password = request.form.get("password", "").strip()
        if not username or not nombre or rol not in ROLES_CREABLES:
            flash("Complete usuario, nombre y rol.", "danger")
        elif Usuario.query.filter(db.func.lower(Usuario.username) == username).first():
            flash("Ese nombre de usuario ya existe.", "danger")
        elif password and not password_valida(password):
            flash(VALIDACION_PASSWORD, "danger")
        else:
            password = password or generar_password()
            u = Usuario(username=username, nombre_completo=nombre, rol=rol,
                        email=request.form.get("email", "").strip() or None, debe_cambiar_password=True)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            return render_template("usuarios/credenciales.html", titulo="Cuenta creada", credenciales=[{
                "nombre": nombre, "codigo": ROLES[rol], "username": username, "password": password,
            }])
    return render_template("usuarios/crear.html", roles={k: ROLES[k] for k in ROLES_CREABLES})


@usuarios_bp.route("/<int:usuario_id>/estado", methods=["POST"])
@direccion_required
def cambiar_estado(usuario_id):
    u = db.get_or_404(Usuario, usuario_id)
    if u.id == current_user.id:
        flash("No puede desactivar su propia cuenta.", "warning")
    else:
        u.activo = not u.activo
        db.session.commit()
        flash(f"Cuenta {u.username} {'activada' if u.activo else 'desactivada'}.", "success")
    volver = request.form.get("volver")
    return redirect(volver if url_segura(volver) else url_for("usuarios.index"))


@usuarios_bp.route("/<int:usuario_id>/restablecer", methods=["POST"])
@direccion_required
def restablecer(usuario_id):
    u = db.get_or_404(Usuario, usuario_id)
    password = restablecer_password(u)
    db.session.commit()
    return render_template("usuarios/credenciales.html", titulo="Contrasena restablecida", credenciales=[{
        "nombre": u.nombre_completo, "codigo": u.rol_nombre, "username": u.username, "password": password,
    }])


@usuarios_bp.route("/<int:usuario_id>/vincular", methods=["POST"])
@direccion_required
def vincular(usuario_id):
    """Vincula una cuenta de docente con su ficha (repara cuentas que quedaron sin vinculo)."""
    u = db.get_or_404(Usuario, usuario_id)
    docente = db.session.get(Docente, request.form.get("docente_id", type=int) or 0)
    if u.rol != "docente" or not docente:
        flash("Seleccione un docente válido.", "danger")
    elif docente.usuario and docente.usuario.id != u.id:
        flash(f"{docente.nombre_completo} ya tiene la cuenta {docente.usuario.username}.", "warning")
    else:
        u.docente_id = docente.id
        db.session.commit()
        flash(f"Cuenta {u.username} vinculada a {docente.nombre_completo}.", "success")
    return redirect(url_for("usuarios.index"))


@usuarios_bp.route("/generar-docentes", methods=["POST"])
@direccion_required
def generar_docentes():
    credenciales = crear_cuentas_docentes()
    if not credenciales:
        flash("Todos los docentes activos ya tienen cuenta.", "info")
        return redirect(url_for("usuarios.index"))
    return render_template("usuarios/credenciales.html", titulo=f"{len(credenciales)} cuentas de docentes creadas",
                           credenciales=credenciales)
