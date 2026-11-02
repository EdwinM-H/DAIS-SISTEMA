import unicodedata
from datetime import date

from models import db, TimestampMixin

ESCUELA_DEFAULT = "Escuela Profesional de Ingenieria de Sistemas"
ESTADOS_DOCENTE = ("activo", "inactivo")

CATEGORIAS = ["Principal", "Asociado", "Auxiliar", "Contratado"]
RANGO_CATEGORIA = {"principal": 0, "asociado": 1, "auxiliar": 2, "contratado": 3}
GRADOS = ["Bachiller", "Titulado", "Maestro", "Doctor"]
CONDICIONES = {"ordinario": "Ordinario", "contratado": "Contratado"}


def _sin_tildes(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c))


def normalizar_nombre(texto):
    """Clave de busqueda independiente del orden, tildes y mayusculas.

    'ACURIO GUTIERREZ MARIA ISABEL' y 'Maria Isabel Acurio Gutierrez'
    producen la misma clave, por lo que editar o reimportar un docente
    nunca genera duplicados.
    """
    tokens = _sin_tildes(texto).upper().replace(",", " ").split()
    return " ".join(sorted(tokens))


def titulo(texto):
    """'ACURIO GUTIERREZ' -> 'Acurio Gutierrez' conservando tildes."""
    return " ".join(p.capitalize() for p in str(texto or "").split())


class Docente(db.Model, TimestampMixin):
    __tablename__ = "docentes"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    dni = db.Column(db.String(15), unique=True, nullable=True)
    nombres = db.Column(db.String(150), nullable=False)
    apellidos = db.Column(db.String(150), nullable=False)
    nombre_normalizado = db.Column(db.String(300), nullable=False, index=True)
    especialidad = db.Column(db.String(200), nullable=True)
    grado_academico = db.Column(db.String(100), nullable=True)
    categoria_docente = db.Column(db.String(100), nullable=True)
    correo_institucional = db.Column(db.String(200), nullable=True)
    telefono = db.Column(db.String(30), nullable=True)
    escuela = db.Column(db.String(150), nullable=False, default=ESCUELA_DEFAULT)
    departamento = db.Column(db.String(150), nullable=True)
    anio_ingreso = db.Column(db.Integer, nullable=True)
    estado = db.Column(db.String(10), nullable=False, default="activo")

    # ---- Perfil academico (prelacion y afinidad para tesis) ----
    # Datos oficiales: los registra el DAIS
    condicion = db.Column(db.String(12), nullable=True)            # ordinario | contratado
    es_autoridad = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    cargo_autoridad = db.Column(db.String(100), nullable=True)
    # Datos declarados por el docente (colegiatura, grado y licencia requieren validacion)
    colegiatura_numero = db.Column(db.String(30), nullable=True)
    colegiatura_anio = db.Column(db.Integer, nullable=True)
    experiencia_anios = db.Column(db.Integer, nullable=True)
    licencia_desde = db.Column(db.Date, nullable=True)
    licencia_hasta = db.Column(db.Date, nullable=True)
    linea_principal_id = db.Column(db.Integer, db.ForeignKey("lineas_investigacion.id", ondelete="SET NULL"), nullable=True)
    perfil_actualizado_en = db.Column(db.DateTime, nullable=True)

    linea_principal = db.relationship("LineaInvestigacion", foreign_keys=[linea_principal_id])
    lineas = db.relationship("LineaInvestigacion", secondary="docente_lineas", order_by="LineaInvestigacion.id")
    temas = db.relationship("TemaInvestigacion", secondary="docente_temas", order_by="TemaInvestigacion.id")
    cambios_perfil = db.relationship("CambioPerfil", back_populates="docente", cascade="all, delete-orphan",
                                     order_by="CambioPerfil.id.desc()")

    usuario = db.relationship("Usuario", back_populates="docente", uselist=False)
    evaluaciones = db.relationship("Evaluacion", back_populates="docente", cascade="all, delete-orphan")
    criterios_norma = db.relationship("CriterioNorma", back_populates="docente", cascade="all, delete-orphan")
    participaciones = db.relationship("DocenteSemestre", back_populates="docente", cascade="all, delete-orphan")
    capacitaciones = db.relationship(
        "Capacitacion", back_populates="docente", cascade="all, delete-orphan",
        order_by="Capacitacion.anio.desc()",
    )
    investigaciones = db.relationship(
        "Investigacion", back_populates="docente", cascade="all, delete-orphan",
        order_by="Investigacion.anio.desc()",
    )
    tesis_roles = db.relationship("TesisMiembro", back_populates="docente", cascade="all, delete-orphan")

    __table_args__ = (
        db.CheckConstraint("estado IN ('activo','inactivo')", name="estado_valido"),
        db.CheckConstraint(
            "anio_ingreso IS NULL OR (anio_ingreso BETWEEN 1950 AND 2100)", name="anio_ingreso_valido"
        ),
        db.CheckConstraint("condicion IS NULL OR condicion IN ('ordinario','contratado')", name="condicion_valida"),
        db.CheckConstraint("colegiatura_anio IS NULL OR (colegiatura_anio BETWEEN 1950 AND 2100)", name="colegiatura_valida"),
        db.CheckConstraint("experiencia_anios IS NULL OR (experiencia_anios BETWEEN 0 AND 70)", name="experiencia_valida"),
        db.CheckConstraint("licencia_hasta IS NULL OR licencia_desde IS NULL OR licencia_hasta >= licencia_desde",
                           name="licencia_valida"),
    )

    # ---- Perfil academico ----
    def de_licencia(self, fecha=None):
        fecha = fecha or date.today()
        if not self.licencia_desde:
            return False
        return self.licencia_desde <= fecha and (self.licencia_hasta is None or fecha <= self.licencia_hasta)

    @property
    def disponible(self):
        return self.estado == "activo" and not self.es_autoridad and not self.de_licencia()

    def faltantes_perfil(self):
        """Datos que faltan para la prelacion y la afinidad (lo usa el aviso del portal)."""
        faltan = []
        if not self.temas:
            faltan.append("líneas y temas de investigación")
        if not self.grado_academico:
            faltan.append("grado académico")
        if not self.colegiatura_anio:
            faltan.append("año de colegiatura")
        if self.experiencia_anios is None:
            faltan.append("años de experiencia profesional")
        return faltan

    @property
    def perfil_completo(self):
        return not self.faltantes_perfil()

    @property
    def clave_prelacion(self):
        """Orden del Art. 71/97: categoria, antiguedad en la UAC, colegiatura, experiencia.

        Valores faltantes van al final dentro de su grupo.
        """
        rango = RANGO_CATEGORIA.get((self.categoria_docente or "").strip().lower(), 9)
        ingreso = self.anio_ingreso or 9999
        colegiatura = self.colegiatura_anio or 9999
        experiencia = -(self.experiencia_anios or 0)
        return (rango, ingreso, colegiatura, experiencia, self.apellidos)

    def faltantes_prelacion(self):
        faltan = []
        if (self.categoria_docente or "").strip().lower() not in RANGO_CATEGORIA:
            faltan.append("categoría")
        if not self.anio_ingreso:
            faltan.append("año de ingreso a la UAC")
        if not self.colegiatura_anio:
            faltan.append("año de colegiatura")
        return faltan

    @property
    def nombre_completo(self):
        """Formato institucional: APELLIDOS, Nombres."""
        return f"{self.apellidos}, {self.nombres}".strip(", ")

    @property
    def nombre_natural(self):
        return f"{self.nombres} {self.apellidos}".strip()

    @property
    def anios_servicio(self):
        if not self.anio_ingreso:
            return None
        return max(date.today().year - self.anio_ingreso, 0)

    def actualizar_nombre_normalizado(self):
        self.nombre_normalizado = normalizar_nombre(f"{self.apellidos} {self.nombres}")

    @staticmethod
    def buscar_por_nombre(nombre):
        """Coincidencia exacta por clave normalizada (sin falsos positivos por subcadena)."""
        clave = normalizar_nombre(nombre)
        if not clave:
            return None
        return Docente.query.filter_by(nombre_normalizado=clave).first()

    @staticmethod
    def siguiente_codigo():
        mayor = 0
        for (cod,) in db.session.query(Docente.codigo).filter(Docente.codigo.like("DOC-%")).all():
            try:
                mayor = max(mayor, int(cod.split("-", 1)[1]))
            except (ValueError, IndexError):
                continue
        return f"DOC-{mayor + 1:04d}"

    def __repr__(self):
        return f"<Docente {self.codigo} - {self.nombre_completo}>"


@db.event.listens_for(Docente, "before_insert")
@db.event.listens_for(Docente, "before_update")
def _mantener_clave(mapper, connection, target):
    target.actualizar_nombre_normalizado()


class DocenteSemestre(db.Model):
    """Participacion de un docente en un semestre (y su modalidad en ese periodo)."""

    __tablename__ = "docentes_semestre"

    id = db.Column(db.Integer, primary_key=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="CASCADE"), nullable=False, index=True)
    modalidad = db.Column(db.String(50), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    docente = db.relationship("Docente", back_populates="participaciones")
    semestre = db.relationship("Semestre", back_populates="participaciones")

    __table_args__ = (
        db.UniqueConstraint("docente_id", "semestre_id", name="uq_docente_semestre"),
    )
