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


def leer_tabla(ruta):
    """Lee la primera hoja de un .xlsx o un .csv. Devuelve (cabeceras, filas)."""
    if ruta.lower().endswith(".csv"):
        with open(ruta, newline="", encoding="utf-8-sig") as f:
            muestra = f.read(4096)
            f.seek(0)
            try:
                dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
            except csv.Error:
                dialecto = csv.excel
            filas = [list(r) for r in csv.reader(f, dialecto)]
    else:
        wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        filas = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    filas = [f for f in filas if any(v not in (None, "") for v in f)]
    if not filas:
        return [], []
    cabeceras = [texto_celda(c) for c in filas[0]]
    return cabeceras, filas[1:]


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
    "puntualidad": "Puntualidad (10)",
    "subida_notas_erp": "ERP (10)",
    "designacion_delegados": "Delegado (10)",
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
    return _confirmar(res)


# ======================================================================
# Importaciones simples (una tabla por tipo)
# ======================================================================
CANDIDATAS_NOMBRE = ("apellidos y nombres", "nombre completo", "docente", "nombres y apellidos", "nombre del docente")
CANDIDATAS_NOTA = {
    "encuesta": ("encuesta", "nota", "puntaje", "resultado", "calificacion"),
    "autoevaluacion": ("autoevaluacion", "auto-evaluacion", "nota", "puntaje", "resultado"),
    "normas": ("nota normas", "normas", "nota", "puntaje"),
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


def analizar_tabla(ruta, tipo):
    """Vista previa generica para los tipos simples."""
    out = {"error": None, "columnas": [], "filas": [], "total": 0, "mapeo": {}}
    try:
        cab, filas = leer_tabla(ruta)
    except Exception as exc:
        out["error"] = f"No se pudo leer el archivo: {exc}"
        return out
    if not cab:
        out["error"] = "El archivo esta vacio."
        return out
    out["columnas"] = cab
    out["filas"] = [[texto_celda(v) for v in f] for f in filas[:15]]
    out["total"] = len(filas)
    mapeo = _mapeo_simple(cab, tipo)
    if mapeo.get("nombre") is None and mapeo.get("nombres") is None:
        out["error"] = "No se encontro la columna con el nombre del docente."
    elif tipo in ("encuesta", "autoevaluacion") and mapeo.get("nota") is None:
        out["error"] = "No se encontro la columna con la nota (0-10)."
    elif tipo == "normas" and mapeo.get("nota") is None and not any(mapeo.get(c) is not None for c in CAMPOS_CRITERIO):
        out["error"] = "No se encontro la nota de normas ni columnas de criterios."
    out["mapeo"] = {k: cab[v] for k, v in mapeo.items() if v is not None}
    return out


def _mapeo_simple(cab, tipo):
    m = {
        "nombre": buscar_columna(cab, *CANDIDATAS_NOMBRE),
        "nombres": buscar_columna(cab, "nombres", "nombre", excluir=("apellido", "completo")),
        "apellidos": buscar_columna(cab, "apellidos", "apellido", excluir=("nombre",)),
        "codigo": buscar_columna(cab, "codigo", "cod docente", "cod"),
        "dni": buscar_columna(cab, "dni", "documento"),
        "correo": buscar_columna(cab, "correo", "email", "e-mail"),
        "especialidad": buscar_columna(cab, "especialidad"),
        "grado": buscar_columna(cab, "grado academico", "grado"),
        "categoria": buscar_columna(cab, "categoria"),
        "modalidad": buscar_columna(cab, "modalidad", "condicion"),
        "anio_ingreso": buscar_columna(cab, "ano de ingreso", "anio ingreso", "ingreso"),
    }
    if tipo in CANDIDATAS_NOTA:
        m["nota"] = buscar_columna(cab, *CANDIDATAS_NOTA[tipo], excluir=("subtotal",))
    if tipo == "normas":
        for campo, cands in CANDIDATAS_CRITERIO.items():
            m[campo] = buscar_columna(cab, *cands)
    return m


def _valor(fila, idx):
    return fila[idx] if idx is not None and idx < len(fila) else None


def _nombre_de_fila(fila, m):
    if m.get("nombre") is not None:
        completo = texto_celda(_valor(fila, m["nombre"]))
        return completo, None, None
    nombres = titulo(texto_celda(_valor(fila, m.get("nombres"))))
    apellidos = titulo(texto_celda(_valor(fila, m.get("apellidos"))))
    return f"{apellidos} {nombres}".strip(), nombres, apellidos


def importar_tabla(ruta, tipo, semestre_id, usuario_id):
    res = _resultado_base()
    analisis = analizar_tabla(ruta, tipo)
    if analisis["error"]:
        res["errores"].append(analisis["error"])
        return res
    cab, filas = leer_tabla(ruta)
    m = _mapeo_simple(cab, tipo)
    res["encontrados"] = len(filas)
    imp = _registrar_importacion(tipo, ruta, semestre_id, usuario_id, res)

    for n, fila in enumerate(filas, start=2):
        completo, nombres, apellidos = _nombre_de_fila(fila, m)
        if not completo:
            res["rechazados"] += 1
            res["errores"].append(f"Fila {n}: sin nombre de docente.")
            continue

        if tipo == "docentes":
            codigo = texto_celda(_valor(fila, m.get("codigo"))) or None
            docente, nuevo = _obtener_o_crear_docente(completo, res, nombres, apellidos, codigo)
            for campo, col in (("dni", "dni"), ("correo_institucional", "correo"), ("especialidad", "especialidad"),
                               ("grado_academico", "grado"), ("categoria_docente", "categoria")):
                valor = texto_celda(_valor(fila, m.get(col)))
                if valor:
                    if campo == "dni" and Docente.query.filter(Docente.dni == valor, Docente.id != docente.id).first():
                        res["advertencias"].append(f"Fila {n}: DNI {valor} ya pertenece a otro docente.")
                        continue
                    setattr(docente, campo, valor)
            anio = a_numero(_valor(fila, m.get("anio_ingreso")))
            if anio and 1950 <= anio <= 2100:
                docente.anio_ingreso = int(anio)
            _asegurar_participacion(docente.id, semestre_id, texto_celda(_valor(fila, m.get("modalidad"))) or None)
            res["importados" if nuevo else "actualizados"] += 1
            continue

        docente = Docente.buscar_por_nombre(completo)
        if not docente:
            res["rechazados"] += 1
            res["errores"].append(f"Fila {n}: el docente '{completo}' no esta registrado. Importe primero la lista de docentes.")
            continue

        ev = Evaluacion.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
        nueva = ev is None
        if nueva:
            ev = Evaluacion(docente_id=docente.id, semestre_id=semestre_id)
            db.session.add(ev)

        if tipo == "normas":
            crit = CriterioNorma.query.filter_by(docente_id=docente.id, semestre_id=semestre_id).first()
            valores = {c: a_numero(_valor(fila, m.get(c))) for c in CAMPOS_CRITERIO}
            if any(v is not None for v in valores.values()):
                if any(v is not None and v < 0 for v in valores.values()):
                    res["rechazados"] += 1
                    res["errores"].append(f"Fila {n}: criterios con valores negativos.")
                    continue
                if not crit:
                    crit = CriterioNorma(docente_id=docente.id, semestre_id=semestre_id)
                    db.session.add(crit)
                for c, v in valores.items():
                    setattr(crit, c, v)
                crit.calcular_subtotal()
            nota = a_numero(_valor(fila, m.get("nota")))
            if nota is None and crit is not None:
                nota = crit.nota_normas
        else:
            nota = a_numero(_valor(fila, m.get("nota")))

        if nota is None or not 0 <= nota <= NOTA_MAX:
            res["rechazados"] += 1
            res["errores"].append(f"Fila {n}: nota invalida o fuera de rango 0-10 ({completo}).")
            if nueva:
                db.session.expunge(ev)
            continue

        setattr(ev, tipo, round(nota, 4))
        ev.recalcular()
        ev.importacion_id = imp.id
        _asegurar_participacion(docente.id, semestre_id)
        res["importados" if nueva else "actualizados"] += 1

    imp.registros_importados = res["importados"]
    imp.registros_actualizados = res["actualizados"]
    imp.registros_rechazados = res["rechazados"]
    imp.errores = json.dumps(res["errores"] + res["advertencias"], ensure_ascii=False) if (res["errores"] or res["advertencias"]) else None
    return _confirmar(res)
