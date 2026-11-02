"""
Servicio de generacion de fichas de evaluacion docente.

Utiliza EXCLUSIVAMENTE la plantilla Word oficial:
    data/FICHA DE EVALUACION INTEGRAL DOCENTES-DAIS.docx

La plantilla original NUNCA se modifica: se abre una copia en memoria y
solo se reemplazan los marcadores {{...}} conservando todo el diseno
(logos, tablas, bordes, fuentes, imagenes, distribucion).
"""

import io
import os
import re
import unicodedata
from datetime import date

from docx import Document
from docx.oxml.ns import qn

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLANTILLA_FICHA = os.path.join(BASE_DIR, "data", "FICHA DE EVALUACI\xd3N INTEGRAL DOCENTES-DAIS.docx")

TOKEN_RE = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")
TOKEN_SUELTO_RE = re.compile(r"\{\{[^{}]{0,60}\}\}")

MSG_SIN_CAPACITACIONES = "No registrado"
MSG_SIN_PUBLICACIONES = "No registrado"
MAX_ITEMS_FICHA = 12
SEMESTRE_FIJO_RE = re.compile(r"20\d{2}-I\s+y\s+20\d{2}-II")


class FichaError(Exception):
    """Error controlado durante la generacion de una ficha."""


def plantilla_disponible():
    return os.path.exists(PLANTILLA_FICHA)


def sanear_nombre(texto):
    """Convierte un texto en nombre de archivo seguro para Windows."""
    if not texto:
        return "SIN_NOMBRE"
    normalizado = unicodedata.normalize("NFKD", str(texto))
    ascii_texto = normalizado.encode("ascii", "ignore").decode("ascii")
    sano = re.sub(r"[^A-Za-z0-9]+", "_", ascii_texto)
    sano = re.sub(r"_+", "_", sano).strip("_")
    return (sano or "SIN_NOMBRE").upper()


# ----------------------------------------------------------------------
# Reemplazo de marcadores a nivel XML (resistente a division de runs)
# ----------------------------------------------------------------------
def _poner(nuevos, spans, completo, ini, fin, valor=None):
    primero = True
    for k, (a, b) in enumerate(spans):
        if b <= ini or a >= fin:
            continue
        if valor is not None:
            if primero:
                nuevos[k] += valor
                primero = False
            continue
        s = max(a, ini)
        e = min(b, fin)
        if e > s:
            nuevos[k] += completo[s:e]


def _reemplazar_parrafo(p_xml, mapping):
    ts = list(p_xml.iter(qn("w:t")))
    if not ts:
        return
    textos = [t.text or "" for t in ts]
    completo = "".join(textos)
    if "{{" not in completo:
        return

    matches = list(TOKEN_RE.finditer(completo))
    spans = []
    pos = 0
    for tx in textos:
        spans.append((pos, pos + len(tx)))
        pos += len(tx)

    nuevos = [""] * len(ts)

    if matches:
        cursor = 0
        for m in matches:
            _poner(nuevos, spans, completo, cursor, m.start())
            clave = m.group(1)
            _poner(nuevos, spans, completo, m.start(), m.end(), valor=str(mapping.get(clave, "-")))
            cursor = m.end()
        _poner(nuevos, spans, completo, cursor, len(completo))
    else:
        # Marcador dividido de forma irregular: reconstruir el parrafo completo
        def sustitucion(m):
            return str(mapping.get(re.sub(r"[^A-Z0-9_]", "", m.group(0)), "-"))

        limpio = TOKEN_RE.sub(sustitucion, completo)
        limpio = TOKEN_SUELTO_RE.sub(lambda m: "-", limpio) if "{{" in limpio else limpio
        nuevos[0] += limpio

    for k, t in enumerate(ts):
        nuevo = nuevos[k]
        if nuevo != (t.text or ""):
            if "\n" in nuevo:
                _escribir_multilinea(t, nuevo)
                continue
            t.text = nuevo
            if nuevo != nuevo.strip():
                t.set(qn("xml:space"), "preserve")


def _escribir_multilinea(t, texto):
    """Escribe varias lineas en el mismo run usando saltos de linea de Word (w:br)."""
    from docx.oxml import OxmlElement

    lineas = texto.split("\n")
    t.text = lineas[0]
    t.set(qn("xml:space"), "preserve")
    ancla = t
    for linea in lineas[1:]:
        br = OxmlElement("w:br")
        ancla.addnext(br)
        nuevo_t = OxmlElement("w:t")
        nuevo_t.text = linea
        nuevo_t.set(qn("xml:space"), "preserve")
        br.addnext(nuevo_t)
        ancla = nuevo_t


def _reemplazar_en_elemento(elemento, mapping):
    for p_xml in elemento.iter(qn("w:p")):
        _reemplazar_parrafo(p_xml, mapping)


def _reemplazar_documento(doc, mapping):
    _reemplazar_en_elemento(doc.element.body, mapping)
    for seccion in doc.sections:
        for parte in (seccion.header, seccion.footer):
            try:
                _reemplazar_en_elemento(parte._element, mapping)
            except Exception:
                pass


def _verificar_sin_marcadores(doc):
    restantes = []
    for t in doc.element.body.iter(qn("w:t")):
        if t.text and "{{" in t.text:
            for m in TOKEN_SUELTO_RE.finditer(t.text):
                restantes.append(m.group(0))
    return restantes


# ----------------------------------------------------------------------
# Datos -> marcadores
# ----------------------------------------------------------------------
def _fmt_num(valor):
    if valor is None:
        return "-"
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if abs(f - round(f)) < 0.005:
        return str(int(round(f)))
    return f"{f:.2f}"


def calcular_posicion_mapa(semestre_id):
    """{docente_id: posicion} con el mismo criterio de desempate que el Ranking."""
    from services.evaluacion_service import mapa_posiciones

    return mapa_posiciones(semestre_id)


def _texto_capacitaciones(docente, semestre):
    """Capacitaciones validadas del periodo evaluado (anio del semestre y anterior)."""
    items = [
        c for c in docente.capacitaciones
        if c.estado_validacion == "validado" and c.anio >= semestre.anio - 1
    ]
    if not items:
        return MSG_SIN_CAPACITACIONES, []
    items.sort(key=lambda c: (-c.anio, c.nombre))
    lineas = []
    for c in items[:MAX_ITEMS_FICHA]:
        horas = f", {_fmt_num(c.horas)} h" if c.horas else ""
        lineas.append(f"• {c.nombre} ({c.anio}{horas})")
    if len(items) > MAX_ITEMS_FICHA:
        lineas.append(f"... y {len(items) - MAX_ITEMS_FICHA} capacitaciones mas.")
    return "\n".join(lineas), items


def _texto_publicaciones(docente):
    items = [i for i in docente.investigaciones if i.estado_validacion == "validado"]
    if not items:
        return MSG_SIN_PUBLICACIONES, []
    items.sort(key=lambda i: (-i.anio, i.titulo))
    lineas = []
    for i in items[:MAX_ITEMS_FICHA]:
        detalle = ", ".join(x for x in (i.subtipo or i.tipo, str(i.anio)) if x)
        lineas.append(f"• {i.titulo} ({detalle})")
    if len(items) > MAX_ITEMS_FICHA:
        lineas.append(f"... y {len(items) - MAX_ITEMS_FICHA} trabajos mas.")
    return "\n".join(lineas), items


def construir_mapeo(docente_id, semestre_id):
    """Construye el diccionario marcador -> valor con los datos reales del sistema."""
    from models import db, Docente, Semestre, Evaluacion, CriterioNorma, DocenteSemestre

    docente = db.session.get(Docente, docente_id)
    semestre = db.session.get(Semestre, semestre_id)
    if not docente or not semestre:
        raise FichaError("Docente o semestre no encontrado.")

    ev = Evaluacion.query.filter_by(docente_id=docente.id, semestre_id=semestre.id).first()
    if not ev or ev.promedio_final is None:
        raise FichaError(
            "No se encontraron datos completos de evaluacion para {} en el semestre {}.".format(
                docente.nombre_completo, semestre.codigo
            )
        )

    crit = CriterioNorma.query.filter_by(docente_id=docente.id, semestre_id=semestre.id).first()
    part = DocenteSemestre.query.filter_by(docente_id=docente.id, semestre_id=semestre.id).first()
    posiciones = calcular_posicion_mapa(semestre.id)
    posicion = posiciones.get(docente.id)
    texto_cap, lista_cap = _texto_capacitaciones(docente, semestre)
    texto_pub, lista_pub = _texto_publicaciones(docente)

    contexto = {
        "docente": docente,
        "semestre": semestre,
        "evaluacion": ev,
        "criterios": crit,
        "modalidad": part.modalidad if part else None,
        "posicion": posicion,
        "total_ranking": len(posiciones),
        "fecha": date.today().strftime("%d/%m/%Y"),
        "capacitaciones": texto_cap,
        "publicaciones": texto_pub,
        "lista_capacitaciones": lista_cap,
        "lista_publicaciones": lista_pub,
    }

    mapping = {
        "CODIGO": docente.codigo or "-",
        "NOMBRE": f"{docente.apellidos} {docente.nombres}".strip().upper() or "-",
        "MODALIDAD": (part.modalidad if part and part.modalidad else "No registrado"),
        "FECHA": contexto["fecha"],
        "ANIOS": str(docente.anios_servicio) if docente.anios_servicio is not None else "-",
        "NOTA_ENC": _fmt_num(ev.encuesta),
        "REUNIONES": _fmt_num(crit.reuniones if crit else None),
        "SILABOS": _fmt_num(crit.silabos if crit else None),
        "NOTAS": _fmt_num(crit.notas_config if crit else None),
        "HRS": _fmt_num(crit.horas_lectivas if crit else None),
        "PUNTUAL": _fmt_num(crit.puntualidad if crit else None),
        "ERP": _fmt_num(crit.subida_notas_erp if crit else None),
        "DELEGADO": _fmt_num(crit.designacion_delegados if crit else None),
        "NOTA_AUTO": _fmt_num(ev.autoevaluacion),
        "PROMEDIO": "{:.2f}".format(ev.promedio_final),
        "CLASIF": ev.clasificacion or "No registrado",
        "POSICION": f"{posicion} de {len(posiciones)}" if posicion else "-",
        "CAPACITACIONES": texto_cap,
        "PUBLICACIONES": texto_pub,
    }
    contexto["mapping"] = mapping
    return contexto


def _reemplazar_semestre_fijo(doc, codigo):
    """La plantilla trae el texto fijo '2025-I y 2025-II'; se reemplaza en la copia por el semestre real."""
    for t in doc.element.body.iter(qn("w:t")):
        if t.text and SEMESTRE_FIJO_RE.search(t.text):
            t.text = SEMESTRE_FIJO_RE.sub(codigo, t.text)


# ----------------------------------------------------------------------
# Generacion del DOCX (copia en memoria; la plantilla original queda intacta)
# ----------------------------------------------------------------------
def generar_docx_bytes(docente_id, semestre_id):
    """Devuelve (BytesIO, nombre_archivo, contexto). Levanta FichaError si no hay datos."""
    if not plantilla_disponible():
        raise FichaError("La plantilla oficial de la ficha no esta disponible.")

    contexto = construir_mapeo(docente_id, semestre_id)
    mapping = contexto["mapping"]

    doc = Document(PLANTILLA_FICHA)
    _reemplazar_documento(doc, mapping)
    _reemplazar_semestre_fijo(doc, contexto["semestre"].codigo)

    restantes = _verificar_sin_marcadores(doc)
    if restantes:
        for p_xml in doc.element.body.iter(qn("w:p")):
            for t in p_xml.iter(qn("w:t")):
                if t.text and "{{" in t.text:
                    t.text = TOKEN_SUELTO_RE.sub("-", t.text)

    nombre_base = sanear_nombre(contexto["docente"].apellidos + "_" + contexto["docente"].nombres)
    filename = "FICHA_{}_{}.docx".format(nombre_base, sanear_nombre(contexto["semestre"].codigo))

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer, filename, contexto


def generar_zip_bytes(docentes_ids, semestre_id):
    """
    Genera un DOCX por cada docente y los empaqueta en un ZIP.
    Devuelve (BytesIO, nombre_zip, generados, fallos).
      generados: lista de (filename, contexto)
      fallos: lista de (nombre_docente, mensaje_error)
    """
    import zipfile

    from models import db, Semestre

    semestre = db.session.get(Semestre, semestre_id)
    if not semestre:
        raise FichaError("Semestre no encontrado.")

    zip_buffer = io.BytesIO()
    generados = []
    fallos = []

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        nombres_usados = set()
        for did in docentes_ids:
            try:
                buffer, filename, ctx = generar_docx_bytes(did, semestre_id)
                if filename in nombres_usados:
                    base, ext = os.path.splitext(filename)
                    filename = "{}_{}{}".format(base, len(generados) + 1, ext)
                nombres_usados.add(filename)
                zf.writestr(filename, buffer.getvalue())
                generados.append((filename, ctx))
            except FichaError as exc:
                from models import Docente

                doc = db.session.get(Docente, did)
                fallos.append((doc.nombre_completo if doc else f"ID {did}", str(exc)))
            except Exception as exc:
                from models import Docente

                doc = db.session.get(Docente, did)
                fallos.append((doc.nombre_completo if doc else f"ID {did}", f"Error inesperado: {exc}"))

    if not generados:
        raise FichaError("Ninguna ficha pudo generarse. " + "; ".join(f[1] for f in fallos[:3]))

    zip_buffer.seek(0)
    nombre_zip = "FICHAS_{}.zip".format(sanear_nombre(semestre.codigo))
    return zip_buffer, nombre_zip, generados, fallos


def guardar_copia_local(app, buffer, filename, codigo_semestre):
    """Guarda una copia organizada por semestre bajo generated/. Devuelve ruta relativa."""
    carpeta_semestre = sanear_nombre(codigo_semestre).lower()
    destino_dir = os.path.join(app.config["GENERATED_FOLDER"], carpeta_semestre)
    os.makedirs(destino_dir, exist_ok=True)

    nombre = filename
    ruta_final = os.path.join(destino_dir, nombre)
    contador = 1
    base, ext = os.path.splitext(filename)
    while os.path.exists(ruta_final):
        nombre = "{}({}){}".format(base, contador, ext)
        ruta_final = os.path.join(destino_dir, nombre)
        contador += 1

    with open(ruta_final, "wb") as f:
        f.write(buffer.getvalue())

    return os.path.join(carpeta_semestre, nombre), nombre
