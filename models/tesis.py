"""Gestion de tesis segun el Reglamento Marco de Grados y Titulos (Res. 256-CU-2024-UAC).

Etapas (tesis ordinaria): asesor -> dictamen de proyecto (2 dictaminantes) -> inscripcion del tema
-> desarrollo (1 anio) -> dictamen de tesis (los 2 + 1 = 3) -> apto -> sustentacion -> titulado.
Trabajo de suficiencia profesional: asesor -> dictamen (3) -> apto -> sustentacion.
"""

from models import db, TimestampMixin
from models.docente import normalizar_nombre

MODALIDADES_TESIS = {
    "tesis": "Tesis",
    "suficiencia": "Trabajo de suficiencia profesional",
}
REGIMENES = {
    "vigente": "Reglamento vigente (3 dictaminantes)",
    "anterior": "Régimen anterior (2 dictaminantes + 2 replicantes)",
}

ETAPAS_TESIS = {
    "asesor": "Designación de asesor",
    "proyecto": "Dictamen del proyecto",
    "inscripcion": "Inscripción del tema",
    "desarrollo": "Desarrollo de la tesis",
    "dictamen": "Dictamen de la tesis",
    "apto": "Declaración de apto",
    "sustentacion": "Sustentación programada",
    "observaciones": "Levantamiento de observaciones",
    "titulado": "Sustentada y aprobada",
    "rechazada": "Rechazada (nuevo trámite)",
    "anulada": "Anulada",
}
ETAPAS_CERRADAS = ("titulado", "rechazada", "anulada")
# Compatibilidad con plantillas y filtros existentes
ESTADOS_TESIS = ETAPAS_TESIS

LINEA_TIEMPO = {
    "tesis": ["asesor", "proyecto", "inscripcion", "desarrollo", "dictamen", "apto", "sustentacion", "titulado"],
    "suficiencia": ["asesor", "dictamen", "apto", "sustentacion", "titulado"],
}

ROLES_TESIS = {
    "asesor": "Asesor",
    "coasesor": "Coasesor",
    "dictaminante": "Dictaminante",
    "dirimente": "Dirimente",
    "replicante": "Replicante",
}
ESTADOS_DESIGNACION = {
    "propuesto": "Por aceptar",
    "aceptado": "Aceptado",
    "impedimento": "Declaró impedimento",
    "reemplazado": "Reemplazado",
    "retirado": "Retirado",
}
ACTIVOS = ("propuesto", "aceptado")

RESULTADOS_DICTAMEN = {
    "suficiente": "Suficiente",
    "con_observaciones": "Con observaciones",
    "insuficiente": "Insuficiente",
}
# Compatibilidad: algunas vistas antiguas usan ESTADOS_REVISION
ESTADOS_REVISION = RESULTADOS_DICTAMEN

TIPOS_RESOLUCION = {
    "asesor": "Designación de asesor",
    "dictaminantes_proyecto": "Designación de dictaminantes del proyecto",
    "inscripcion": "Inscripción del tema de tesis",
    "ampliacion": "Ampliación de plazo",
    "dictaminantes_tesis": "Designación de dictaminantes de la tesis",
    "dirimente": "Designación de dirimente",
    "apto": "Declaración de apto",
    "sustentacion": "Fecha y hora de sustentación",
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
    palabras_clave = db.Column(db.String(300), nullable=True)
    area_id = db.Column(db.Integer, db.ForeignKey("areas_investigacion.id", ondelete="SET NULL"), nullable=True)
    linea_id = db.Column(db.Integer, db.ForeignKey("lineas_investigacion.id", ondelete="SET NULL"), nullable=True)
    modalidad = db.Column(db.String(12), nullable=False, default="tesis")
    regimen = db.Column(db.String(10), nullable=False, default="vigente")
    etapa = db.Column(db.String(15), nullable=False, default="asesor", index=True)
    decision_pendiente = db.Column(db.String(200), nullable=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="SET NULL"), nullable=True)
    fecha_registro = db.Column(db.Date, nullable=True)
    fecha_inscripcion = db.Column(db.Date, nullable=True)
    fecha_limite_entrega = db.Column(db.Date, nullable=True)
    plazo_ampliado = db.Column(db.Boolean, nullable=False, default=False)
    fecha_sustentacion = db.Column(db.DateTime, nullable=True)
    lugar_sustentacion = db.Column(db.String(200), nullable=True)
    modalidad_sustentacion = db.Column(db.String(10), nullable=True)   # presencial | virtual
    numero_sustentacion = db.Column(db.Integer, nullable=False, default=0)
    nota_sustentacion = db.Column(db.Integer, nullable=True)
    calificacion = db.Column(db.String(60), nullable=True)
    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    area = db.relationship("AreaInvestigacion")
    linea = db.relationship("LineaInvestigacion")
    temas = db.relationship("TemaInvestigacion", secondary="tesis_temas", order_by="TemaInvestigacion.id")
    semestre = db.relationship("Semestre")
    creado_por = db.relationship("Usuario")
    estudiantes = db.relationship("Estudiante", secondary=tesis_estudiantes, back_populates="tesis")
    miembros = db.relationship("TesisMiembro", back_populates="tesis", cascade="all, delete-orphan",
                               order_by="TesisMiembro.id")
    dictamenes = db.relationship("Dictamen", back_populates="tesis", cascade="all, delete-orphan",
                                 order_by="Dictamen.id")
    versiones = db.relationship("TesisVersion", back_populates="tesis", cascade="all, delete-orphan",
                                order_by="TesisVersion.numero.desc()")
    resoluciones = db.relationship("ResolucionTesis", back_populates="tesis", cascade="all, delete-orphan",
                                   order_by="ResolucionTesis.id")
    eventos = db.relationship("TesisEvento", back_populates="tesis", cascade="all, delete-orphan",
                              order_by="TesisEvento.id.desc()")

    __table_args__ = (
        db.CheckConstraint("modalidad IN ('tesis','suficiencia')", name="modalidad_valida"),
        db.CheckConstraint("regimen IN ('vigente','anterior')", name="regimen_valido"),
        db.CheckConstraint(
            "etapa IN ('asesor','proyecto','inscripcion','desarrollo','dictamen','apto','sustentacion',"
            "'observaciones','titulado','rechazada','anulada')", name="etapa_valida"),
        db.CheckConstraint("nota_sustentacion IS NULL OR (nota_sustentacion BETWEEN 0 AND 20)", name="nota_rango"),
    )

    # ---- Presentacion ----
    @property
    def etapa_nombre(self):
        return ETAPAS_TESIS.get(self.etapa, self.etapa)

    # Compatibilidad con vistas existentes
    estado = property(lambda self: self.etapa)
    estado_nombre = property(lambda self: self.etapa_nombre)

    @property
    def modalidad_nombre(self):
        return MODALIDADES_TESIS.get(self.modalidad, self.modalidad)

    @property
    def cerrada(self):
        return self.etapa in ETAPAS_CERRADAS

    @property
    def estudiantes_texto(self):
        return "; ".join(e.nombre_completo for e in self.estudiantes) or "-"

    # ---- Miembros ----
    def activos(self, *roles):
        return [m for m in self.miembros if m.estado_designacion in ACTIVOS and (not roles or m.rol in roles)]

    @property
    def asesor(self):
        a = self.activos("asesor")
        return a[0] if a else None

    @property
    def dictaminantes(self):
        return sorted(self.activos("dictaminante"), key=lambda m: (m.orden_prelacion or 99, m.id))

    @property
    def dirimentes(self):
        return self.activos("dirimente")

    @property
    def jurado(self):
        """Jurado de sustentacion ordenado por prelacion: el primero preside, el ultimo es secretario."""
        miembros = self.dictaminantes + (self.activos("replicante") if self.regimen == "anterior" else [])
        return sorted(miembros, key=lambda m: m.docente.clave_prelacion)

    @property
    def presidente(self):
        j = self.jurado
        return j[0] if j else None

    @property
    def secretario(self):
        j = self.jurado
        return j[-1] if len(j) > 1 else None

    @property
    def version_actual(self):
        return self.versiones[0] if self.versiones else None

    def resolucion(self, tipo):
        r = [x for x in self.resoluciones if x.tipo == tipo]
        return r[-1] if r else None

    # ---- Dictamenes ----
    def dictamenes_de(self, etapa):
        return [d for d in self.dictamenes if d.etapa == etapa]

    def ronda_actual(self, etapa):
        return max((d.ronda for d in self.dictamenes_de(etapa)), default=0)

    @property
    def etapa_dictamen(self):
        if self.etapa == "proyecto":
            return "proyecto"
        if self.etapa == "dictamen":
            return "tesis"
        return None

    def ultimo_dictamen(self, miembro, etapa):
        propios = [d for d in self.dictamenes if d.miembro_id == miembro.id and d.etapa == etapa]
        return propios[-1] if propios else None

    @property
    def progreso_dictamen(self):
        """(suficientes, total) de la etapa de dictamen actual (o la de tesis si ya paso)."""
        etapa = self.etapa_dictamen or ("tesis" if self.modalidad == "suficiencia" or self.dictamenes_de("tesis") else "proyecto")
        miembros = self.dictaminantes
        ok = 0
        for m in miembros:
            d = self.ultimo_dictamen(m, etapa)
            if d and d.resultado == "suficiente":
                ok += 1
        return ok, len(miembros)

    def linea_tiempo(self):
        """[(clave, etiqueta, estado)] con estado en 'hecho' | 'actual' | 'pendiente'."""
        orden = LINEA_TIEMPO[self.modalidad]
        if self.etapa in ETAPAS_CERRADAS and self.etapa != "titulado":
            return [(c, ETAPAS_TESIS[c], "pendiente") for c in orden]
        actual = "sustentacion" if self.etapa == "observaciones" else self.etapa
        idx = orden.index(actual) if actual in orden else len(orden)
        salida = []
        for i, c in enumerate(orden):
            estado = "hecho" if i < idx or self.etapa == "titulado" else ("actual" if i == idx else "pendiente")
            salida.append((c, ETAPAS_TESIS[c], estado))
        return salida

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
    """Designacion de un docente en una tesis (asesor, dictaminante, dirimente, replicante)."""

    __tablename__ = "tesis_miembros"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    rol = db.Column(db.String(15), nullable=False)
    etapa_ingreso = db.Column(db.String(10), nullable=True)          # proyecto | tesis
    estado_designacion = db.Column(db.String(12), nullable=False, default="propuesto")
    orden_prelacion = db.Column(db.Integer, nullable=True)
    automatico = db.Column(db.Boolean, nullable=False, default=False)
    puntaje = db.Column(db.Float, nullable=True)
    motivos = db.Column(db.Text, nullable=True)
    fecha_designacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    fecha_respuesta = db.Column(db.DateTime, nullable=True)
    motivo_impedimento = db.Column(db.Text, nullable=True)
    nota_sustentacion = db.Column(db.Float, nullable=True)
    asignado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    tesis = db.relationship("Tesis", back_populates="miembros")
    docente = db.relationship("Docente", back_populates="tesis_roles")
    asignado_por = db.relationship("Usuario")
    dictamenes = db.relationship("Dictamen", back_populates="miembro", cascade="all, delete-orphan",
                                 order_by="Dictamen.id")

    __table_args__ = (
        db.UniqueConstraint("tesis_id", "docente_id", "rol", name="uq_tesis_docente_rol"),
        db.CheckConstraint("rol IN ('asesor','coasesor','dictaminante','dirimente','replicante')", name="rol_valido"),
        db.CheckConstraint(
            "estado_designacion IN ('propuesto','aceptado','impedimento','reemplazado','retirado')",
            name="designacion_valida"),
        db.CheckConstraint("nota_sustentacion IS NULL OR (nota_sustentacion BETWEEN 0 AND 20)", name="nota_rango"),
    )

    @property
    def rol_nombre(self):
        return ROLES_TESIS.get(self.rol, self.rol)

    @property
    def estado_nombre(self):
        return ESTADOS_DESIGNACION.get(self.estado_designacion, self.estado_designacion)

    @property
    def activo(self):
        return self.estado_designacion in ACTIVOS

    @property
    def emite_dictamen(self):
        return self.rol in ("dictaminante", "dirimente")

    @property
    def lista_motivos(self):
        return [m for m in (self.motivos or "").split("|") if m]


class Dictamen(db.Model):
    """Dictamen de un miembro en una ronda de revision (proyecto o tesis)."""

    __tablename__ = "dictamenes"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    miembro_id = db.Column(db.Integer, db.ForeignKey("tesis_miembros.id", ondelete="CASCADE"), nullable=False, index=True)
    etapa = db.Column(db.String(10), nullable=False)
    ronda = db.Column(db.Integer, nullable=False, default=1)
    resultado = db.Column(db.String(20), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)
    archivo_ruta = db.Column(db.String(300), nullable=True)
    archivo_nombre = db.Column(db.String(255), nullable=True)
    inicio = db.Column(db.Date, nullable=False)
    limite = db.Column(db.Date, nullable=False)
    emitido_en = db.Column(db.DateTime, nullable=True)

    tesis = db.relationship("Tesis", back_populates="dictamenes")
    miembro = db.relationship("TesisMiembro", back_populates="dictamenes")

    __table_args__ = (
        db.UniqueConstraint("miembro_id", "etapa", "ronda", name="uq_dictamen_miembro_ronda"),
        db.CheckConstraint("etapa IN ('proyecto','tesis')", name="etapa_valida"),
        db.CheckConstraint("resultado IS NULL OR resultado IN ('suficiente','con_observaciones','insuficiente')",
                           name="resultado_valido"),
    )

    @property
    def resultado_nombre(self):
        return RESULTADOS_DICTAMEN.get(self.resultado, "Pendiente")

    @property
    def pendiente(self):
        return self.resultado is None


class TesisVersion(db.Model):
    """Documento subido por el estudiante (o la gestion) en cada etapa."""

    __tablename__ = "tesis_versiones"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    numero = db.Column(db.Integer, nullable=False)
    etapa = db.Column(db.String(12), nullable=False, default="proyecto")   # proyecto | tesis | final
    archivo_ruta = db.Column(db.String(300), nullable=False)
    archivo_nombre = db.Column(db.String(255), nullable=False)
    subsanacion_ruta = db.Column(db.String(300), nullable=True)   # documento "como se levantaron las observaciones"
    subsanacion_nombre = db.Column(db.String(255), nullable=True)
    comentario = db.Column(db.Text, nullable=True)
    subido_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    tesis = db.relationship("Tesis", back_populates="versiones")
    subido_por = db.relationship("Usuario")

    __table_args__ = (
        db.UniqueConstraint("tesis_id", "numero", name="uq_tesis_version_numero"),
        db.CheckConstraint("etapa IN ('proyecto','tesis','final')", name="etapa_valida"),
    )

    @property
    def etapa_nombre(self):
        return {"proyecto": "Proyecto de tesis", "tesis": "Tesis", "final": "Versión final"}.get(self.etapa, self.etapa)


class ResolucionTesis(db.Model):
    __tablename__ = "resoluciones_tesis"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False)
    numero = db.Column(db.String(80), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    registrada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    tesis = db.relationship("Tesis", back_populates="resoluciones")

    @property
    def tipo_nombre(self):
        return TIPOS_RESOLUCION.get(self.tipo, self.tipo)


class TesisEvento(db.Model):
    """Bitacora del proceso (visible para todos los involucrados)."""

    __tablename__ = "tesis_eventos"

    id = db.Column(db.Integer, primary_key=True)
    tesis_id = db.Column(db.Integer, db.ForeignKey("tesis.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    tipo = db.Column(db.String(30), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    tesis = db.relationship("Tesis", back_populates="eventos")
    usuario = db.relationship("Usuario")
