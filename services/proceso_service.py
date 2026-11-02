"""Proceso de evaluacion por semestre: avance de la carga de datos y calculo de resultados.

Flujo: docentes -> encuesta -> criterios de normas -> autoevaluacion -> calcular resultados.
Los promedios, clasificaciones y el ranking solo existen despues de calcular.
"""

from datetime import datetime

from sqlalchemy.orm import joinedload

from models import db, DocenteSemestre, Evaluacion, CriterioNorma, Importacion, CRITERIOS_NORMA
from models.evaluacion import clasificar

CAMPOS = [c for c, _, _ in CRITERIOS_NORMA]


class ProcesoError(Exception):
    pass


def _normas_completas(ev, crit):
    if crit and all(getattr(crit, c) is not None for c in CAMPOS):
        return True
    return ev is not None and ev.normas is not None and not (crit and any(getattr(crit, c) is not None for c in CAMPOS))


def estado_proceso(semestre):
    """Avance de cada paso del proceso para el semestre."""
    participaciones = (
        DocenteSemestre.query.options(joinedload(DocenteSemestre.docente))
        .filter_by(semestre_id=semestre.id).all()
    )
    docentes = sorted((p.docente for p in participaciones), key=lambda d: (d.apellidos, d.nombres))
    evs = {e.docente_id: e for e in Evaluacion.query.filter_by(semestre_id=semestre.id)}
    crits = {c.docente_id: c for c in CriterioNorma.query.filter_by(semestre_id=semestre.id)}

    faltan = {"encuesta": [], "autoevaluacion": [], "normas": [], **{c: [] for c in CAMPOS}}
    completos, filas = 0, []
    for d in docentes:
        ev, crit = evs.get(d.id), crits.get(d.id)
        enc = ev is not None and ev.encuesta is not None
        auto = ev is not None and ev.autoevaluacion is not None
        criterios = {c: crit is not None and getattr(crit, c) is not None for c in CAMPOS}
        normas = _normas_completas(ev, crit)
        if not enc:
            faltan["encuesta"].append(d)
        if not auto:
            faltan["autoevaluacion"].append(d)
        if not normas:
            faltan["normas"].append(d)
        for c, ok in criterios.items():
            if not ok:
                faltan[c].append(d)
        completo = enc and auto and normas
        completos += completo
        filas.append({"docente": d, "evaluacion": ev, "criterios": crit, "encuesta": enc, "autoevaluacion": auto,
                      "normas": normas, "detalle_criterios": criterios, "completo": completo})

    ultimas = {}
    for imp in Importacion.query.filter_by(semestre_id=semestre.id).order_by(Importacion.fecha_importacion).all():
        ultimas[imp.tipo] = imp

    total = len(docentes)
    pasos = {
        "docentes": total,
        "encuesta": total - len(faltan["encuesta"]),
        "normas": total - len(faltan["normas"]),
        "autoevaluacion": total - len(faltan["autoevaluacion"]),
        **{c: total - len(faltan[c]) for c in CAMPOS},
    }
    return {
        "semestre": semestre,
        "total": total,
        "pasos": pasos,
        "faltan": faltan,
        "completos": completos,
        "incompletos": total - completos,
        "listo": total > 0 and completos == total,
        "filas": filas,
        "ultimas": ultimas,
        "estado_resultados": semestre.estado_resultados,
    }


def calcular_resultados(semestre, excluir_incompletos=False):
    """Calcula normas, promedio final y clasificacion de cada docente del semestre."""
    estado = estado_proceso(semestre)
    if estado["total"] == 0:
        raise ProcesoError("No hay docentes registrados en el semestre.")
    if estado["incompletos"] and not excluir_incompletos:
        raise ProcesoError(
            f"Faltan datos de {estado['incompletos']} docente(s). Complete la informacion o marque "
            "'calcular excluyendo a los docentes incompletos'."
        )
    if estado["completos"] == 0:
        raise ProcesoError("Ningun docente tiene todas las dimensiones completas.")

    calculados = 0
    for fila in estado["filas"]:
        ev, crit = fila["evaluacion"], fila["criterios"]
        if not fila["completo"]:
            if ev:
                ev.promedio_final = None
                ev.clasificacion = None
            continue
        if crit and all(getattr(crit, c) is not None for c in CAMPOS):
            crit.calcular_subtotal()
            ev.normas = crit.nota_normas
        ev.calcular_promedio()
        ev.clasificacion = clasificar(ev.promedio_final)
        calculados += 1

    semestre.resultados_vigentes = True
    semestre.fecha_calculo = datetime.now()
    db.session.commit()
    return {"calculados": calculados, "excluidos": estado["incompletos"]}


def recalcular_docente(ev, crit, semestre):
    """Tras una correccion manual: si el semestre ya fue calculado, actualiza solo a ese docente."""
    if crit and all(getattr(crit, c) is not None for c in CAMPOS):
        crit.calcular_subtotal()
        ev.normas = crit.nota_normas
    if semestre.fecha_calculo and None not in (ev.encuesta, ev.normas, ev.autoevaluacion):
        ev.calcular_promedio()
        ev.clasificacion = clasificar(ev.promedio_final)
    else:
        ev.promedio_final = None
        ev.clasificacion = None
