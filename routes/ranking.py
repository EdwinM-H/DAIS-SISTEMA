import csv
import io

from flask import Blueprint, render_template, session, Response, request

from models import db, Semestre, Docente
from services.evaluacion_service import calcular_ranking, historial_docente
from utils import gestion_required

ranking_bp = Blueprint("ranking", __name__)


@ranking_bp.route("/ranking")
@gestion_required
def index():
    semestre_id = session.get("semestre_id")
    semestre = db.session.get(Semestre, semestre_id) if semestre_id else None
    ranking = calcular_ranking(semestre.id) if semestre else []
    clasif = request.args.get("clasificacion", "")
    if clasif:
        ranking = [r for r in ranking if r["clasificacion"] == clasif]
    return render_template("ranking/index.html", ranking=ranking, semestre_actual=semestre, clasif=clasif)


@ranking_bp.route("/ranking/exportar.csv")
@gestion_required
def exportar():
    semestre = db.get_or_404(Semestre, session.get("semestre_id") or 0)
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(["Puesto", "Codigo", "Docente", "Modalidad", "Encuesta", "Normas", "Autoevaluacion", "Promedio final", "Clasificacion"])
    for r in calcular_ranking(semestre.id):
        w.writerow([r["posicion"], r["docente"].codigo, r["docente"].nombre_completo, r["modalidad"],
                    *[f"{v:.2f}".replace(".", ",") if v is not None else "" for v in (r["encuesta"], r["normas"], r["autoevaluacion"], r["promedio_final"])],
                    r["clasificacion"]])
    return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=ranking_{semestre.codigo}.csv"})


@ranking_bp.route("/ranking/comparativa/<int:docente_id>")
@gestion_required
def comparativa(docente_id):
    docente = db.get_or_404(Docente, docente_id)
    return render_template("ranking/comparativa.html", docente=docente, historial=historial_docente(docente.id))
