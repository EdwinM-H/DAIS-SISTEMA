"""Propuesta automatica de asesores, dictaminantes, dirimentes y replicantes.

1. Descarta a quien no puede ser designado (Art. 73, 95, 117 y cupo del DAIS).
2. Puntua afinidad (tema > linea > area, publicaciones), carga y cumplimiento de plazos.
3. Los elegidos se ordenan por prelacion (Art. 71/97): categoria, antiguedad UAC, colegiatura, experiencia.
"""

import re
import unicodedata

from models import db, Docente, Investigacion, Tesis, TesisMiembro, Dictamen
from models.tesis import ACTIVOS, ETAPAS_CERRADAS
from services import parametros

ROLES_JURADO = ("dictaminante", "dirimente", "replicante")
STOPWORDS = {
    "sistema", "sistemas", "para", "como", "entre", "sobre", "desde", "hasta", "mediante", "basado", "basada",
    "aplicacion", "propuesta", "desarrollo", "implementacion", "universidad", "andina", "cusco", "region",
    "empresa", "caso", "estudio", "analisis", "diseno", "modelo", "mejora", "gestion", "periodo", "nivel",
}
PUNTOS = {"tema": 40, "linea": 25, "area": 10, "publicaciones": 15, "carga": 20, "cumplimiento": 10}


def _tokens(texto):
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return {w for w in re.findall(r"[a-z]{5,}", t) if w not in STOPWORDS}


def _carga():
    """{docente_id: (jurado_activo, asesorias_activas)} en tesis no cerradas."""
    filas = (
        db.session.query(TesisMiembro.docente_id, TesisMiembro.rol, db.func.count(TesisMiembro.id))
        .join(Tesis)
        .filter(TesisMiembro.estado_designacion.in_(ACTIVOS), Tesis.etapa.notin_(ETAPAS_CERRADAS))
        .group_by(TesisMiembro.docente_id, TesisMiembro.rol).all()
    )
    carga = {}
    for did, rol, n in filas:
        j, a = carga.get(did, (0, 0))
        carga[did] = (j + n, a) if rol in ROLES_JURADO else (j, a + n)
    return carga


def _cumplimiento():
    """{docente_id: proporcion de dictamenes emitidos dentro del plazo}."""
    datos = {}
    for d in Dictamen.query.filter(Dictamen.emitido_en.isnot(None)).all():
        a_tiempo, total = datos.get(d.miembro.docente_id, (0, 0))
        datos[d.miembro.docente_id] = (a_tiempo + (d.emitido_en.date() <= d.limite), total + 1)
    return {k: v[0] / v[1] for k, v in datos.items() if v[1]}


def _lineas_y_areas(docente):
    lineas = {l.id for l in docente.lineas} | {t.linea_id for t in docente.temas}
    if docente.linea_principal_id:
        lineas.add(docente.linea_principal_id)
    areas = {l.area_id for l in docente.lineas} | {t.linea.area_id for t in docente.temas}
    if docente.linea_principal:
        areas.add(docente.linea_principal.area_id)
    return lineas, areas


def candidatos(tesis, rol):
    """Devuelve (elegibles, descartados). elegibles: lista de dicts ordenada por puntaje."""
    es_jurado = rol in ROLES_JURADO
    cupo = parametros.obtener("cupo_dictamenes" if es_jurado else "cupo_asesorias")
    carga = _carga()
    cumplimiento = _cumplimiento()
    en_tesis = {m.docente_id for m in tesis.miembros}

    temas_tesis = {t.id for t in tesis.temas}
    lineas_tesis = {t.linea_id for t in tesis.temas} | ({tesis.linea_id} if tesis.linea_id else set())
    areas_tesis = {t.linea.area_id for t in tesis.temas} | ({tesis.area_id} if tesis.area_id else set())
    if tesis.linea:
        areas_tesis.add(tesis.linea.area_id)
    palabras = _tokens(f"{tesis.titulo} {tesis.palabras_clave or ''}")

    investigaciones = {}
    for inv in Investigacion.query.filter_by(estado_validacion="validado").all():
        investigaciones.setdefault(inv.docente_id, []).append(inv)

    elegibles, descartados = [], []
    for d in Docente.query.order_by(Docente.apellidos).all():
        motivo = None
        jurado, asesorias = carga.get(d.id, (0, 0))
        actual = jurado if es_jurado else asesorias
        if d.estado != "activo":
            motivo = "Docente inactivo"
        elif d.es_autoridad:
            motivo = f"Autoridad ({d.cargo_autoridad or 'cargo directivo'}) - Art. 73"
        elif d.de_licencia():
            motivo = "De licencia"
        elif d.id in en_tesis:
            motivo = "Ya participa (o participó) en esta tesis"
        elif actual >= cupo:
            motivo = f"Cupo completo ({actual}/{cupo})"
        if motivo:
            descartados.append({"docente": d, "motivo": motivo})
            continue

        puntos, motivos = {}, []
        lineas_doc, areas_doc = _lineas_y_areas(d)
        temas_comunes = [t for t in d.temas if t.id in temas_tesis]
        if temas_comunes:
            puntos["afinidad"] = PUNTOS["tema"]
            motivos.append("Mismo tema: " + ", ".join(t.nombre for t in temas_comunes[:2]))
        elif lineas_doc & lineas_tesis:
            puntos["afinidad"] = PUNTOS["linea"]
            motivos.append("Misma línea de investigación")
        elif areas_doc & areas_tesis:
            puntos["afinidad"] = PUNTOS["area"]
            motivos.append("Misma área")
        else:
            puntos["afinidad"] = 0
            if not d.temas and not d.lineas:
                motivos.append("Sin líneas registradas en su perfil")

        relacionadas = [i for i in investigaciones.get(d.id, []) if len(_tokens(i.titulo) & palabras) >= 2]
        puntos["publicaciones"] = min(len(relacionadas) * 5, PUNTOS["publicaciones"])
        if relacionadas:
            motivos.append(f"{len(relacionadas)} publicación(es) relacionada(s)")

        puntos["carga"] = round(PUNTOS["carga"] * (1 - actual / cupo), 1) if cupo else 0
        motivos.append(f"{actual} {'dictamen(es)' if es_jurado else 'asesoría(s)'} activo(s)")

        if d.id in cumplimiento:
            puntos["cumplimiento"] = round(PUNTOS["cumplimiento"] * cumplimiento[d.id], 1)
            motivos.append(f"Cumple plazos en {round(cumplimiento[d.id] * 100)}%")
        else:
            puntos["cumplimiento"] = PUNTOS["cumplimiento"] / 2

        if d.faltantes_prelacion():
            motivos.append("Prelación incompleta: falta " + ", ".join(d.faltantes_prelacion()))

        elegibles.append({
            "docente": d,
            "puntaje": round(sum(puntos.values()), 1),
            "puntos": puntos,
            "motivos": motivos,
            "carga": actual,
            "cupo": cupo,
            "categoria": d.categoria_docente or "-",
        })

    elegibles.sort(key=lambda c: (-c["puntaje"], c["docente"].clave_prelacion))
    return elegibles, descartados


def proponer(tesis, rol, cantidad):
    """Los 'cantidad' mejores candidatos, ordenados por prelacion entre ellos."""
    elegibles, _ = candidatos(tesis, rol)
    elegidos = elegibles[:cantidad]
    return sorted(elegidos, key=lambda c: c["docente"].clave_prelacion)


def reordenar_prelacion(tesis):
    """Numera a los dictaminantes activos segun prelacion (1 = mayor prelacion)."""
    for i, m in enumerate(sorted(tesis.activos("dictaminante"), key=lambda m: m.docente.clave_prelacion), start=1):
        m.orden_prelacion = i
