"""Utilidades transversales: permisos, archivos, notificaciones y filtros de plantilla."""

import os
import re
import secrets
import string
import unicodedata
import uuid
from functools import wraps
from urllib.parse import urlparse

from flask import abort, current_app, session
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from models import db, Usuario, Semestre, Notificacion


# ----------------------------------------------------------------------
# Permisos
# ----------------------------------------------------------------------
def roles_required(*roles):
    """Restringe la vista a los roles indicados (ademas de exigir login)."""

    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(*args, **kwargs):
            if current_user.rol not in roles:
                abort(403)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


gestion_required = roles_required("admin", "director", "operador")
direccion_required = roles_required("admin", "director")
docente_required = roles_required("docente")
estudiante_required = roles_required("estudiante")


def url_segura(destino):
    """Evita redirecciones abiertas: solo rutas relativas del mismo sitio."""
    if not destino:
        return False
    partes = urlparse(destino)
    return not partes.scheme and not partes.netloc and destino.startswith("/") and not destino.startswith("//")


def semestre_sesion():
    sid = session.get("semestre_id")
    return db.session.get(Semestre, sid) if sid else None


# ----------------------------------------------------------------------
# Archivos
# ----------------------------------------------------------------------
def extension(nombre):
    return nombre.rsplit(".", 1)[1].lower() if nombre and "." in nombre else ""


def guardar_archivo(archivo, subcarpeta, extensiones=None):
    """Guarda un archivo subido con nombre unico. Devuelve (ruta_relativa, nombre_original).

    Lanza ValueError si la extension no esta permitida.
    """
    if not archivo or not archivo.filename:
        return None, None
    extensiones = extensiones or current_app.config["EXTENSIONES_DOCUMENTOS"]
    ext = extension(archivo.filename)
    if ext not in extensiones:
        raise ValueError(
            "Tipo de archivo no permitido. Formatos aceptados: " + ", ".join(sorted(extensiones))
        )
    nombre_original = archivo.filename[:255]
    destino_rel = os.path.join(subcarpeta, f"{uuid.uuid4().hex}.{ext}")
    destino = os.path.join(current_app.config["STORAGE_FOLDER"], destino_rel)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    archivo.save(destino)
    return destino_rel.replace("\\", "/"), nombre_original


def ruta_absoluta(ruta_rel):
    base = os.path.realpath(current_app.config["STORAGE_FOLDER"])
    ruta = os.path.realpath(os.path.join(base, ruta_rel or ""))
    if not ruta.startswith(base + os.sep) or not os.path.isfile(ruta):
        return None
    return ruta


def eliminar_archivo(ruta_rel):
    ruta = ruta_absoluta(ruta_rel) if ruta_rel else None
    if ruta:
        try:
            os.remove(ruta)
        except OSError:
            pass


def nombre_temporal_seguro(nombre):
    base = secure_filename(nombre) or "archivo"
    return f"{uuid.uuid4().hex[:8]}_{base}"


# ----------------------------------------------------------------------
# Cuentas
# ----------------------------------------------------------------------
def generar_password(longitud=10):
    alfabeto = string.ascii_letters + string.digits
    while True:
        pwd = "".join(secrets.choice(alfabeto) for _ in range(longitud))
        if any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd):
            return pwd


def _ascii(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c))


def generar_username(nombres, apellidos):
    """'Maria Isabel', 'Acurio Gutierrez' -> 'macurio' (con sufijo si ya existe)."""
    inicial = re.sub(r"[^a-z]", "", _ascii(nombres).lower())[:1] or "u"
    apellido = re.sub(r"[^a-z]", "", _ascii((apellidos or "").split()[0] if apellidos else "").lower()) or "usuario"
    base = (inicial + apellido)[:30]
    candidato, n = base, 1
    while Usuario.query.filter_by(username=candidato).first():
        n += 1
        candidato = f"{base}{n}"
    return candidato


VALIDACION_PASSWORD = "La contrasena debe tener al menos 8 caracteres, con letras y numeros."


def password_valida(pwd):
    return bool(pwd) and len(pwd) >= 8 and any(c.isdigit() for c in pwd) and any(c.isalpha() for c in pwd)


# ----------------------------------------------------------------------
# Notificaciones
# ----------------------------------------------------------------------
def notificar(usuario, titulo, mensaje=None, url=None):
    if usuario is None:
        return
    db.session.add(Notificacion(usuario_id=usuario.id, titulo=titulo[:200], mensaje=mensaje, url=url))


def notificar_gestion(titulo, mensaje=None, url=None, roles=("admin", "director")):
    for u in Usuario.query.filter(Usuario.rol.in_(roles), Usuario.activo.is_(True)).all():
        notificar(u, titulo, mensaje, url)


# ----------------------------------------------------------------------
# Filtros Jinja
# ----------------------------------------------------------------------
CLASES_CLASIFICACION = {
    "Excelente": "badge-success",
    "Muy Bueno": "badge-info",
    "Bueno": "badge-warning",
    "Regular": "badge-secondary",
    "Insuficiente": "badge-danger",
}

CLASES_ESTADO = {
    "validado": "badge-success",
    "pendiente": "badge-warning",
    "observado": "badge-danger",
    "visto_bueno": "badge-success",
    "registrada": "badge-secondary",
    "en_dictamen": "badge-info",
    "observada": "badge-danger",
    "dictamen_favorable": "badge-success",
    "sustentacion_programada": "badge-purple",
    "sustentada": "badge-success",
    "anulada": "badge-secondary",
    "Completa": "badge-success",
    "Parcial": "badge-warning",
    "Pendiente": "badge-secondary",
}


def registrar_filtros(app):
    @app.template_filter("nota")
    def fmt_nota(valor, decimales=2):
        if valor is None or valor == "":
            return "-"
        try:
            return f"{float(valor):.{decimales}f}"
        except (TypeError, ValueError):
            return str(valor)

    @app.template_filter("fecha")
    def fmt_fecha(valor, con_hora=False):
        if not valor:
            return "-"
        return valor.strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")

    @app.template_filter("clase_clasif")
    def clase_clasif(valor):
        return CLASES_CLASIFICACION.get(valor or "", "badge-secondary")

    @app.template_filter("clase_estado")
    def clase_estado(valor):
        return CLASES_ESTADO.get(valor or "", "badge-secondary")

    @app.template_filter("pct")
    def pct(valor, maximo):
        try:
            return max(0, min(100, round(float(valor) * 100.0 / float(maximo))))
        except (TypeError, ValueError, ZeroDivisionError):
            return 0
