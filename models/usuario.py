from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, TimestampMixin

ROLES = {
    "admin": "Administrador",
    "director": "Director(a) DAIS",
    "operador": "Operador",
    "docente": "Docente",
    "estudiante": "Estudiante",
}
ROLES_GESTION = ("admin", "director", "operador")
ROLES_DIRECCION = ("admin", "director")


class Usuario(db.Model, UserMixin, TimestampMixin):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    nombre_completo = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    rol = db.Column(db.String(20), nullable=False, default="operador")
    docente_id = db.Column(
        db.Integer, db.ForeignKey("docentes.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    estudiante_id = db.Column(
        db.Integer, db.ForeignKey("estudiantes.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    activo = db.Column(db.Boolean, nullable=False, default=True)
    debe_cambiar_password = db.Column(db.Boolean, nullable=False, default=False)
    ultimo_acceso = db.Column(db.DateTime, nullable=True)

    docente = db.relationship("Docente", back_populates="usuario")
    estudiante = db.relationship("Estudiante", back_populates="usuario")
    notificaciones = db.relationship(
        "Notificacion", back_populates="usuario", cascade="all, delete-orphan",
        order_by="Notificacion.creado_en.desc()", lazy="dynamic",
    )

    __table_args__ = (
        db.CheckConstraint(
            "rol IN ('admin','director','operador','docente','estudiante')", name="rol_valido"
        ),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return bool(self.activo)

    @property
    def es_gestion(self):
        return self.rol in ROLES_GESTION

    @property
    def es_direccion(self):
        return self.rol in ROLES_DIRECCION

    @property
    def es_docente(self):
        return self.rol == "docente" and self.docente_id is not None

    @property
    def es_estudiante(self):
        return self.rol == "estudiante" and self.estudiante_id is not None

    @property
    def rol_nombre(self):
        return ROLES.get(self.rol, self.rol)

    @property
    def iniciales(self):
        partes = (self.nombre_completo or self.username).split()
        return "".join(p[0] for p in partes[:2]).upper()

    def notificaciones_pendientes(self):
        return self.notificaciones.filter_by(leida=False).count()

    def __repr__(self):
        return f"<Usuario {self.username} ({self.rol})>"


class Notificacion(db.Model):
    __tablename__ = "notificaciones"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(
        db.Integer, db.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    titulo = db.Column(db.String(200), nullable=False)
    mensaje = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(300), nullable=True)
    leida = db.Column(db.Boolean, nullable=False, default=False)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    usuario = db.relationship("Usuario", back_populates="notificaciones")
