from models import db


class DocumentoGenerado(db.Model):
    __tablename__ = "documentos_generados"

    id = db.Column(db.Integer, primary_key=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="CASCADE"), nullable=False, index=True)
    docente_id = db.Column(db.Integer, db.ForeignKey("docentes.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(300), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="individual")
    fecha_generacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    semestre = db.relationship("Semestre")
    docente = db.relationship("Docente")
    usuario = db.relationship("Usuario")

    __table_args__ = (
        db.CheckConstraint("tipo IN ('individual','masivo')", name="tipo_valido"),
    )
