"""Importacion de datos desde Excel/CSV.

Flujo en dos pasos para todos los tipos:
    1. analizar_*(ruta)  -> lee y valida SIN escribir en la base de datos (vista previa)
    2. importar_*(ruta, semestre_id, usuario_id) -> persiste en una sola transaccion

Escala oficial de todas las notas: 0 a 10.
"""

import csv
import json
import os
import unicodedata

import openpyxl

from models import (
    db, Docente, DocenteSemestre, Evaluacion, Importacion, Semestre, CriterioNorma,
    Capacitacion, Investigacion, CRITERIOS_NORMA, clasificar,
)
from models.docente import titulo

NOTA_MAX = 10.0
PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "VON", "VAN", "MC"}
PALABRAS_TOTALES = ("promedio", "total", "general")


# ======================================================================
# Utilidades de lectura
# ======================================================================
def clave(texto):
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.lower().split())


def a_numero(valor):
    """Convierte '8,24', '8.24', 10, '1.234,5' a float. Devuelve None si no es numero."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "").replace(" ", "")
    if not texto or texto.lower() in ("nan", "none", "-", "n/a"):
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def texto_celda(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def dividir_nombre(completo):
    """'CUBA DEL CASTILLO MARIA YORNET' -> ('Maria Yornet', 'Cuba Del Castillo').

    Formato institucional: APELLIDOS (dos, con particulas) seguidos de NOMBRES.
    """
    tokens = completo.split()
    grupos, actual = [], []
    for tok in tokens:
        actual.append(tok)
        if tok.upper() not in PARTICULAS:
            grupos.append(" ".join(actual))
            actual = []
    if actual:
        grupos.append(" ".join(actual))
    if len(grupos) <= 1:
        return titulo(completo), ""
    n_apellidos = 2 if len(grupos) >= 3 else 1
    apellidos = " ".join(grupos[:n_apellidos])
    nombres = " ".join(grupos[n_apellidos:])
    return titulo(nombres), titulo(apellidos)


PALABRAS_ENCABEZADO = ("apellido", "nombre", "codigo", "docente")


def letra_columna(i):
    """0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    letras = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _detectar_fila_titulos(filas):
    for n, fila in enumerate(filas[:25], start=1):
        claves = [clave(v) for v in fila]
        if any(any(p in k for p in PALABRAS_ENCABEZADO) for k in claves):
            return n
    for n, fila in enumerate(filas, start=1):
        if any(v not in (None, "") for v in fila):
            return n
    return 1


def leer_hoja(ruta, hoja=None, fila_titulos=None):
    """Lee una hoja de un .xlsx (o un .csv) para importar.

    Devuelve dict con:
      hojas, hoja, fila_titulos (1-based), cab (titulo propio de cada columna),
      grupos (titulo del grupo superior, p. ej. 'ENCUESTA ESTUDIANTES'),
      etiquetas ('D · ENCUESTA ESTUDIANTES › NOTA /10') y filas [(numero_fila, valores)].
    """
    if ruta.lower().endswith(".csv"):
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            lineas = f.read(8192).splitlines()
            f.seek(0)
            # Excel en espanol exporta con ';' y coma decimal: se elige el separador presente en mas lineas
            separador = max((";", "\t", ","), key=lambda d: sum(1 for ln in lineas if d in ln))
            todas = [list(r) for r in csv.reader(f, delimiter=separador)]
        hojas, hoja = ["CSV"], "CSV"
    else:
        wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        hojas = list(wb.sheetnames)
        hoja = hoja if hoja in hojas else hojas[0]
        todas = [list(r) for r in wb[hoja].iter_rows(values_only=True)]
        wb.close()

    ancho = max((len(f) for f in todas), default=0)
    todas = [f + [None] * (ancho - len(f)) for f in todas]
    if not todas:
        return {"hojas": hojas, "hoja": hoja, "fila_titulos": 1, "cab": [], "grupos": [], "etiquetas": [], "filas": []}
    if not fila_titulos or not 1 <= int(fila_titulos) <= len(todas):
        fila_titulos = _detectar_fila_titulos(todas)
    fila_titulos = int(fila_titulos)

    cab = [texto_celda(v) for v in todas[fila_titulos - 1]]
    # Titulos de grupo (celdas combinadas de las filas superiores, propagadas a la derecha)
    grupos = [""] * ancho
    for fila in todas[max(0, fila_titulos - 3):fila_titulos - 1]:
        actual = ""
        for i, v in enumerate(fila):
            t = texto_celda(v)
            if t:
                actual = t
            k = clave(actual)
            if actual and not k.startswith("peso") and "=" not in actual and not grupos[i]:
                grupos[i] = actual
    etiquetas = []
    for i in range(ancho):
        partes = [p for p in (grupos[i], cab[i]) if p]
        etiquetas.append(f"{letra_columna(i)} · " + (" › ".join(partes) if partes else "(sin titulo)"))

    filas = [
        (n, f) for n, f in enumerate(todas[fila_titulos:], start=fila_titulos + 1)
        if any(v not in (None, "") for v in f)
    ]
    return {"hojas": hojas, "hoja": hoja, "fila_titulos": fila_titulos, "cab": cab, "grupos": grupos,
            "etiquetas": etiquetas, "filas": filas}


def buscar_columna(cabeceras, *candidatas, excluir=()):
    claves = [clave(c) for c in cabeceras]
    for cand in candidatas:
        for i, c in enumerate(claves):
            if c == cand:
                return i
    for cand in candidatas:
        for i, c in enumerate(claves):
            if cand in c and not any(x in c for x in excluir):
                return i
    return None


def _obtener_o_crear_docente(nombre_completo, resultado, nombres=None, apellidos=None, codigo=None):
    docente = None
    if codigo:
        docente = Docente.query.filter_by(codigo=codigo).first()
    if not docente:
        docente = Docente.buscar_por_nombre(nombre_completo)
    if docente:
        return docente, False
    if nombres is None or apellidos is None:
        nombres, apellidos = dividir_nombre(nombre_completo)
    docente = Docente(
        codigo=codigo or Docente.siguiente_codigo(),
        nombres=nombres or "Sin nombre",
        apellidos=apellidos or "Sin apellido",
    )
    db.session.add(docente)
    db.session.flush()
    resultado["nuevos_docentes"] = resultado.get("nuevos_docentes", 0) + 1
    return docente, True


def _asegurar_participacion(docente_id, semestre_id, modalidad=None):
    part = DocenteSemestre.query.filter_by(docente_id=docente_id, semestre_id=semestre_id).first()
    if not part:
        part = DocenteSemestre(docente_id=docente_id, semestre_id=semestre_id)
        db.session.add(part)
    if modalidad:
        part.modalidad = modalidad
    return part


def _resultado_base():
    return {
        "encontrados": 0, "importados": 0, "actualizados": 0, "rechazados": 0,
        "nuevos_docentes": 0, "capacitaciones": 0, "investigaciones": 0,
        "errores": [], "advertencias": [],
    }


def _registrar_importacion(tipo, ruta, semestre_id, usuario_id, res):
    imp = Importacion(
        usuario_id=usuario_id,
        semestre_id=semestre_id,
        tipo=tipo,
        nombre_archivo=os.path.basename(ruta).split("_", 1)[-1],
        registros_encontrados=res["encontrados"],
        registros_importados=res["importados"],
        registros_actualizados=res["actualizados"],
        registros_rechazados=res["rechazados"],
        capacitaciones_importadas=res["capacitaciones"],
        investigaciones_importadas=res["investigaciones"],
        errores=(json.dumps(res["errores"] + res["advertencias"], ensure_ascii=False)
                 if (res["errores"] or res["advertencias"]) else None),
    )
    db.session.add(imp)
    db.session.flush()
    return imp


def _confirmar(res):
    try:
        db.session.commit()
    except Exception as exc:  # pragma: no cover - errores de integridad inesperados
        db.session.rollback()
        res["errores"].append(f"No se pudieron guardar los datos: {exc}")
        res["importados"] = res["actualizados"] = 0
    return res


# ======================================================================
# FICHA DE EVALUACION INTEGRAL (Excel oficial con cabeceras agrupadas)
# ======================================================================
ETIQUETAS_CAMPOS_FICHA = {
    "nombre_completo": "Apellidos y Nombres",
    "modalidad": "Modalidad",
    "encuesta": "Encuesta estudiantil (/10)",
    "reuniones": "Reuniones (15)",
    "silabos": "Silabos (20)",
    "notas_config": "Notas/Config (15)",
    "horas_lectivas": "Hrs Lectivas (20)",
    "puntualidad": "Puntualidad (15)",
    "subida_notas_erp": "ERP (10)",
    "designacion_delegados": "Delegado (5)",
    "subtotal_normas": "Subtotal normas (/100)",
    "normas": "Nota normas (/10)",
    "autoevaluacion": "Autoevaluacion (/10)",
    "promedio_final": "Promedio final (/10)",
    "clasificacion": "Clasificacion",
}
CAMPOS_CRITERIO = [c for c, _, _ in CRITERIOS_NORMA]


def _hoja(wb, *palabras):
    for nombre in wb.sheetnames:
        n = clave(nombre)
        if all(p in n for p in palabras):
            return wb[nombre]
    return None


def _hoja_ficha(wb):
    ws = _hoja(wb, "evaluac", "integral") or _hoja(wb, "evaluac", "docente")
    if ws:
        return ws
    for ws in wb.worksheets:
        if _fila_encabezado(ws)[0]:
            return ws
    return None


def _fila_encabezado(ws, max_filas=20):
    for r, fila in enumerate(ws.iter_rows(min_row=1, max_row=max_filas, values_only=True), start=1):
        for c, v in enumerate(fila, start=1):
            k = clave(v)
            if "apellido" in k and "nombre" in k:
                return r, c
    return None, None


def _mapear_columnas_ficha(ws, fila_cab, col_nombre):
    """Asigna a cada columna un campo usando las cabeceras de grupo (ENCUESTA, NORMAS...)."""
    filas_sup = list(ws.iter_rows(min_row=1, max_row=fila_cab, values_only=True))
    cab = filas_sup[-1]
    ancho = len(cab)

    grupos = {}
    for fila in filas_sup[:-1]:
        actual = None
        encontrados = False
        for c in range(ancho):
            k = clave(fila[c] if c < len(fila) else None)
            g = None
            if "encuesta" in k:
                g = "encuesta"
            elif "norma" in k:
                g = "normas"
            elif "autoevaluac" in k:
                g = "autoevaluacion"
            elif "resultado" in k:
                g = "resultado"
            elif k.startswith("dato"):
                g = "datos"
            if g:
                actual, encontrados = g, True
            if actual:
                grupos[c + 1] = actual
        if encontrados:
            break

    mapeo = {}
    for c in range(1, ancho + 1):
        h = clave(cab[c - 1])
        if not h:
            continue
        g = grupos.get(c, "datos")
        if c == col_nombre:
            mapeo[c] = "nombre_completo"
        elif "modalidad" in h:
            mapeo[c] = "modalidad"
        elif g == "encuesta":
            mapeo[c] = "encuesta"
        elif g == "normas":
            if "reunion" in h:
                mapeo[c] = "reuniones"
            elif "silabo" in h:
                mapeo[c] = "silabos"
            elif "config" in h:
                mapeo[c] = "notas_config"
            elif "hrs" in h or "hora" in h or "lect" in h:
                mapeo[c] = "horas_lectivas"
            elif "puntual" in h:
                mapeo[c] = "puntualidad"
            elif "erp" in h:
                mapeo[c] = "subida_notas_erp"
            elif "delegado" in h:
                mapeo[c] = "designacion_delegados"
            elif "subtotal" in h:
                mapeo[c] = "subtotal_normas"
            elif "nota" in h or "/10" in h:
                mapeo[c] = "normas"
        elif g == "autoevaluacion":
            mapeo.setdefault(c, "autoevaluacion")
        elif g == "resultado":
            if "clasificac" in h:
                mapeo[c] = "clasificacion"
            elif "promedio" in h or "final" in h:
                mapeo[c] = "promedio_final"
        else:
            if "promedio" in h and "final" in h:
                mapeo[c] = "promedio_final"
            elif "clasificac" in h:
                mapeo[c] = "clasificacion"
    # Una sola columna por campo (la primera encontrada)
    vistos, limpio = set(), {}
    for c in sorted(mapeo):
        if mapeo[c] not in vistos:
            limpio[c] = mapeo[c]
            vistos.add(mapeo[c])
    return limpio


def _leer_produccion(wb, palabra_hoja, col_titulo_cands):
    """Lee las hojas INVESTIGACIONES / CAPACITACIONES (filas sin nombre heredan el docente anterior)."""
    ws = _hoja(wb, palabra_hoja)
    if ws is None:
        return []
    fila_cab, col_nombre = _fila_encabezado(ws)
    if not fila_cab:
        return []
    cab = [clave(v) for v in next(ws.iter_rows(min_row=fila_cab, max_row=fila_cab, values_only=True))]
    col_titulo = next(
        (i for i, h in enumerate(cab) if i != col_nombre - 1 and any(k in h for k in col_titulo_cands)), None
    )
    col_anio = next((i for i, h in enumerate(cab) if h in ("ano", "anio") or h.startswith("ano ")), None)
    col_tipo = next((i for i, h in enumerate(cab) if h.startswith("tipo")), None)
    col_subtipo = next((i for i, h in enumerate(cab) if h.startswith("subtipo")), None)
    col_horas = next((i for i, h in enumerate(cab) if "hora" in h), None)
    if col_titulo is None:
        return []

    salida, docente_actual = [], None
    for fila in ws.iter_rows(min_row=fila_cab + 1, values_only=True):
        nombre = texto_celda(fila[col_nombre - 1]) if len(fila) >= col_nombre else ""
        if nombre:
            docente_actual = nombre
        titulo_txt = texto_celda(fila[col_titulo]) if col_titulo < len(fila) else ""
        if not docente_actual or not titulo_txt or clave(titulo_txt) in ("no tiene", "no registra", "ninguno", "-"):
            continue
        anio = a_numero(fila[col_anio]) if col_anio is not None and col_anio < len(fila) else None
        salida.append({
            "docente": docente_actual,
            "titulo": titulo_txt[:600],
            "anio": int(anio) if anio and 1950 <= anio <= 2100 else None,
            "tipo": texto_celda(fila[col_tipo]) if col_tipo is not None and col_tipo < len(fila) else "",
            "subtipo": texto_celda(fila[col_subtipo]) if col_subtipo is not None and col_subtipo < len(fila) else "",
            "horas": a_numero(fila[col_horas]) if col_horas is not None and col_horas < len(fila) else None,
        })
    return salida


def analizar_ficha_integral(ruta):
    """Lee y valida la Ficha Integral sin tocar la base de datos."""
    out = {
        "error": None, "hoja": None, "fila_encabezado": None,
        "campos_detectados": [], "campos_faltantes": [],
        "registros": [], "rechazados": [], "advertencias": [],
        "capacitaciones": [], "investigaciones": [],
    }
    try:
        wb = openpyxl.load_workbook(ruta, data_only=True)
    except Exception as exc:
        out["error"] = f"No se pudo abrir el archivo: {exc}"
        return out

    ws = _hoja_ficha(wb)
    if ws is None:
        out["error"] = "No se encontro la hoja de evaluacion integral (con la columna 'APELLIDOS Y NOMBRES')."
        return out
    fila_cab, col_nombre = _fila_encabezado(ws)
    mapeo = _mapear_columnas_ficha(ws, fila_cab, col_nombre)
    out["hoja"], out["fila_encabezado"] = ws.title, fila_cab

    campos = set(mapeo.values())
    out["campos_detectados"] = [ETIQUETAS_CAMPOS_FICHA[c] for c in ETIQUETAS_CAMPOS_FICHA if c in campos]
    out["campos_faltantes"] = [ETIQUETAS_CAMPOS_FICHA[c] for c in ETIQUETAS_CAMPOS_FICHA if c not in campos]
    if not campos & {"encuesta", "normas", "autoevaluacion", "promedio_final"}:
        out["error"] = "No se encontro ninguna columna de notas (encuesta, normas, autoevaluacion o promedio)."
        return out

    vistos = set()
    for fila in ws.iter_rows(min_row=fila_cab + 1, values_only=False):
        num_fila = fila[0].row
        valores = {}
        for col, campo in mapeo.items():
            v = fila[col - 1].value if col - 1 < len(fila) else None
            if campo in ("nombre_completo", "modalidad", "clasificacion"):
                valores[campo] = texto_celda(v)
            else:
                valores[campo] = a_numero(v)
        nombre = valores.get("nombre_completo")
        if not nombre or any(p in nombre.lower() for p in PALABRAS_TOTALES):
            continue

        errores = []
        for campo in ("encuesta", "normas", "autoevaluacion", "promedio_final"):
            v = valores.get(campo)
            if v is not None and not 0 <= v <= NOTA_MAX:
                errores.append(f"{ETIQUETAS_CAMPOS_FICHA[campo]} fuera de rango (0-10): {v}")
        for campo in CAMPOS_CRITERIO:
            v = valores.get(campo)
            if v is not None and v < 0:
                errores.append(f"{ETIQUETAS_CAMPOS_FICHA[campo]} negativo: {v}")
        if valores.get("subtotal_normas") is not None and not 0 <= valores["subtotal_normas"] <= 100:
            errores.append(f"Subtotal de normas fuera de rango (0-100): {valores['subtotal_normas']}")

        clave_nombre = clave(nombre)
        if clave_nombre in vistos:
            errores.append("Docente repetido en el archivo")
        vistos.add(clave_nombre)

        if errores:
            out["rechazados"].append({"fila": num_fila, "nombre": nombre, "errores": errores})
            continue

        # Completar normas desde los criterios cuando falte la nota /10
        criterios = [valores.get(c) for c in CAMPOS_CRITERIO if valores.get(c) is not None]
        if valores.get("subtotal_normas") is None and criterios:
            valores["subtotal_normas"] = round(min(sum(criterios), 100), 4)
        if valores.get("normas") is None and valores.get("subtotal_normas") is not None:
            valores["normas"] = round(valores["subtotal_normas"] / 10, 4)

        comps = [valores.get(c) for c in ("encuesta", "normas", "autoevaluacion")]
        calculado = None
        if None not in comps:
            calculado = round(comps[0] * 0.4 + comps[1] * 0.4 + comps[2] * 0.2, 4)
        oficial = valores.get("promedio_final")
        if oficial is not None and calculado is not None and abs(oficial - calculado) > 0.01:
            out["advertencias"].append(
                f"Fila {num_fila} ({nombre}): el promedio del Excel ({oficial:.4f}) difiere del calculado "
                f"({calculado:.4f}). Se conserva el valor oficial."
            )
        if oficial is None:
            valores["promedio_final"] = calculado
        if not valores.get("clasificacion"):
            valores["clasificacion"] = clasificar(valores.get("promedio_final")) or ""
        valores["fila"] = num_fila
        out["registros"].append(valores)

    out["investigaciones"] = _leer_produccion(wb, "investigac", ("proyecto", "titulo", "nombre"))
    out["capacitaciones"] = _leer_produccion(wb, "capacitac", ("capacitac", "nombre", "curso"))
    wb.close()
    if not out["registros"] and not out["rechazados"]:
        out["error"] = "La hoja no contiene registros de docentes."
    return out


def _existe_capacitacion(docente_id, nombre, anio):
    return any(
        clave(c.nombre) == clave(nombre) and c.anio == anio
        for c in Capacitacion.query.filter_by(docente_id=docente_id, anio=anio).all()
    )


def _existe_investigacion(docente_id, titulo_txt, anio):
    return any(
        clave(i.titulo) == clave(titulo_txt) and i.anio == anio
        for i in Investigacion.query.filter_by(docente_id=docente_id, anio=anio).all()
    )


def importar_ficha_integral(ruta, semestre_id, usuario_id):
    res = _resultado_base()
    analisis = analizar_ficha_integral(ruta)
    if analisis["error"]:
        res["errores"].append(analisis["error"])
        return res
    semestre = db.session.get(Semestre, semestre_id)
    if not semestre:
        res["errores"].append("Semestre no encontrado.")
        return res

    res["encontrados"] = len(analisis["registros"]) + len(analisis["rechazados"])
    res["rechazados"] = len(analisis["rechazados"])
    for r in analisis["rechazados"]:
        res["errores"].append(f"Fila {r['fila']} ({r['nombre']}): " + "; ".join(r["errores"]))
    res["advertencias"].extend(analisis["advertencias"])

    imp = _registrar_importacion("ficha_integral", ruta, semestre_id, usuario_id, res)
    docentes_por_nombre = {}

    for reg in analisis["registros"]:
        docente, _ = _obtener_o_crear_docente(reg["nombre_completo"], res)
        docentes_por_nombre[clave(reg["nombre_completo"])] = docente
        _asegurar_participacion(docente.id, semestre_id, reg.get("modalidad") or None)

        ev = Evaluacion.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
        nueva = ev is None
        if nueva:
            ev = Evaluacion(docente_id=docente.id, semestre_id=semestre_id)
            db.session.add(ev)
        for campo in ("encuesta", "normas", "autoevaluacion", "promedio_final"):
            if reg.get(campo) is not None:
                setattr(ev, campo, reg[campo])
        ev.clasificacion = reg.get("clasificacion") or clasificar(ev.promedio_final)
        ev.importacion_id = imp.id
        ev.editado_manual = False

        if any(reg.get(c) is not None for c in CAMPOS_CRITERIO + ["subtotal_normas"]):
            crit = CriterioNorma.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
            if not crit:
                crit = CriterioNorma(docente_id=docente.id, semestre_id=semestre_id)
                db.session.add(crit)
            for c in CAMPOS_CRITERIO + ["subtotal_normas"]:
                if reg.get(c) is not None:
                    setattr(crit, c, reg[c])
        res["importados" if nueva else "actualizados"] += 1

    # Produccion academica (hojas CAPACITACIONES / INVESTIGACIONES)
    def docente_de(nombre):
        k = clave(nombre)
        return docentes_por_nombre.get(k) or Docente.buscar_por_nombre(nombre)

    for cap in analisis["capacitaciones"]:
        doc = docente_de(cap["docente"])
        if not doc or not cap["anio"]:
            continue
        if _existe_capacitacion(doc.id, cap["titulo"], cap["anio"]):
            continue
        db.session.add(Capacitacion(
            docente_id=doc.id, nombre=cap["titulo"][:400], anio=cap["anio"], horas=cap["horas"],
            origen="excel", estado_validacion="validado",
        ))
        res["capacitaciones"] += 1

    for inv in analisis["investigaciones"]:
        doc = docente_de(inv["docente"])
        if not doc or not inv["anio"]:
            continue
        if _existe_investigacion(doc.id, inv["titulo"], inv["anio"]):
            continue
        db.session.add(Investigacion(
            docente_id=doc.id, titulo=inv["titulo"], anio=inv["anio"],
            tipo=(inv["tipo"] or "Publicaciones")[:40], subtipo=(inv["subtipo"] or None),
            origen="excel", estado_validacion="validado",
        ))
        res["investigaciones"] += 1

    imp.registros_importados = res["importados"]
    imp.registros_actualizados = res["actualizados"]
    imp.capacitaciones_importadas = res["capacitaciones"]
    imp.investigaciones_importadas = res["investigaciones"]
    # La Ficha Integral trae los resultados oficiales: el semestre queda calculado
    from datetime import datetime
    semestre.resultados_vigentes = True
    semestre.fecha_calculo = datetime.now()
    return _confirmar(res)


# ======================================================================
# Importaciones por dimension / criterio (proceso de evaluacion paso a paso)
# ======================================================================
CANDIDATAS_NOMBRE = ("apellidos y nombres", "nombre completo", "docente", "nombres y apellidos", "nombre del docente")
COLUMNAS_IDENTIDAD = ("codigo", "dni", "nombre", "apellido", "docente", "modalidad", "correo", "n°", "nro", "item")

# Palabras que identifican columnas de valores por tipo de importacion
CANDIDATAS_VALOR = {
    "encuesta": ("encuesta", "nota", "promedio", "puntaje", "resultado", "calificacion", "semestre"),
    "autoevaluacion": ("autoevaluacion", "auto-evaluacion", "nota", "promedio", "puntaje", "resultado", "semestre"),
    "criterio": ("puntaje", "nota", "valor", "cumplimiento", "porcentaje", "%", "resultado", "asistencia", "promedio"),
}
CANDIDATAS_CRITERIO = {
    "reuniones": ("reuniones", "reunion"),
    "silabos": ("silabos", "silabo"),
    "notas_config": ("notas/config", "configuracion", "config"),
    "horas_lectivas": ("horas lectivas", "hrs lect", "horas"),
    "puntualidad": ("puntualidad", "puntual"),
    "subida_notas_erp": ("erp",),
    "designacion_delegados": ("delegados", "delegado"),
}
MAX_CRITERIO = {c: maximo for c, _, maximo in CRITERIOS_NORMA}
ETIQUETA_CRITERIO = {c: etiqueta for c, etiqueta, _ in CRITERIOS_NORMA}

# Escalas de origen aceptadas para encuesta/autoevaluacion (se convierten a /10)
ESCALAS_NOTA = {"10": 10.0, "20": 20.0, "5": 5.0, "100": 100.0}


def tipo_criterio(tipo):
    """'criterio_puntualidad' -> 'puntualidad' (o None si no es un criterio)."""
    if tipo and tipo.startswith("criterio_") and tipo[9:] in MAX_CRITERIO:
        return tipo[9:]
    return None


def _es_identidad(cabecera):
    k = clave(cabecera)
    return not k or any(p in k for p in COLUMNAS_IDENTIDAD)


def _columnas_valor(cab, candidatas, excluir=(), grupos=None, especificas=()):
    """Columnas de valores (ej. 'Encuesta Sem I' y 'Encuesta Sem II' se promedian).

    Si alguna columna (o su grupo superior) contiene una palabra especifica
    (p. ej. 'encuesta'), solo se usan esas; si no, se buscan las genericas ('nota', ...).
    """
    grupos = grupos or [""] * len(cab)

    def validas(palabras, con_grupo):
        cols = []
        for i, c in enumerate(cab):
            k = clave(c)
            texto = k + " " + clave(grupos[i]) if con_grupo else k
            if _es_identidad(c) or any(x in k for x in excluir):
                continue
            if any(p in texto for p in palabras):
                cols.append(i)
        return cols

    if especificas:
        cols = validas(especificas, con_grupo=True)
        if cols:
            return cols
    return validas(candidatas, con_grupo=False)


ESPECIFICAS_VALOR = {"encuesta": ("encuesta",), "autoevaluacion": ("autoevaluac", "auto-evaluac", "auto evaluac")}

# Campos que el usuario puede asignar a mano en la pantalla de columnas
CAMPOS_IDENTIDAD = [
    ("nombre", "Apellidos y nombres (en una sola columna)"),
    ("apellidos", "Apellidos (si estan separados)"),
    ("nombres", "Nombres (si estan separados)"),
    ("codigo", "Codigo del docente"),
]
CAMPOS_DOCENTE = [
    ("modalidad", "Modalidad"), ("dni", "DNI"), ("correo", "Correo"), ("especialidad", "Especialidad"),
    ("grado", "Grado academico"), ("categoria", "Categoria"), ("anio_ingreso", "Anio de ingreso"),
]


def campos_mapeo(tipo):
    """Campos simples (una columna) a elegir segun el tipo, ademas de la identificacion."""
    if tipo == "docentes":
        return CAMPOS_DOCENTE
    if tipo == "normas":
        return [(c, f"{ETIQUETA_CRITERIO[c]} (/{MAX_CRITERIO[c]})") for c in MAX_CRITERIO] + [("nota", "Nota de normas /10 (si no hay criterios)")]
    return []


def usa_valores(tipo):
    return tipo in ("encuesta", "autoevaluacion") or bool(tipo_criterio(tipo))


def mapeo_automatico(cab, tipo, grupos=None):
    return _mapeo(cab, tipo, grupos)


def _mapeo(cab, tipo, grupos=None, manual=None):
    if manual:
        m = {k: None for k in ("nombre", "nombres", "apellidos", "codigo", "dni", "correo", "especialidad",
                               "grado", "categoria", "modalidad", "anio_ingreso", "nota", *CAMPOS_CRITERIO)}
        for k, v in manual.items():
            if k == "valores":
                m["valores"] = [int(x) for x in v if str(x).isdigit() and int(x) < len(cab)]
            elif k in m and v is not None and str(v).isdigit() and int(v) < len(cab):
                m[k] = int(v)
        m.setdefault("valores", [])
        return m
    grupos = grupos or [""] * len(cab)
    m = {
        "nombre": buscar_columna(cab, *CANDIDATAS_NOMBRE),
        "nombres": buscar_columna(cab, "nombres", "nombre", excluir=("apellido", "completo")),
        "apellidos": buscar_columna(cab, "apellidos", "apellido", excluir=("nombre",)),
        "codigo": buscar_columna(cab, "codigo", "cod docente", excluir=("asignatura", "curso")),
        "dni": buscar_columna(cab, "dni", "documento"),
        "correo": buscar_columna(cab, "correo", "email", "e-mail"),
        "especialidad": buscar_columna(cab, "especialidad"),
        "grado": buscar_columna(cab, "grado academico", "grado"),
        "categoria": buscar_columna(cab, "categoria"),
        "modalidad": buscar_columna(cab, "modalidad", "condicion"),
        "anio_ingreso": buscar_columna(cab, "ano de ingreso", "anio ingreso", "ingreso"),
        "valores": [],
    }
    if tipo in ("encuesta", "autoevaluacion"):
        m["valores"] = _columnas_valor(cab, CANDIDATAS_VALOR[tipo], excluir=("subtotal",), grupos=grupos,
                                       especificas=ESPECIFICAS_VALOR[tipo])
    elif tipo_criterio(tipo):
        campo = tipo_criterio(tipo)
        propias = _columnas_valor(cab, CANDIDATAS_CRITERIO[campo], excluir=("subtotal",))
        m["valores"] = propias or _columnas_valor(cab, CANDIDATAS_VALOR["criterio"], excluir=("subtotal",))
    elif tipo == "normas":
        for campo, cands in CANDIDATAS_CRITERIO.items():
            m[campo] = buscar_columna(cab, *cands, excluir=("subtotal",))
        # 'NOTA /10' bajo el grupo 'CUMPLIMIENTO DE NORMAS'
        m["nota"] = next((i for i, c in enumerate(cab)
                          if "nota" in clave(c) and "norma" in clave(grupos[i]) and "config" not in clave(c)), None)
        if m["nota"] is None:
            m["nota"] = buscar_columna(cab, "nota normas", "nota de normas", "normas", excluir=("subtotal", "config"))
    return m


def _valor(fila, idx):
    return fila[idx] if idx is not None and idx < len(fila) else None


def _nombre_de_fila(fila, m):
    if m.get("nombre") is not None:
        return texto_celda(_valor(fila, m["nombre"])), None, None
    nombres = titulo(texto_celda(_valor(fila, m.get("nombres"))))
    apellidos = titulo(texto_celda(_valor(fila, m.get("apellidos"))))
    return f"{apellidos} {nombres}".strip(), nombres, apellidos


def _buscar_docente(codigo, nombre):
    if codigo:
        d = Docente.query.filter_by(codigo=codigo).first()
        if d:
            return d
    return Docente.buscar_por_nombre(nombre) if nombre else None


def _convertir(valor, tipo, opciones):
    """Lleva el valor leido a la escala del sistema. Devuelve (valor, error)."""
    campo = tipo_criterio(tipo)
    if campo:
        maximo = MAX_CRITERIO[campo]
        if opciones.get("escala") == "porcentaje":
            if not 0 <= valor <= 100:
                return None, f"porcentaje fuera de rango (0-100): {valor:g}"
            return round(valor * maximo / 100.0, 4), None
        if not 0 <= valor <= maximo:
            return None, f"puntaje fuera de rango (0-{maximo}): {valor:g}"
        return round(valor, 4), None
    escala = ESCALAS_NOTA.get(str(opciones.get("escala") or "10"), 10.0)
    if not 0 <= valor <= escala:
        return None, f"nota fuera de rango (0-{escala:g}): {valor:g}"
    return round(valor * 10.0 / escala, 4), None


def analizar_tabla(ruta, tipo, opciones=None):
    """Lee, agrupa por docente y valida sin escribir en la base de datos.

    - Varias columnas de valor (p. ej. Semestre I y II) se promedian.
    - Varias filas del mismo docente (p. ej. una por curso) se promedian.
    """
    opciones = opciones or {}
    out = {
        "error": None, "columnas": [], "total": 0, "mapeo": {}, "columnas_valor": [],
        "registros": [], "no_encontrados": [], "rechazados": [],
    }
    try:
        hoja = leer_hoja(ruta, opciones.get("hoja"), opciones.get("fila_titulos"))
    except Exception as exc:
        out["error"] = f"No se pudo leer el archivo: {exc}"
        return out
    cab, filas, etiquetas = hoja["cab"], hoja["filas"], hoja["etiquetas"]
    out["hoja"], out["fila_titulos"] = hoja["hoja"], hoja["fila_titulos"]
    if not cab:
        out["error"] = "La hoja seleccionada esta vacia."
        return out
    m = _mapeo(cab, tipo, hoja["grupos"], opciones.get("columnas"))
    out["columnas"], out["total"] = etiquetas, len(filas)
    out["mapeo"] = {k: etiquetas[v] for k, v in m.items() if isinstance(v, int)}
    out["columnas_valor"] = [etiquetas[i] for i in m["valores"]]

    if m["nombre"] is None and m["nombres"] is None and m["apellidos"] is None and m["codigo"] is None:
        out["error"] = "Indique la columna con los apellidos y nombres o el codigo del docente."
        return out
    if usa_valores(tipo) and not m["valores"]:
        out["error"] = "Indique al menos una columna con las notas o puntajes."
        return out
    if tipo == "normas" and m["nota"] is None and not any(m.get(c) is not None for c in CAMPOS_CRITERIO):
        out["error"] = "Indique las columnas de los criterios de normas (o la nota de normas)."
        return out

    grupos = {}
    for n, fila in filas:
        nombre, nombres, apellidos = _nombre_de_fila(fila, m)
        codigo = texto_celda(_valor(fila, m["codigo"])) or None
        if not nombre and not codigo:
            continue
        if any(p in clave(nombre) for p in PALABRAS_TOTALES):
            continue

        if tipo == "docentes":
            out["registros"].append({
                "fila": n, "nombre": nombre, "nombres": nombres, "apellidos": apellidos, "codigo": codigo,
                "docente": _buscar_docente(codigo, nombre),
                "extra": {k: texto_celda(_valor(fila, m[k])) for k in ("dni", "correo", "especialidad", "grado", "categoria", "modalidad")},
                "anio_ingreso": a_numero(_valor(fila, m["anio_ingreso"])),
            })
            continue

        docente = _buscar_docente(codigo, nombre)
        if not docente:
            out["no_encontrados"].append({"fila": n, "nombre": nombre or codigo})
            continue
        g = grupos.setdefault(docente.id, {"docente": docente, "filas": [], "valores": {}, "errores": []})
        g["filas"].append(n)

        if tipo == "normas":
            for campo in CAMPOS_CRITERIO:
                v = a_numero(_valor(fila, m.get(campo)))
                if v is None:
                    continue
                conv, err = _convertir(v, "criterio_" + campo, opciones)
                if err:
                    g["errores"].append(f"Fila {n}, {ETIQUETA_CRITERIO[campo]}: {err}")
                else:
                    g["valores"].setdefault(campo, []).append(conv)
            v = a_numero(_valor(fila, m.get("nota")))
            if v is not None:
                if 0 <= v <= NOTA_MAX:
                    g["valores"].setdefault("normas", []).append(v)
                else:
                    g["errores"].append(f"Fila {n}: nota de normas fuera de rango (0-10): {v:g}")
        else:
            leidos = [a_numero(_valor(fila, i)) for i in m["valores"]]
            leidos = [v for v in leidos if v is not None]
            for v in leidos:
                conv, err = _convertir(v, tipo, opciones)
                if err:
                    g["errores"].append(f"Fila {n}: {err}")
                else:
                    g["valores"].setdefault("valor", []).append(conv)

    for g in grupos.values():
        promedios = {k: round(sum(v) / len(v), 4) for k, v in g["valores"].items() if v}
        reg = {"docente": g["docente"], "filas": g["filas"], "valores": promedios, "errores": g["errores"],
               "n_valores": sum(len(v) for v in g["valores"].values())}
        if g["errores"] or not promedios:
            if not promedios and not g["errores"]:
                reg["errores"] = ["Sin valores numericos."]
            out["rechazados"].append(reg)
        else:
            out["registros"].append(reg)
    out["registros"].sort(key=lambda r: (r.get("docente").apellidos if r.get("docente") else r.get("nombre", "")))
    if not out["registros"] and not out["rechazados"] and not out["no_encontrados"]:
        out["error"] = "El archivo no contiene filas con datos."
    return out


def importar_tabla(ruta, tipo, semestre_id, usuario_id, opciones=None):
    """Guarda los datos de una dimension o criterio. No calcula el promedio final:
    los resultados se obtienen recien con 'Calcular resultados' (proceso_service)."""
    res = _resultado_base()
    analisis = analizar_tabla(ruta, tipo, opciones)
    if analisis["error"]:
        res["errores"].append(analisis["error"])
        return res
    semestre = db.session.get(Semestre, semestre_id)
    res["encontrados"] = len(analisis["registros"]) + len(analisis["rechazados"]) + len(analisis["no_encontrados"])
    res["rechazados"] = len(analisis["rechazados"]) + len(analisis["no_encontrados"])
    for r in analisis["no_encontrados"]:
        res["errores"].append(f"Fila {r['fila']}: el docente '{r['nombre']}' no esta registrado. Importe primero la lista de docentes.")
    for r in analisis["rechazados"]:
        res["errores"].append(f"{r['docente'].nombre_completo}: " + "; ".join(r["errores"]))
    imp = _registrar_importacion(tipo, ruta, semestre_id, usuario_id, res)

    for reg in analisis["registros"]:
        if tipo == "docentes":
            docente = reg["docente"]
            nuevo = docente is None
            if nuevo:
                docente, _ = _obtener_o_crear_docente(reg["nombre"], res, reg["nombres"], reg["apellidos"], reg["codigo"])
            extra = reg["extra"]
            for campo, k in (("correo_institucional", "correo"), ("especialidad", "especialidad"),
                             ("grado_academico", "grado"), ("categoria_docente", "categoria")):
                if extra.get(k):
                    setattr(docente, campo, extra[k])
            if extra.get("dni"):
                if Docente.query.filter(Docente.dni == extra["dni"], Docente.id != docente.id).first():
                    res["advertencias"].append(f"{docente.nombre_completo}: el DNI {extra['dni']} ya pertenece a otro docente.")
                else:
                    docente.dni = extra["dni"]
            if reg["anio_ingreso"] and 1950 <= reg["anio_ingreso"] <= 2100:
                docente.anio_ingreso = int(reg["anio_ingreso"])
            _asegurar_participacion(docente.id, semestre_id, extra.get("modalidad") or None)
            res["importados" if nuevo else "actualizados"] += 1
            continue

        docente = reg["docente"]
        _asegurar_participacion(docente.id, semestre_id)
        ev = Evaluacion.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
        nueva = ev is None
        if nueva:
            ev = Evaluacion(docente_id=docente.id, semestre_id=semestre_id)
            db.session.add(ev)
        ev.importacion_id = imp.id

        campo_crit = tipo_criterio(tipo)
        if tipo in ("encuesta", "autoevaluacion"):
            setattr(ev, tipo, reg["valores"]["valor"])
        else:
            crit = CriterioNorma.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
            if not crit:
                crit = CriterioNorma(docente_id=docente.id, semestre_id=semestre_id)
                db.session.add(crit)
            if campo_crit:
                setattr(crit, campo_crit, reg["valores"]["valor"])
            else:
                for campo in CAMPOS_CRITERIO:
                    if campo in reg["valores"]:
                        setattr(crit, campo, reg["valores"][campo])
                if "normas" in reg["valores"]:
                    ev.normas = reg["valores"]["normas"]
            crit.calcular_subtotal()
        res["importados" if nueva else "actualizados"] += 1

    if semestre:
        semestre.marcar_desactualizado()
    imp.registros_importados = res["importados"]
    imp.registros_actualizados = res["actualizados"]
    imp.registros_rechazados = res["rechazados"]
    return _confirmar(res)
