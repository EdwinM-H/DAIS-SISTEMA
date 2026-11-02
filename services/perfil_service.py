"""Perfil academico: el docente declara, el DAIS valida lo que define la prelacion."""

from datetime import datetime

from flask import url_for

from models import db, CambioPerfil, LineaInvestigacion, TemaInvestigacion, AreaInvestigacion
from models.docente import GRADOS, RANGO_CATEGORIA, CATEGORIAS
from utils import notificar, notificar_gestion

MAX_LINEAS = 3
MAX_TEMAS = 8


class PerfilError(Exception):
    pass


def catalogo():
    return AreaInvestigacion.query.order_by(AreaInvestigacion.orden).all()


def _registrar(docente, campo, anterior, nuevo, estado, usuario, motivo=None, archivo=(None, None)):
    c = CambioPerfil(docente_id=docente.id, campo=campo, valor_anterior=anterior, valor_nuevo=nuevo, estado=estado,
                     motivo=motivo, archivo_ruta=archivo[0], archivo_nombre=archivo[1],
                     solicitado_por_id=usuario.id if usuario else None)
    if estado == "directo":
        c.revisado_en = datetime.now()
    db.session.add(c)
    return c


def _texto(v):
    return "" if v is None else str(v)


def valor_actual(docente, campo):
    if campo == "grado_academico":
        return _texto(docente.grado_academico)
    if campo == "colegiatura":
        return f"{_texto(docente.colegiatura_numero)}|{_texto(docente.colegiatura_anio)}"
    if campo == "licencia":
        return f"{docente.licencia_desde.isoformat() if docente.licencia_desde else ''}|{docente.licencia_hasta.isoformat() if docente.licencia_hasta else ''}"
    return ""


def pendiente(docente, campo):
    return next((c for c in docente.cambios_perfil if c.campo == campo and c.estado == "pendiente"), None)


def guardar_afinidad(docente, linea_ids, tema_ids, principal_id, experiencia, usuario):
    """Lineas, temas y experiencia: se registran directamente (no requieren validacion)."""
    lineas = LineaInvestigacion.query.filter(LineaInvestigacion.id.in_(linea_ids or [0])).all()
    temas = TemaInvestigacion.query.filter(TemaInvestigacion.id.in_(tema_ids or [0])).all()
    if len(lineas) > MAX_LINEAS:
        raise PerfilError(f"Seleccione como máximo {MAX_LINEAS} líneas de investigación.")
    if len(temas) > MAX_TEMAS:
        raise PerfilError(f"Seleccione como máximo {MAX_TEMAS} temas.")
    ids_lineas = {l.id for l in lineas} | {t.linea_id for t in temas}
    lineas = LineaInvestigacion.query.filter(LineaInvestigacion.id.in_(ids_lineas or [0])).all()
    if len(lineas) > MAX_LINEAS:
        raise PerfilError(f"Los temas elegidos pertenecen a más de {MAX_LINEAS} líneas. Reduzca la selección.")
    if principal_id and principal_id not in ids_lineas:
        raise PerfilError("La línea principal debe ser una de las líneas seleccionadas.")
    if experiencia is not None and not 0 <= experiencia <= 70:
        raise PerfilError("Años de experiencia fuera de rango.")

    antes = ", ".join(t.nombre for t in docente.temas)
    docente.lineas = lineas
    docente.temas = temas
    docente.linea_principal_id = principal_id or (lineas[0].id if lineas else None)
    despues = ", ".join(t.nombre for t in temas)
    if antes != despues:
        _registrar(docente, "lineas_y_temas", antes[:300], despues[:300], "directo", usuario)
    if experiencia != docente.experiencia_anios:
        _registrar(docente, "experiencia_anios", _texto(docente.experiencia_anios), _texto(experiencia), "directo", usuario)
        docente.experiencia_anios = experiencia
    docente.perfil_actualizado_en = datetime.now()


def solicitar_cambio(docente, campo, nuevo, usuario, motivo=None, archivo=(None, None)):
    """Datos validables: quedan pendientes hasta que el DAIS los aprueba (si cambian)."""
    if campo == "grado_academico" and nuevo and nuevo not in GRADOS:
        raise PerfilError("Grado académico no válido.")
    if nuevo == valor_actual(docente, campo) or (not nuevo.strip("|") and not valor_actual(docente, campo).strip("|")):
        return None
    previo = pendiente(docente, campo)
    if previo:
        previo.valor_nuevo, previo.motivo, previo.creado_en = nuevo, motivo, datetime.now()
        if archivo[0]:
            previo.archivo_ruta, previo.archivo_nombre = archivo
        return previo
    c = _registrar(docente, campo, valor_actual(docente, campo), nuevo, "pendiente", usuario, motivo, archivo)
    notificar_gestion("Dato de perfil por validar", f"{docente.nombre_completo}: {c.campo_nombre}",
                      url_for("perfiles.validaciones"), roles=("admin", "director", "operador"))
    return c


def _aplicar_valor(docente, campo, valor):
    if campo == "grado_academico":
        docente.grado_academico = valor or None
    elif campo == "colegiatura":
        numero, _, anio = (valor or "|").partition("|")
        docente.colegiatura_numero = numero or None
        docente.colegiatura_anio = int(anio) if anio.isdigit() else None
    elif campo == "licencia":
        desde, _, hasta = (valor or "|").partition("|")
        docente.licencia_desde = datetime.strptime(desde, "%Y-%m-%d").date() if desde else None
        docente.licencia_hasta = datetime.strptime(hasta, "%Y-%m-%d").date() if hasta else None


def revisar(cambio, aprobar, motivo, usuario):
    if cambio.estado != "pendiente":
        raise PerfilError("Este cambio ya fue revisado.")
    if not aprobar and not (motivo or "").strip():
        raise PerfilError("Indique el motivo del rechazo.")
    cambio.estado = "aprobado" if aprobar else "rechazado"
    cambio.revisado_por_id = usuario.id
    cambio.revisado_en = datetime.now()
    if aprobar:
        _aplicar_valor(cambio.docente, cambio.campo, cambio.valor_nuevo)
    else:
        cambio.motivo = motivo.strip()
    if cambio.docente.usuario:
        notificar(cambio.docente.usuario, f"{cambio.campo_nombre}: {'aprobado' if aprobar else 'rechazado'} por el DAIS",
                  None if aprobar else motivo, url_for("docente.perfil_academico"))


def guardar_oficial(docente, datos, usuario):
    """Datos oficiales que registra el DAIS (y correccion directa de cualquier dato del perfil)."""
    cambios = {
        "categoria_docente": datos.get("categoria_docente") if datos.get("categoria_docente") in CATEGORIAS else None,
        "condicion": datos.get("condicion") if datos.get("condicion") in ("ordinario", "contratado") else None,
        "anio_ingreso": int(datos["anio_ingreso"]) if str(datos.get("anio_ingreso", "")).isdigit() else None,
        "es_autoridad": datos.get("es_autoridad") == "1",
        "cargo_autoridad": (datos.get("cargo_autoridad") or "").strip() or None,
    }
    for campo, valor in cambios.items():
        anterior = getattr(docente, campo)
        if anterior != valor:
            _registrar(docente, campo, _texto(anterior), _texto(valor), "directo", usuario)
            setattr(docente, campo, valor)
    # El DAIS tambien puede registrar directamente los datos validables
    for campo, nuevo in (("grado_academico", datos.get("grado_academico", "")),
                         ("colegiatura", f"{(datos.get('colegiatura_numero') or '').strip()}|{(datos.get('colegiatura_anio') or '').strip()}"),
                         ("licencia", f"{datos.get('licencia_desde') or ''}|{datos.get('licencia_hasta') or ''}")):
        if nuevo != valor_actual(docente, campo):
            _registrar(docente, campo, valor_actual(docente, campo), nuevo, "directo", usuario)
            _aplicar_valor(docente, campo, nuevo)
            p = pendiente(docente, campo)
            if p:
                p.estado, p.revisado_por_id, p.revisado_en = "aprobado", usuario.id, datetime.now()


def avance(docentes):
    total = len(docentes)
    completos = sum(1 for d in docentes if d.perfil_completo)
    return {"total": total, "completos": completos, "porcentaje": round(completos * 100 / total) if total else 0}


def recordar(docentes):
    n = 0
    for d in docentes:
        if not d.perfil_completo and d.usuario and d.usuario.activo:
            notificar(d.usuario, "Complete su perfil académico",
                      "Falta: " + ", ".join(d.faltantes_perfil()) + ". Se usa para proponer asesores y dictaminantes.",
                      url_for("docente.perfil_academico"))
            n += 1
    return n


def categoria_valida(valor):
    return (valor or "").strip().lower() in RANGO_CATEGORIA
