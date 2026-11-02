"""Logica central del proceso de evaluacion: ranking, estadisticas y puntos de mejora.

Todas las vistas (dashboard, ranking, fichas, portal docente) usan estas
funciones para que la posicion de un docente sea siempre la misma.
"""

from sqlalchemy.orm import joinedload

from models import db, Evaluacion, CriterioNorma, DocenteSemestre, CRITERIOS_NORMA
from models.evaluacion import (
    umbral_siguiente,
    PESO_ENCUESTA as PESO_ENCUESTA_DEF,
    PESO_NORMAS as PESO_NORMAS_DEF,
    PESO_AUTOEVALUACION as PESO_AUTO_DEF,
)

RECOMENDACIONES = {
    "encuesta": "Revise los comentarios de la encuesta estudiantil: claridad en las clases, "
                "retroalimentacion oportuna y uso de recursos didacticos.",
    "autoevaluacion": "Complete la autoevaluacion de forma reflexiva y dentro del plazo establecido.",
    "reuniones": "Asista a todas las reuniones de junta de docentes convocadas por el DAIS.",
    "silabos": "Entregue silabos y portafolio docente completos dentro del plazo.",
    "notas_config": "Configure el sistema de evaluacion y registre las notas en las fechas programadas.",
    "horas_lectivas": "Cumpla la totalidad de horas lectivas programadas y registre su asistencia.",
    "puntualidad": "Inicie y finalice las sesiones de clase en el horario establecido.",
    "subida_notas_erp": "Registre la asistencia de los estudiantes en el ERP en cada sesion.",
    "designacion_delegados": "Elija y registre oportunamente al delegado de cada asignatura.",
}


def _clave_orden(ev):
    return round(ev.promedio_final, 4)


def calcular_ranking(semestre_id):
    """Ranking del semestre con 'ranking de competicion' (empates comparten puesto: 1,2,2,4).

    Devuelve lista de dicts ordenada por puesto.
    """
    evaluaciones = (
        Evaluacion.query.options(joinedload(Evaluacion.docente))
        .filter(Evaluacion.semestre_id == semestre_id, Evaluacion.promedio_final.isnot(None))
        .all()
    )
    modalidades = dict(
        db.session.query(DocenteSemestre.docente_id, DocenteSemestre.modalidad)
        .filter_by(semestre_id=semestre_id).all()
    )
    evaluaciones.sort(key=lambda e: (-_clave_orden(e), e.docente.apellidos, e.docente.nombres))

    ranking = []
    puesto_anterior, valor_anterior = 0, None
    for i, ev in enumerate(evaluaciones, start=1):
        valor = _clave_orden(ev)
        puesto = puesto_anterior if valor == valor_anterior else i
        puesto_anterior, valor_anterior = puesto, valor
        ranking.append({
            "posicion": puesto,
            "docente": ev.docente,
            "evaluacion": ev,
            "modalidad": modalidades.get(ev.docente_id) or "",
            "encuesta": ev.encuesta,
            "normas": ev.normas,
            "autoevaluacion": ev.autoevaluacion,
            "promedio_final": ev.promedio_final,
            "clasificacion": ev.clasificacion or "",
        })
    return ranking


def mapa_posiciones(semestre_id):
    return {r["docente"].id: r["posicion"] for r in calcular_ranking(semestre_id)}


def promedios_semestre(semestre_id):
    """Promedios de cada componente y de cada criterio de normas en el semestre."""
    campos = [Evaluacion.encuesta, Evaluacion.normas, Evaluacion.autoevaluacion, Evaluacion.promedio_final]
    fila = db.session.query(*[db.func.avg(c) for c in campos]).filter(Evaluacion.semestre_id == semestre_id).one()
    res = {
        "encuesta": fila[0], "normas": fila[1], "autoevaluacion": fila[2], "promedio_final": fila[3],
    }
    cols = [getattr(CriterioNorma, c) for c, _, _ in CRITERIOS_NORMA]
    fila_c = db.session.query(*[db.func.avg(c) for c in cols]).filter(CriterioNorma.semestre_id == semestre_id).one()
    for (campo, _, _), valor in zip(CRITERIOS_NORMA, fila_c):
        res[campo] = valor
    return res


def _prioridad(porcentaje):
    if porcentaje < 70:
        return "alta"
    if porcentaje < 90:
        return "media"
    return "baja"


def analisis_docente(docente_id, semestre_id):
    """Resumen de la evaluacion de un docente: puesto, comparativos, fortalezas y mejoras."""
    ev = Evaluacion.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first()
    if not ev:
        return None
    crit = CriterioNorma.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first()
    ranking = calcular_ranking(semestre_id)
    promedios = promedios_semestre(semestre_id)

    puesto, total = None, len(ranking)
    distancia_puesto = None
    for idx, r in enumerate(ranking):
        if r["docente"].id == docente_id:
            puesto = r["posicion"]
            superiores = [x for x in ranking[:idx] if x["posicion"] < puesto]
            if superiores:
                distancia_puesto = round(superiores[-1]["promedio_final"] - ev.promedio_final, 4)
            break

    mejoras, fortalezas = [], []

    def evaluar(clave, etiqueta, valor, maximo, peso_final, area):
        if valor is None:
            mejoras.append({
                "clave": clave, "etiqueta": etiqueta, "area": area, "valor": None, "maximo": maximo,
                "porcentaje": 0, "brecha": maximo, "impacto": round(maximo * peso_final, 4),
                "prioridad": "alta", "promedio": promedios.get(clave),
                "recomendacion": "No se registro este componente. " + RECOMENDACIONES.get(clave, ""),
            })
            return
        porcentaje = round(valor * 100.0 / maximo, 1) if maximo else 0
        item = {
            "clave": clave, "etiqueta": etiqueta, "area": area, "valor": valor, "maximo": maximo,
            "porcentaje": min(porcentaje, 100), "brecha": round(max(maximo - valor, 0), 4),
            "impacto": round(max(maximo - valor, 0) * peso_final, 4),
            "promedio": promedios.get(clave), "recomendacion": RECOMENDACIONES.get(clave, ""),
        }
        if valor >= maximo - 1e-6:
            fortalezas.append(item)
        else:
            item["prioridad"] = _prioridad(porcentaje)
            mejoras.append(item)

    evaluar("encuesta", "Encuesta estudiantil", ev.encuesta, 10, PESO_ENCUESTA_DEF, "Encuesta")
    evaluar("autoevaluacion", "Autoevaluacion", ev.autoevaluacion, 10, PESO_AUTO_DEF, "Autoevaluacion")
    if crit:
        # Cada punto de un criterio (sobre 100) vale 0.1 en la nota de normas
        for campo, etiqueta, maximo in CRITERIOS_NORMA:
            evaluar(campo, etiqueta, getattr(crit, campo), maximo, PESO_NORMAS_DEF / 10.0, "Normas")
    else:
        evaluar("normas", "Cumplimiento de normas", ev.normas, 10, PESO_NORMAS_DEF, "Normas")

    mejoras.sort(key=lambda m: -m["impacto"])
    for m in mejoras:
        m.setdefault("prioridad", "alta")

    siguiente = umbral_siguiente(ev.promedio_final)
    return {
        "evaluacion": ev,
        "criterios": crit,
        "puesto": puesto,
        "total": total,
        "percentil": round((total - puesto) * 100.0 / (total - 1)) if puesto and total > 1 else None,
        "promedios": promedios,
        "mejoras": mejoras,
        "fortalezas": fortalezas,
        "siguiente_clasificacion": siguiente[0] if siguiente else None,
        "falta_siguiente": round(siguiente[1] - ev.promedio_final, 4) if siguiente and ev.promedio_final is not None else None,
        "distancia_puesto": distancia_puesto,
        "max_alcanzable": round(min(10, (ev.promedio_final or 0) + sum(m["impacto"] for m in mejoras)), 4),
    }


def historial_docente(docente_id):
    """Evaluaciones del docente en todos los semestres, con su puesto en cada uno."""
    evaluaciones = (
        Evaluacion.query.options(joinedload(Evaluacion.semestre))
        .filter_by(docente_id=docente_id).all()
    )
    evaluaciones.sort(key=lambda e: e.semestre.orden)
    salida = []
    for ev in evaluaciones:
        posiciones = mapa_posiciones(ev.semestre_id) if ev.promedio_final is not None else {}
        salida.append({
            "semestre": ev.semestre,
            "evaluacion": ev,
            "posicion": posiciones.get(docente_id),
            "total": len(posiciones),
        })
    return salida
