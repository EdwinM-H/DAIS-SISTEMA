"""Lineas de investigacion de la EPIS y perfil academico del docente."""

from models import db

docente_lineas = db.Table(
    "docente_lineas",
    db.Column("docente_id", db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("linea_id", db.Integer, db.ForeignKey("lineas_investigacion.id", ondelete="CASCADE"), primary_key=True),
)
docente_temas = db.Table(
    "docente_temas",
    db.Column("docente_id", db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tema_id", db.Integer, db.ForeignKey("temas_investigacion.id", ondelete="CASCADE"), primary_key=True),
)
tesis_temas = db.Table(
    "tesis_temas",
    db.Column("tesis_id", db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tema_id", db.Integer, db.ForeignKey("temas_investigacion.id", ondelete="CASCADE"), primary_key=True),
)


class AreaInvestigacion(db.Model):
    __tablename__ = "areas_investigacion"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), unique=True, nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)

    lineas = db.relationship("LineaInvestigacion", back_populates="area", order_by="LineaInvestigacion.orden",
                             cascade="all, delete-orphan")


class LineaInvestigacion(db.Model):
    __tablename__ = "lineas_investigacion"

    id = db.Column(db.Integer, primary_key=True)
    area_id = db.Column(db.Integer, db.ForeignKey("areas_investigacion.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = db.Column(db.String(150), nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)

    area = db.relationship("AreaInvestigacion", back_populates="lineas")
    temas = db.relationship("TemaInvestigacion", back_populates="linea", order_by="TemaInvestigacion.orden",
                            cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("area_id", "nombre", name="uq_linea_area_nombre"),)


class TemaInvestigacion(db.Model):
    __tablename__ = "temas_investigacion"

    id = db.Column(db.Integer, primary_key=True)
    linea_id = db.Column(db.Integer, db.ForeignKey("lineas_investigacion.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = db.Column(db.String(200), nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)

    linea = db.relationship("LineaInvestigacion", back_populates="temas")

    __table_args__ = (db.UniqueConstraint("linea_id", "nombre", name="uq_tema_linea_nombre"),)

    @property
    def etiqueta(self):
        return f"{self.linea.nombre} › {self.nombre}"


# Datos del perfil que el docente puede declarar pero que requieren validacion del DAIS
CAMPOS_VALIDABLES = {
    "grado_academico": "Grado académico",
    "colegiatura": "Colegiatura (número y año)",
    "licencia": "Licencia / no disponibilidad",
}
ESTADOS_CAMBIO = {"pendiente": "Pendiente", "aprobado": "Aprobado", "rechazado": "Rechazado", "directo": "Registrado"}


class CambioPerfil(db.Model):
    """Historial del perfil academico. Los datos validables quedan 'pendiente' hasta que el DAIS los aprueba."""

    __tablename__ = "cambios_perfil"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    campo = db.Column(db.String(40), nullable=False)
    valor_anterior = db.Column(db.String(300), nullable=True)
    valor_nuevo = db.Column(db.String(300), nullable=True)
    estado = db.Column(db.String(10), nullable=False, default="pendiente", index=True)
    motivo = db.Column(db.Text, nullable=True)            # sustento del docente o motivo de rechazo
    archivo_ruta = db.Column(db.String(300), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)
    solicitado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    revisado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    revisado_en = db.Column(db.DateTime, nullable=True)

    docente = db.relationship("Docente", back_populates="cambios_perfil")
    solicitado_por = db.relationship("Usuario", foreign_keys=[solicitado_por_id])
    revisado_por = db.relationship("Usuario", foreign_keys=[revisado_por_id])

    __table_args__ = (
        db.CheckConstraint("estado IN ('pendiente','aprobado','rechazado','directo')", name="estado_valido"),
    )

    @property
    def campo_nombre(self):
        return CAMPOS_VALIDABLES.get(self.campo, self.campo.replace("_", " ").capitalize())

    @property
    def estado_nombre(self):
        return ESTADOS_CAMBIO.get(self.estado, self.estado)


class Parametro(db.Model):
    """Parametros configurables por la Direccion (plazos, cupos...)."""

    __tablename__ = "parametros"

    clave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.String(200), nullable=False)


class Feriado(db.Model):
    __tablename__ = "feriados"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False)
    descripcion = db.Column(db.String(150), nullable=True)
