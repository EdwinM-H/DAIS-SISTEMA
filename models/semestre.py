import re

from models import db

CODIGO_RE = re.compile(r"^(20\d{2})-(I|II)$")


class Semestre(db.Model):
    __tablename__ = "semestres"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    periodo = db.Column(db.String(2), nullable=False)
    activo = db.Column(db.Boolean, nullable=False, default=False)
    publicado = db.Column(db.Boolean, nullable=False, default=False)
    # Los resultados (promedio, clasificacion, ranking) solo existen tras "Calcular resultados".
    # Si luego se importan datos nuevos, resultados_vigentes pasa a False hasta recalcular.
    resultados_vigentes = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    fecha_calculo = db.Column(db.DateTime, nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    evaluaciones = db.relationship("Evaluacion", back_populates="semestre", cascade="all, delete-orphan")
    importaciones = db.relationship("Importacion", back_populates="semestre", cascade="all, delete-orphan")
    participaciones = db.relationship("DocenteSemestre", back_populates="semestre", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("anio", "periodo", name="uq_semestres_anio_periodo"),
        db.CheckConstraint("periodo IN ('I','II')", name="periodo_valido"),
    )

    @staticmethod
    def parsear_codigo(codigo):
        """Valida 'AAAA-I' / 'AAAA-II'. Devuelve (anio, periodo) o None."""
        m = CODIGO_RE.match((codigo or "").strip().upper())
        if not m:
            return None
        return int(m.group(1)), m.group(2)

    @classmethod
    def crear(cls, anio, periodo):
        return cls(codigo=f"{anio}-{periodo}", anio=anio, periodo=periodo)

    @property
    def estado_resultados(self):
        """'pendiente' (nunca calculados), 'vigente' o 'desactualizado' (hubo cambios)."""
        if not self.fecha_calculo:
            return "pendiente"
        return "vigente" if self.resultados_vigentes else "desactualizado"

    def marcar_desactualizado(self):
        if self.fecha_calculo:
            self.resultados_vigentes = False

    @property
    def orden(self):
        return (self.anio, 1 if self.periodo == "I" else 2)

    @classmethod
    def ordenados(cls, desc=True):
        q = cls.query.order_by(cls.anio.desc() if desc else cls.anio, cls.periodo.desc() if desc else cls.periodo)
        return q.all()

    @classmethod
    def activo_actual(cls):
        return cls.query.filter_by(activo=True).first()

    def __repr__(self):
        return f"<Semestre {self.codigo}>"
