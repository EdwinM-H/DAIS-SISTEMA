from flask import Blueprint, render_template
from sqlalchemy.orm import joinedload

from models import db, Semestre, Importacion, Evaluacion, DocenteSemestre
from services.evaluacion_service import calcular_ranking
from utils import gestion_required

historial_bp = Blueprint("historial", __name__)


@historial_bp.route("/historial")
@gestion_required
def index():
    f = db.func
    evals = {sid: (n, avg) for sid, n, avg in db.session.query(
        Evaluacion.semestre_id, f.count(Evaluacion.id), f.avg(Evaluacion.promedio_final)
    ).group_by(Evaluacion.semestre_id).all()}
    imps = dict(db.session.query(Importacion.semestre_id, f.count(Importacion.id)).group_by(Importacion.semestre_id).all())
    docs = dict(db.session.query(DocenteSemestre.semestre_id, f.count(DocenteSemestre.id)).group_by(DocenteSemestre.semestre_id).all())

    datos = []
    for s in Semestre.ordenados():
        n, avg = evals.get(s.id, (0, None))
        datos.append({
            "semestre": s, "total_evaluaciones": n, "total_importaciones": imps.get(s.id, 0),
            "total_docentes": docs.get(s.id, 0), "promedio": round(float(avg), 2) if avg is not None else None,
        })
    return render_template("historial/index.html", datos=datos)


@historial_bp.route("/historial/<int:semestre_id>")
@gestion_required
def detalle(semestre_id):
    semestre = db.get_or_404(Semestre, semestre_id)
    importaciones = (Importacion.query.options(joinedload(Importacion.usuario))
                     .filter_by(semestre_id=semestre_id).order_by(Importacion.fecha_importacion.desc()).all())
    return render_template("historial/detalle.html", semestre=semestre, importaciones=importaciones,
                           ranking=calcular_ranking(semestre_id))
