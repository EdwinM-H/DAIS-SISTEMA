"""Parametros del proceso de tesis editables por la Direccion (valores por defecto: Reglamento Marco)."""

from models import db, Parametro

PARAMETROS = {
    # clave: (valor por defecto, descripcion, articulo)
    "dictaminantes_proyecto": (2, "Dictaminantes del proyecto de tesis", "Art. 70"),
    "dictaminantes_tesis": (3, "Dictaminantes de la tesis (los del proyecto + nuevos)", "Art. 93, 96"),
    "dictaminantes_suficiencia": (3, "Dictaminantes del trabajo de suficiencia profesional", "Art. 166"),
    "plazo_dictamen_proyecto": (10, "Días hábiles para dictaminar el proyecto", "Art. 75"),
    "plazo_dictamen_tesis": (15, "Días hábiles para dictaminar la tesis", "Art. 100, 167"),
    "plazo_revision_subsanacion": (7, "Días hábiles para revisar el levantamiento de observaciones", "Art. 103"),
    "plazo_subsanar_proyecto": (10, "Días hábiles del tesista para subsanar el proyecto", "Art. 78"),
    "plazo_subsanar_tesis": (15, "Días hábiles del tesista para subsanar la tesis", "Art. 103"),
    "plazo_observaciones_sustentacion": (10, "Días hábiles para levantar observaciones de sustentación", "Art. 132"),
    "dias_reemplazo_sin_dictamen": (30, "Días calendario sin dictamen para proponer reemplazo", "Art. 84, 110"),
    "rondas_maximas_observacion": (3, "Rondas de observaciones nuevas antes de sugerir reemplazo", "Art. 110 d"),
    "plazo_aceptar_designacion": (3, "Días hábiles para aceptar la designación o declarar impedimento", "Acuerdo DAIS"),
    "cupo_dictamenes": (5, "Máximo de dictámenes/jurados activos por docente", "Acuerdo DAIS"),
    "cupo_asesorias": (5, "Máximo de asesorías activas por docente", "Acuerdo DAIS"),
    "permite_coasesor": (0, "Permitir coasesor (1 = sí, 0 = no; lo define el reglamento de Facultad)", "Art. 61"),
}


def obtener(clave):
    defecto = PARAMETROS[clave][0]
    p = db.session.get(Parametro, clave)
    if not p:
        return defecto
    try:
        return int(p.valor)
    except ValueError:
        return defecto


def todos():
    return [
        {"clave": k, "valor": obtener(k), "defecto": v[0], "descripcion": v[1], "articulo": v[2]}
        for k, v in PARAMETROS.items()
    ]


def guardar(clave, valor):
    if clave not in PARAMETROS:
        raise KeyError(clave)
    valor = int(valor)
    if valor < 0 or valor > 365:
        raise ValueError("Valor fuera de rango")
    p = db.session.get(Parametro, clave)
    if p:
        p.valor = str(valor)
    else:
        db.session.add(Parametro(clave=clave, valor=str(valor)))
