import json

from models import db

TIPOS_IMPORTACION = {
    "ficha_integral": "Ficha de Evaluacion Integral",
    "docentes": "Lista de docentes",
    "encuesta": "Encuesta estudiantil",
    "normas": "Cumplimiento de normas",
    "autoevaluacion": "Autoevaluacion",
}


class Importacion(db.Model):
    __tablename__ = "importaciones"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    semestre_id = db.Column(db.Integer, db.ForeignKey("semestres.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = db.Column(db.String(30), nullable=False, default="ficha_integral")
    nombre_archivo = db.Column(db.String(255), nullable=False)
    registros_encontrados = db.Column(db.Integer, nullable=False, default=0)
    registros_importados = db.Column(db.Integer, nullable=False, default=0)
    registros_actualizados = db.Column(db.Integer, nullable=False, default=0)
    registros_rechazados = db.Column(db.Integer, nullable=False, default=0)
    capacitaciones_importadas = db.Column(db.Integer, nullable=False, default=0)
    investigaciones_importadas = db.Column(db.Integer, nullable=False, default=0)
    errores = db.Column(db.Text, nullable=True)
    fecha_importacion = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    usuario = db.relationship("Usuario")
    semestre = db.relationship("Semestre", back_populates="importaciones")
    evaluaciones = db.relationship("Evaluacion", back_populates="importacion")

    @property
    def tipo_nombre(self):
        return TIPOS_IMPORTACION.get(self.tipo, self.tipo)

    @property
    def lista_errores(self):
        try:
            return json.loads(self.errores) if self.errores else []
        except ValueError:
            return [self.errores]
