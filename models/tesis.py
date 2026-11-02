"""Gestion de tesis: estudiantes, tesis, asesores/dictaminantes/jurados y seguimiento."""

from models import db, TimestampMixin
from models.docente import normalizar_nombre

ESTADOS_TESIS = {
    "registrada": "Registrada",
    "en_dictamen": "En revision de dictaminantes",
    "observada": "Con observaciones",
    "dictamen_favorable": "Dictamen favorable",
    "sustentacion_programada": "Sustentacion programada",
    "sustentada": "Sustentada",
    "anulada": "Anulada",
}

# Etapas visibles en la linea de tiempo del estudiante
ETAPAS_TESIS = [
    ("registrada", "Proyecto registrado"),
    ("asesor", "Asesor asignado"),
    ("dictaminantes", "Dictaminantes asignados"),
    ("dictamen_favorable", "Vistos buenos completos"),
    ("sustentacion_programada", "Sustentacion programada"),
    ("sustentada", "Tesis sustentada"),
]

ROLES_TESIS = {
    "asesor": "Asesor",
    "coasesor": "Coasesor",
    "dictaminante": "Dictaminante",
    "jurado": "Jurado",
}

ESTADOS_REVISION = {
    "pendiente": "Pendiente",
    "observado": "Observado",
    "visto_bueno": "Visto bueno",
}

tesis_estudiantes = db.Table(
    "tesis_estudiantes",
    db.Column("tesis_id", db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), primary_key=True),
    db.Column("estudiante_id", db.Integer, db.ForeignKey("estudiantes.id", ondelete="CASCADE"), primary_key=True),
)


class Estudiante(db.Model, TimestampMixin):
    __tablename__ = "estudiantes"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    dni = db.Column(db.String(15), unique=True, nullable=True)
    nombres = db.Column(db.String(150), nullable=False)
    apellidos = db.Column(db.String(150), nullable=False)
    nombre_normalizado = db.Column(db.String(300), nullable=False, index=True)
    correo = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(30), nullable=True)
    escuela = db.Column(db.String(150), nullable=True)
    estado = db.Column(db.String(12), nullable=False, default="activo")

    usuario = db.relationship("Usuario", back_populates="estudiante", uselist=False)
    tesis = db.relationship("Tesis", secondary=tesis_estudiantes, back_populates="estudiantes")

    __table_args__ = (
        db.CheckConstraint("estado IN ('activo','egresado','inactivo')", name="estado_valido"),
    )

    @property
    def nombre_completo(self):
        return f"{self.apellidos}, {self.nombres}"


@db.event.listens_for(Estudiante, "before_insert")
@db.event.listens_for(Estudiante, "before_update")
def _clave_estudiante(mapper, connection, target):
    target.nombre_normalizado = normalizar_nombre(f"{target.apellidos} {target.nombres}")


class Tesis(db.Model, TimestampMixin):
    __tablename__ = "tesis"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    titulo = db.Column(db.String(600), nullable=False)
    resumen = db.Column(db.Text, nullable=True)
    linea_investigacion = db.Column(db.String(200), nullable=True)
    modalidad = db.Column(db.String(60), nullable=True)  # Tesis, Trabajo de suficiencia, Articulo...
    estado = db.Column(db.String(30), nullable=False, default="registrada", index=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="SET NULL"), nullable=True)
    resolucion = db.Column(db.String(120), nullable=True)
    fecha_registro = db.Column(db.Date, nullable=True)
    fecha_limite_revision = db.Column(db.Date, nullable=True)
    fecha_sustentacion = db.Column(db.DateTime, nullable=True)
    lugar_sustentacion = db.Column(db.String(200), nullable=True)
    nota_sustentacion = db.Column(db.Float, nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    semestre = db.relationship("Semestre")
    creado_por = db.relationship("Usuario")
    estudiantes = db.relationship("Estudiante", secondary=tesis_estudiantes, back_populates="tesis")
    miembros = db.relationship(
        "TesisMiembro", back_populates="tesis", cascade="all, delete-orphan",
        order_by="TesisMiembro.rol",
    )
    versiones = db.relationship(
        "TesisVersion", back_populates="tesis", cascade="all, delete-orphan",
        order_by="TesisVersion.numero.desc()",
    )
    eventos = db.relationship(
        "TesisEvento", back_populates="tesis", cascade="all, delete-orphan",
        order_by="TesisEvento.id.desc()",
    )

    __table_args__ = (
        db.CheckConstraint(
            "estado IN ('registrada','en_dictamen','observada','dictamen_favorable',"
            "'sustentacion_programada','sustentada','anulada')",
            name="estado_valido",
        ),
        db.CheckConstraint(
            "nota_sustentacion IS NULL OR (nota_sustentacion >= 0 AND nota_sustentacion <= 20)",
            name="nota_rango",
        ),
    )

    @property
    def estado_nombre(self):
        return ESTADOS_TESIS.get(self.estado, self.estado)

    def miembros_por_rol(self, rol):
        return [m for m in self.miembros if m.rol == rol]

    @property
    def asesor(self):
        asesores = self.miembros_por_rol("asesor")
        return asesores[0] if asesores else None

    @property
    def dictaminantes(self):
        return self.miembros_por_rol("dictaminante")

    @property
    def progreso_dictamen(self):
        """(vistos_buenos, total_dictaminantes)."""
        dic = self.dictaminantes
        return sum(1 for m in dic if m.estado_revision == "visto_bueno"), len(dic)

    @property
    def version_actual(self):
        return self.versiones[0] if self.versiones else None

    @property
    def estudiantes_texto(self):
        return "; ".join(e.nombre_completo for e in self.estudiantes) or "-"

    def recalcular_estado(self):
        """Deriva el estado a partir de las revisiones de los dictaminantes.

        No retrocede estados finales (programada, sustentada, anulada).
        """
        if self.estado in ("sustentacion_programada", "sustentada", "anulada"):
            return self.estado
        dic = self.dictaminantes
        if not dic:
            self.estado = "registrada"
        elif all(m.estado_revision == "visto_bueno" for m in dic):
            self.estado = "dictamen_favorable"
        elif any(m.estado_revision == "observado" for m in dic):
            self.estado = "observada"
        else:
            self.estado = "en_dictamen"
        return self.estado

    def etapas(self):
        """Linea de tiempo: lista de (clave, etiqueta, completada)."""
        vb, total = self.progreso_dictamen
        orden_final = ["sustentacion_programada", "sustentada"]
        hecho = {
            "registrada": True,
            "asesor": self.asesor is not None,
            "dictaminantes": total > 0,
            "dictamen_favorable": total > 0 and vb == total,
            "sustentacion_programada": self.estado in orden_final,
            "sustentada": self.estado == "sustentada",
        }
        return [(clave, etiqueta, hecho[clave]) for clave, etiqueta in ETAPAS_TESIS]

    @staticmethod
    def siguiente_codigo(anio):
        prefijo = f"TES-{anio}-"
        mayor = 0
        for (cod,) in db.session.query(Tesis.codigo).filter(Tesis.codigo.like(prefijo + "%")).all():
            try:
                mayor = max(mayor, int(cod.rsplit("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        return f"{prefijo}{mayor + 1:04d}"


class TesisMiembro(db.Model, TimestampMixin):
    """Docente asignado a una tesis con un rol (asesor, dictaminante, jurado)."""

    __tablename__ = "tesis_miembros"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    rol = db.Column(db.String(20), nullable=False)
    estado_revision = db.Column(db.String(12), nullable=False, default="pendiente")
    observaciones = db.Column(db.Text, nullable=True)
    fecha_respuesta = db.Column(db.DateTime, nullable=True)
    archivo_ruta = db.Column(db.String(300), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)
    asignado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    tesis = db.relationship("Tesis", back_populates="miembros")
    docente = db.relationship("Docente", back_populates="tesis_roles")
    asignado_por = db.relationship("Usuario")

    __table_args__ = (
        db.UniqueConstraint("tesis_id", "docente_id", "rol", name="uq_tesis_docente_rol"),
        db.CheckConstraint("rol IN ('asesor','coasesor','dictaminante','jurado')", name="rol_valido"),
        db.CheckConstraint("estado_revision IN ('pendiente','observado','visto_bueno')", name="revision_valida"),
    )

    @property
    def rol_nombre(self):
        return ROLES_TESIS.get(self.rol, self.rol)

    @property
    def estado_nombre(self):
        return ESTADOS_REVISION.get(self.estado_revision, self.estado_revision)

    @property
    def emite_dictamen(self):
        return self.rol == "dictaminante"


class TesisVersion(db.Model):
    """Version del documento de tesis subida por el estudiante o la gestion."""

    __tablename__ = "tesis_versiones"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    numero = db.Column(db.Integer, nullable=False)
    archivo_ruta = db.Column(db.String(300), nullable=False)
    archivo_nombre = db.Column(db.String(255), nullable=False)
    comentario = db.Column(db.Text, nullable=True)
    subido_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    tesis = db.relationship("Tesis", back_populates="versiones")
    subido_por = db.relationship("Usuario")

    __table_args__ = (
        db.UniqueConstraint("tesis_id", "numero", name="uq_tesis_version_numero"),
    )


class TesisEvento(db.Model):
    """Bitacora del proceso de la tesis (visible para todos los involucrados)."""

    __tablename__ = "tesis_eventos"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    tipo = db.Column(db.String(30), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    tesis = db.relationship("Tesis", back_populates="eventos")
    usuario = db.relationship("Usuario")
