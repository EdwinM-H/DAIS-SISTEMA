from sqlalchemy import func

from models import (
    db, Evaluacion, Semestre, DocenteSemestre, Capacitacion, Investigacion, Tesis, Usuario,
)
from models.evaluacion import ORDEN_CLASIFICACION
from services.evaluacion_service import calcular_ranking, promedios_semestre

RANGOS_NOTA = [(0, 6, "0 - 6"), (6, 7, "6 - 7"), (7, 8, "7 - 8"), (8, 9, "8 - 9"), (9, 10.0001, "9 - 10")]


def get_dashboard_stats(semestre_id=None):
    stats = {
        "semestre_actual": None,
        "total_docentes": 0,
        "evaluaciones_completas": 0,
        "evaluaciones_parciales": 0,
        "evaluaciones_pendientes": 0,
        "promedio_general": None,
        "mejor_promedio": None,
        "mejor_docente": None,
        "ranking": [],
        "clasificaciones": [],
        "distribucion_puntajes": [],
        "promedios_componentes": None,
        "evolucion_semestres": [],
        "pendientes_validacion": 0,
        "tesis_activas": 0,
        "tesis_por_estado": [],
        "docentes_con_cuenta": 0,
    }

    stats["pendientes_validacion"] = (
        Capacitacion.query.filter_by(estado_validacion="pendiente").count()
        + Investigacion.query.filter_by(estado_validacion="pendiente").count()
    )
    stats["tesis_activas"] = Tesis.query.filter(Tesis.estado.notin_(("sustentada", "anulada"))).count()
    stats["tesis_por_estado"] = [
        {"estado": e, "cantidad": c}
        for e, c in db.session.query(Tesis.estado, func.count(Tesis.id)).group_by(Tesis.estado).all()
    ]
    stats["docentes_con_cuenta"] = Usuario.query.filter(Usuario.rol == "docente", Usuario.activo.is_(True)).count()

    # Evolucion historica (una sola consulta agrupada)
    promedios = dict(
        db.session.query(Evaluacion.semestre_id, func.avg(Evaluacion.promedio_final))
        .filter(Evaluacion.promedio_final.isnot(None))
        .group_by(Evaluacion.semestre_id).all()
    )
    for s in Semestre.ordenados(desc=False):
        if s.id in promedios:
            stats["evolucion_semestres"].append({"semestre": s.codigo, "promedio": round(float(promedios[s.id]), 2)})

    semestre = db.session.get(Semestre, semestre_id) if semestre_id else None
    if not semestre:
        return stats
    stats["semestre_actual"] = {"id": semestre.id, "codigo": semestre.codigo,
                                "estado_resultados": semestre.estado_resultados}

    total_doc = DocenteSemestre.query.filter_by(semestre_id=semestre.id).count()
    evaluaciones = Evaluacion.query.filter_by(semestre_id=semestre.id).all()
    stats["total_docentes"] = total_doc
    stats["evaluaciones_completas"] = sum(1 for e in evaluaciones if e.estado_evaluacion == "Completa")
    stats["evaluaciones_parciales"] = sum(1 for e in evaluaciones if e.estado_evaluacion == "Parcial")
    stats["evaluaciones_pendientes"] = max(total_doc - len(evaluaciones), 0)

    ranking = calcular_ranking(semestre.id)
    stats["ranking"] = ranking
    if ranking:
        stats["promedio_general"] = round(sum(r["promedio_final"] for r in ranking) / len(ranking), 2)
        stats["mejor_promedio"] = ranking[0]["promedio_final"]
        stats["mejor_docente"] = ranking[0]["docente"].nombre_completo

    proms = promedios_semestre(semestre.id)
    stats["promedios_componentes"] = {
        k: round(float(proms[k]), 2) if proms.get(k) is not None else 0
        for k in ("encuesta", "normas", "autoevaluacion", "promedio_final")
    }

    conteo = {}
    for e in evaluaciones:
        if e.clasificacion:
            conteo[e.clasificacion.strip()] = conteo.get(e.clasificacion.strip(), 0) + 1
    orden = [c for c in ORDEN_CLASIFICACION if c in conteo] + sorted(c for c in conteo if c not in ORDEN_CLASIFICACION)
    stats["clasificaciones"] = [{"clasificacion": c, "cantidad": conteo[c]} for c in orden]

    finales = [e.promedio_final for e in evaluaciones if e.promedio_final is not None]
    stats["distribucion_puntajes"] = [
        {"rango": etiqueta, "cantidad": sum(1 for p in finales if minimo <= p < maximo)}
        for minimo, maximo, etiqueta in RANGOS_NOTA
    ]
    return stats
