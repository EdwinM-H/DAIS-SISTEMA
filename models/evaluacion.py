from models import db, TimestampMixin

PESO_ENCUESTA = 0.40
PESO_NORMAS = 0.40
PESO_AUTOEVALUACION = 0.20

# Criterios de cumplimiento de normas: (campo, etiqueta, puntaje maximo sobre 100)
CRITERIOS_NORMA = [
    ("reuniones", "Asistencia a reuniones de junta", 15),
    ("silabos", "Entrega de silabos y portafolio", 20),
    ("notas_config", "Configuracion y registro de notas", 15),
    ("horas_lectivas", "Asistencia a horas lectivas", 20),
    ("puntualidad", "Puntualidad", 10),
    ("subida_notas_erp", "Registro de asistencia en ERP", 10),
    ("designacion_delegados", "Eleccion y registro de delegados", 10),
]

# Umbrales de clasificacion (escala /10). Solo se aplican cuando la fuente
# no trae la clasificacion oficial; coinciden con la Ficha de Evaluacion Integral.
UMBRALES_CLASIFICACION = [
    (9.0, "Excelente"),
    (8.0, "Muy Bueno"),
    (7.0, "Bueno"),
    (6.0, "Regular"),
    (0.0, "Insuficiente"),
]
ORDEN_CLASIFICACION = [c for _, c in UMBRALES_CLASIFICACION]


def clasificar(promedio):
    if promedio is None:
        return None
    for minimo, etiqueta in UMBRALES_CLASIFICACION:
        if promedio >= minimo:
            return etiqueta
    return UMBRALES_CLASIFICACION[-1][1]


def umbral_siguiente(promedio):
    """Devuelve (etiqueta, minimo) de la siguiente clasificacion superior o None."""
    if promedio is None:
        return None
    superiores = [(m, e) for m, e in UMBRALES_CLASIFICACION if m > promedio]
    if not superiores:
        return None
    minimo, etiqueta = min(superiores)
    return etiqueta, minimo


def _check_rango(campo, maximo):
    return db.CheckConstraint(
        f"{campo} IS NULL OR ({campo} >= 0 AND {campo} <= {maximo})", name=f"{campo}_rango"
    )


class Evaluacion(db.Model, TimestampMixin):
    __tablename__ = "evaluaciones"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="CASCADE"), nullable=False, index=True)
    importacion_id = db.Column(db.Integer, db.ForeignKey("importaciones.id", ondelete="SET NULL"), nullable=True)

    encuesta = db.Column(db.Float, nullable=True)
    normas = db.Column(db.Float, nullable=True)
    autoevaluacion = db.Column(db.Float, nullable=True)
    promedio_final = db.Column(db.Float, nullable=True)
    clasificacion = db.Column(db.String(30), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    editado_manual = db.Column(db.Boolean, nullable=False, default=False)

    docente = db.relationship("Docente", back_populates="evaluaciones")
    semestre = db.relationship("Semestre", back_populates="evaluaciones")
    importacion = db.relationship("Importacion", back_populates="evaluaciones")

    __table_args__ = (
        db.UniqueConstraint("docente_id", "semestre_id", name="uq_evaluacion_docente_semestre"),
        _check_rango("encuesta", 10),
        _check_rango("normas", 10),
        _check_rango("autoevaluacion", 10),
        _check_rango("promedio_final", 10),
    )

    PESO_ENCUESTA = PESO_ENCUESTA
    PESO_NORMAS = PESO_NORMAS
    PESO_AUTOEVALUACION = PESO_AUTOEVALUACION

    def calcular_promedio(self):
        if None in (self.encuesta, self.normas, self.autoevaluacion):
            self.promedio_final = None
        else:
            self.promedio_final = round(
                self.encuesta * PESO_ENCUESTA
                + self.normas * PESO_NORMAS
                + self.autoevaluacion * PESO_AUTOEVALUACION,
                4,
            )
        return self.promedio_final

    def recalcular(self):
        """Recalcula promedio y clasificacion a partir de los componentes."""
        self.calcular_promedio()
        self.clasificacion = clasificar(self.promedio_final)

    @property
    def estado_evaluacion(self):
        completos = sum(1 for p in (self.encuesta, self.normas, self.autoevaluacion) if p is not None)
        if completos == 3 or self.promedio_final is not None:
            return "Completa"
        if completos > 0:
            return "Parcial"
        return "Pendiente"

    def __repr__(self):
        return f"<Evaluacion docente={self.docente_id} semestre={self.semestre_id} promedio={self.promedio_final}>"


class CriterioNorma(db.Model, TimestampMixin):
    __tablename__ = "criterios_norma"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="CASCADE"), nullable=False, index=True)

    reuniones = db.Column(db.Float, nullable=True)
    silabos = db.Column(db.Float, nullable=True)
    notas_config = db.Column(db.Float, nullable=True)
    horas_lectivas = db.Column(db.Float, nullable=True)
    puntualidad = db.Column(db.Float, nullable=True)
    subida_notas_erp = db.Column(db.Float, nullable=True)
    designacion_delegados = db.Column(db.Float, nullable=True)
    subtotal_normas = db.Column(db.Float, nullable=True)

    docente = db.relationship("Docente", back_populates="criterios_norma")

    __table_args__ = (
        db.UniqueConstraint("docente_id", "semestre_id", name="uq_criterio_docente_semestre"),
        *[db.CheckConstraint(f"{c} IS NULL OR {c} >= 0", name=f"{c}_no_negativo") for c, _, _ in CRITERIOS_NORMA],
        _check_rango("subtotal_normas", 100),
    )

    def valores(self):
        return {campo: getattr(self, campo) for campo, _, _ in CRITERIOS_NORMA}

    def calcular_subtotal(self):
        vals = [v for v in self.valores().values() if v is not None]
        self.subtotal_normas = round(min(sum(vals), 100.0), 4) if vals else None
        return self.subtotal_normas

    @property
    def nota_normas(self):
        """Nota de normas sobre 10 (= subtotal / 10)."""
        sub = self.subtotal_normas if self.subtotal_normas is not None else self.calcular_subtotal()
        return round(sub / 10.0, 4) if sub is not None else None
