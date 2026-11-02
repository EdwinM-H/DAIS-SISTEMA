import logging
import os
from datetime import datetime

from flask import Flask, render_template, session, request, redirect, url_for
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError

from config import config, CLAVE_DESARROLLO
from models import db, Usuario, Semestre

csrf = CSRFProtect()
migrate = Migrate()
login_manager = LoginManager()

ENDPOINTS_LIBRES = {"auth.login", "auth.logout", "auth.cambiar_password", "static"}


def create_app(config_name=None, **overrides):
    config_name = config_name or os.getenv("FLASK_ENV", "development")
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    app.config.update(overrides)

    if config_name == "production" and app.config["SECRET_KEY"] == CLAVE_DESARROLLO:
        raise RuntimeError("SECRET_KEY debe configurarse en produccion.")

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Debe iniciar sesion para acceder."
    login_manager.login_message_category = "warning"

    for carpeta in ("UPLOAD_FOLDER", "GENERATED_FOLDER", "STORAGE_FOLDER"):
        os.makedirs(app.config[carpeta], exist_ok=True)
    os.makedirs(app.instance_path, exist_ok=True)

    _registrar_hooks(app)
    _registrar_errores(app)

    from routes import register_routes
    register_routes(app)

    from commands import register_commands
    register_commands(app)

    from utils import registrar_filtros
    registrar_filtros(app)

    if config_name == "production":
        os.makedirs(os.path.join(app.root_path, "logs"), exist_ok=True)
        logging.basicConfig(
            filename=os.path.join(app.root_path, "logs", "dais.log"),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    return app


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


def _registrar_hooks(app):
    @app.before_request
    def preparar_sesion():
        if not current_user.is_authenticated:
            return None
        # Obliga a cambiar la contrasena temporal antes de usar el sistema
        if current_user.debe_cambiar_password and request.endpoint not in ENDPOINTS_LIBRES:
            return redirect(url_for("auth.cambiar_password"))
        # Semestre de trabajo por defecto: el activo (o el mas reciente)
        sid = session.get("semestre_id")
        if not sid or not db.session.get(Semestre, sid):
            sem = Semestre.activo_actual() or (Semestre.ordenados() or [None])[0]
            if sem:
                session["semestre_id"] = sem.id
                session["semestre_codigo"] = sem.codigo
            else:
                session.pop("semestre_id", None)
                session.pop("semestre_codigo", None)
        return None

    @app.context_processor
    def inject_globals():
        datos = {
            "session_semestre_id": session.get("semestre_id"),
            "session_semestre_codigo": session.get("semestre_codigo"),
            "anio_actual": datetime.now().year,
            "nav_pendientes_produccion": 0,
            "nav_tesis_pendientes": 0,
            "nav_validaciones_perfil": 0,
            "perfil_faltante": [],
        }
        if current_user.is_authenticated:
            datos.update(_contadores_menu())
        return datos

    def _contadores_menu():
        """Insignias del menu lateral: registros por validar y dictamenes pendientes."""
        from models import Capacitacion, Investigacion, Tesis, TesisMiembro, Dictamen, CambioPerfil
        from models.tesis import ETAPAS_CERRADAS

        if current_user.es_gestion:
            return {"nav_pendientes_produccion":
                    Capacitacion.query.filter_by(estado_validacion="pendiente").count()
                    + Investigacion.query.filter_by(estado_validacion="pendiente").count(),
                    "nav_validaciones_perfil": CambioPerfil.query.filter_by(estado="pendiente").count()}
        if current_user.es_docente:
            abiertas = Tesis.etapa.notin_(ETAPAS_CERRADAS)
            designaciones = (TesisMiembro.query.join(Tesis)
                             .filter(TesisMiembro.docente_id == current_user.docente_id,
                                     TesisMiembro.estado_designacion == "propuesto", abiertas).count())
            dictamenes = (Dictamen.query.join(TesisMiembro).join(Tesis, Dictamen.tesis_id == Tesis.id)
                          .filter(TesisMiembro.docente_id == current_user.docente_id,
                                  TesisMiembro.estado_designacion == "aceptado",
                                  Dictamen.resultado.is_(None), abiertas).count())
            docente = current_user.docente
            return {"nav_tesis_pendientes": designaciones + dictamenes,
                    "perfil_faltante": docente.faltantes_perfil() if docente else []}
        return {}

    @app.after_request
    def cabeceras_seguridad(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp


def _registrar_errores(app):
    def pagina(code, message):
        return render_template("error.html", code=code, message=message), code

    app.register_error_handler(403, lambda e: pagina(403, "No tiene permisos para acceder a esta seccion."))
    app.register_error_handler(404, lambda e: pagina(404, "Pagina no encontrada."))
    app.register_error_handler(413, lambda e: pagina(413, "El archivo es demasiado grande (maximo 15 MB)."))
    app.register_error_handler(CSRFError, lambda e: pagina(400, "La sesion del formulario expiro. Recargue la pagina e intente de nuevo."))

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return pagina(500, "Error interno del servidor.")


if __name__ == "__main__":
    create_app().run(debug=True)
