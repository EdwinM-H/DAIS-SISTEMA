"""Produccion academica del docente: capacitaciones e investigaciones/publicaciones."""

from models import db, TimestampMixin

ESTADOS_VALIDACION = {
    "pendiente": "Pendiente de revision",
    "validado": "Validado",
    "observado": "Observado",
}

TIPOS_CAPACITACION = [
    "Curso", "Taller", "Diplomado", "Seminario", "Congreso", "Especializacion",
    "Certificacion", "Maestria", "Doctorado", "Otro",
]

TIPOS_INVESTIGACION = ["Publicaciones", "Proyectos", "Libros", "Ponencias", "Otro"]
SUBTIPOS_INVESTIGACION = [
    "Articulo Cientifico", "Articulo de Opinion", "Investigacion y Desarrollo",
    "Libro", "Capitulo de libro", "Ponencia", "Tesis asesorada", "Otro",
]


class _Validable:
    estado_validacion = db.Column(db.String(12), nullable=False, default="pendiente", index=True)
    observacion_validacion = db.Column(db.Text, nullable=True)
    fecha_validacion = db.Column(db.DateTime, nullable=True)
    origen = db.Column(db.String(10), nullable=False, default="docente")  # docente | excel | gestion
    archivo_ruta = db.Column(db.String(300), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)

    @property
    def estado_nombre(self):
        return ESTADOS_VALIDACION.get(self.estado_validacion, self.estado_validacion)


class Capacitacion(db.Model, TimestampMixin, _Validable):
    __tablename__ = "capacitaciones"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = db.Column(db.String(400), nullable=False)
    tipo = db.Column(db.String(40), nullable=True)
    institucion = db.Column(db.String(200), nullable=True)
    anio = db.Column(db.Integer, nullable=False, index=True)
    horas = db.Column(db.Float, nullable=True)
    fecha_inicio = db.Column(db.Date, nullable=True)
    fecha_fin = db.Column(db.Date, nullable=True)
    validado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    docente = db.relationship("Docente", back_populates="capacitaciones")
    validado_por = db.relationship("Usuario")

    __table_args__ = (
        db.CheckConstraint("anio BETWEEN 1950 AND 2100", name="anio_valido"),
        db.CheckConstraint("horas IS NULL OR horas >= 0", name="horas_no_negativas"),
        db.CheckConstraint("estado_validacion IN ('pendiente','validado','observado')", name="estado_valido"),
        db.CheckConstraint("fecha_fin IS NULL OR fecha_inicio IS NULL OR fecha_fin >= fecha_inicio", name="fechas_validas"),
    )


class Investigacion(db.Model, TimestampMixin, _Validable):
    __tablename__ = "investigaciones"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    titulo = db.Column(db.String(600), nullable=False)
    tipo = db.Column(db.String(40), nullable=False, default="Publicaciones")
    subtipo = db.Column(db.String(60), nullable=True)
    anio = db.Column(db.Integer, nullable=False, index=True)
    medio = db.Column(db.String(300), nullable=True)  # revista, editorial, evento
    enlace = db.Column(db.String(500), nullable=True)  # DOI o URL
    rol_autor = db.Column(db.String(40), nullable=True)  # Autor, Coautor, Investigador principal
    validado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    docente = db.relationship("Docente", back_populates="investigaciones")
    validado_por = db.relationship("Usuario")

    __table_args__ = (
        db.CheckConstraint("anio BETWEEN 1950 AND 2100", name="anio_valido"),
        db.CheckConstraint("estado_validacion IN ('pendiente','validado','observado')", name="estado_valido"),
    )
