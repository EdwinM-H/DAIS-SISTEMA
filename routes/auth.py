from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user

from models import db, Usuario, Notificacion
from utils import url_segura, password_valida, VALIDACION_PASSWORD

auth_bp = Blueprint("auth", __name__)


def destino_inicio(usuario):
    if usuario.rol == "docente":
        return url_for("docente.inicio")
    if usuario.rol == "estudiante":
        return url_for("estudiante.inicio")
    return url_for("dashboard.index")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(destino_inicio(current_user))

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = Usuario.query.filter(db.func.lower(Usuario.username) == username).first()

        if user and user.activo and user.check_password(password):
            session.clear()
            login_user(user, remember=bool(request.form.get("recordar")))
            user.ultimo_acceso = datetime.now()
            db.session.commit()
            if user.debe_cambiar_password:
                flash("Por seguridad, defina una nueva contrasena antes de continuar.", "info")
                return redirect(url_for("auth.cambiar_password"))
            if user.rol == "docente" and user.docente and not user.docente.perfil_completo:
                flash("Complete su perfil académico. Puede hacerlo después, pero se usará para proponerle tesis afines.", "info")
                return redirect(url_for("docente.perfil_academico"))
            siguiente = request.args.get("next")
            if url_segura(siguiente) and siguiente != "/":
                return redirect(siguiente)
            return redirect(destino_inicio(user))

        if user and not user.activo:
            flash("Su cuenta esta desactivada. Comuniquese con la Direccion del DAIS.", "warning")
        else:
            flash("Usuario o contrasena incorrectos.", "danger")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("Sesion cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/cuenta/contrasena", methods=["GET", "POST"])
@login_required
def cambiar_password():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")
        # Si viene de la ventana flotante, se vuelve a la misma pagina
        volver = request.form.get("volver") if url_segura(request.form.get("volver")) else None
        obligatorio = current_user.debe_cambiar_password
        error = None
        if not current_user.check_password(actual):
            error = "La contraseña actual no es correcta."
        elif nueva != confirmar:
            error = "La confirmación no coincide con la nueva contraseña."
        elif not password_valida(nueva):
            error = VALIDACION_PASSWORD
        elif nueva == actual:
            error = "La nueva contraseña debe ser distinta de la actual."
        if error:
            flash(error, "danger")
            if volver and not obligatorio:
                base = volver.rstrip("?")
                return redirect(base + ("&" if "?" in base else "?") + "cambiar_clave=1")
            return render_template("cuenta/cambiar_password.html")
        current_user.set_password(nueva)
        current_user.debe_cambiar_password = False
        db.session.commit()
        flash("Contraseña actualizada correctamente.", "success")
        if obligatorio and current_user.rol == "docente" and current_user.docente and not current_user.docente.perfil_completo:
            return redirect(url_for("docente.perfil_academico"))
        if volver and not obligatorio:
            return redirect(volver.rstrip("?"))
        return redirect(destino_inicio(current_user))
    return render_template("cuenta/cambiar_password.html")


@auth_bp.route("/notificaciones")
@login_required
def notificaciones():
    items = current_user.notificaciones.limit(100).all()
    return render_template("cuenta/notificaciones.html", notificaciones=items)


@auth_bp.route("/notificaciones/<int:notif_id>/abrir")
@login_required
def abrir_notificacion(notif_id):
    n = Notificacion.query.filter_by(id=notif_id, usuario_id=current_user.id).first_or_404()
    n.leida = True
    db.session.commit()
    return redirect(n.url if url_segura(n.url) else url_for("auth.notificaciones"))


@auth_bp.route("/notificaciones/marcar-leidas", methods=["POST"])
@login_required
def marcar_leidas():
    Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).update({"leida": True})
    db.session.commit()
    volver = request.form.get("volver")
    return redirect(volver.rstrip("?") if url_segura(volver) else url_for("auth.notificaciones"))
