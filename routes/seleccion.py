from flask import Blueprint, request, session, jsonify

from models import db, Semestre
from utils import gestion_required

seleccion_bp = Blueprint("seleccion", __name__)


@seleccion_bp.route("/api/semestres")
@gestion_required
def api_listar():
    actual_id = session.get("semestre_id")
    return jsonify([
        {"id": s.id, "codigo": s.codigo, "actual": s.id == actual_id, "activo": s.activo}
        for s in Semestre.ordenados()
    ])


@seleccion_bp.route("/api/cambiar-semestre", methods=["POST"])
@gestion_required
def api_cambiar():
    data = request.get_json(silent=True) or {}
    try:
        semestre = db.session.get(Semestre, int(data.get("semestre_id")))
    except (TypeError, ValueError):
        semestre = None
    if not semestre:
        return jsonify({"error": "Semestre no encontrado"}), 404
    session["semestre_id"], session["semestre_codigo"] = semestre.id, semestre.codigo
    return jsonify({"ok": True, "id": semestre.id, "codigo": semestre.codigo})


@seleccion_bp.route("/api/crear-semestre", methods=["POST"])
@gestion_required
def api_crear():
    data = request.get_json(silent=True) or {}
    datos = Semestre.parsear_codigo(f"{str(data.get('anio', '')).strip()}-{str(data.get('periodo', '')).strip()}")
    if not datos:
        return jsonify({"error": "Anio (20XX) o periodo (I/II) invalido"}), 400
    codigo = f"{datos[0]}-{datos[1]}"
    if Semestre.query.filter_by(codigo=codigo).first():
        return jsonify({"error": f"El semestre {codigo} ya existe"}), 400
    semestre = Semestre.crear(*datos)
    db.session.add(semestre)
    db.session.commit()
    session["semestre_id"], session["semestre_codigo"] = semestre.id, semestre.codigo
    return jsonify({"ok": True, "id": semestre.id, "codigo": semestre.codigo})
