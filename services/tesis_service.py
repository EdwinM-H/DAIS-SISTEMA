"""Flujo de tesis segun el Reglamento Marco (Res. 256-CU-2024-UAC).

El DAIS (Departamento Academico) propone asesor y dictaminantes, registra las resoluciones del
Decanato y lleva el control de plazos (Art. 54, 71, 99). Los docentes aceptan su designacion o
declaran impedimento y emiten dictamenes: suficiente, con observaciones o insuficiente.
"""

from datetime import date, datetime, timedelta

from flask import url_for

from models import db, TesisMiembro, TesisVersion, TesisEvento, Dictamen, ResolucionTesis
from models.tesis import ROLES_TESIS, RESULTADOS_DICTAMEN, TIPOS_RESOLUCION, ACTIVOS
from services import parametros, calendario
from services import asignacion_service
from utils import notificar, notificar_gestion


class TesisError(Exception):
    pass


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def registrar_evento(tesis, tipo, descripcion, usuario=None):
    db.session.add(TesisEvento(tesis_id=tesis.id, tipo=tipo, descripcion=descripcion,
                               usuario_id=usuario.id if usuario else None))


def _url_estudiante(tesis):
    return url_for("estudiante.mi_tesis", tesis_id=tesis.id)


def _url_docente(tesis):
    return url_for("docente.tesis_detalle", tesis_id=tesis.id)


def _notificar_estudiantes(tesis, titulo, mensaje=None):
    for est in tesis.estudiantes:
        if est.usuario:
            notificar(est.usuario, titulo, mensaje, _url_estudiante(tesis))


def _notificar_miembro(miembro, titulo, mensaje=None):
    if miembro.docente.usuario:
        notificar(miembro.docente.usuario, titulo, mensaje, _url_docente(miembro.tesis))


def _abierta(tesis):
    if tesis.cerrada:
        raise TesisError("La tesis ya está cerrada.")


def objetivo_dictaminantes(tesis):
    if tesis.modalidad == "suficiencia":
        return parametros.obtener("dictaminantes_suficiencia")
    if tesis.etapa in ("asesor", "proyecto", "inscripcion", "desarrollo"):
        return parametros.obtener("dictaminantes_proyecto")
    if tesis.regimen == "anterior":
        return parametros.obtener("dictaminantes_proyecto")
    return parametros.obtener("dictaminantes_tesis")


def necesidades(tesis):
    """Designaciones que faltan en la etapa actual: [(rol, cantidad)]."""
    if tesis.cerrada:
        return []
    faltan = []
    if not tesis.asesor:
        faltan.append(("asesor", 1))
    if tesis.etapa in ("proyecto", "dictamen"):
        n = objetivo_dictaminantes(tesis) - len(tesis.dictaminantes)
        if n > 0:
            faltan.append(("dictaminante", n))
        if tesis.decision_pendiente == "dirimente" and not tesis.dirimentes:
            faltan.append(("dirimente", 1))
    if tesis.regimen == "anterior" and tesis.etapa in ("apto", "sustentacion"):
        n = 2 - len(tesis.activos("replicante"))
        if n > 0:
            faltan.append(("replicante", n))
    return faltan


# ----------------------------------------------------------------------
# Designaciones
# ----------------------------------------------------------------------
def designar(tesis, docente, rol, usuario, candidato=None):
    _abierta(tesis)
    if rol not in ROLES_TESIS:
        raise TesisError("Rol no válido.")
    if rol == "coasesor" and not parametros.obtener("permite_coasesor"):
        raise TesisError("El coasesor no está habilitado en la configuración (Art. 61).")
    previos = [m for m in tesis.miembros if m.docente_id == docente.id and m.estado_designacion != "retirado"]
    if previos:
        p = previos[0]
        raise TesisError(f"{docente.nombre_completo} ya figura como {p.rol_nombre.lower()} ({p.estado_nombre.lower()}) en esta tesis.")
    if rol == "asesor" and tesis.asesor:
        raise TesisError("La tesis ya tiene asesor.")
    if docente.es_autoridad and rol != "asesor":
        raise TesisError("Una autoridad (Decano) no puede ser dictaminante (Art. 73).")
    if rol == "dictaminante" and len(tesis.dictaminantes) >= objetivo_dictaminantes(tesis):
        raise TesisError("La tesis ya tiene el número de dictaminantes requerido para esta etapa.")

    retirado = next((m for m in tesis.miembros if m.docente_id == docente.id and m.rol == rol), None)
    miembro = retirado or TesisMiembro(tesis=tesis, docente=docente, rol=rol)
    miembro.estado_designacion = "propuesto"
    miembro.etapa_ingreso = "tesis" if tesis.etapa in ("desarrollo", "dictamen") or tesis.modalidad == "suficiencia" else "proyecto"
    miembro.fecha_designacion = datetime.now()
    miembro.fecha_respuesta = None
    miembro.motivo_impedimento = None
    miembro.asignado_por_id = usuario.id if usuario else None
    miembro.automatico = candidato is not None
    if candidato:
        miembro.puntaje = candidato["puntaje"]
        miembro.motivos = "|".join(candidato["motivos"])
    db.session.add(miembro)
    db.session.flush()
    asignacion_service.reordenar_prelacion(tesis)

    plazo = parametros.obtener("plazo_aceptar_designacion")
    registrar_evento(tesis, "designacion",
                     f"{docente.nombre_completo} propuesto(a) como {miembro.rol_nombre.lower()}"
                     + (" (propuesta automática)." if candidato else "."), usuario)
    _notificar_miembro(miembro, f"Designación como {miembro.rol_nombre.lower()}: {tesis.codigo}",
                       f"Acepte o declare impedimento dentro de {plazo} días hábiles. {tesis.titulo[:120]}")
    return miembro


def proponer_automaticamente(tesis, usuario, rol=None):
    """Completa las designaciones que faltan con los mejores candidatos. Devuelve los miembros creados."""
    creados = []
    for r, n in necesidades(tesis):
        if rol and r != rol:
            continue
        for c in asignacion_service.proponer(tesis, r, n):
            creados.append(designar(tesis, c["docente"], r, usuario, candidato=c))
    if not creados and not necesidades(tesis):
        raise TesisError("No hay designaciones pendientes en esta etapa.")
    if not creados:
        raise TesisError("No hay docentes disponibles que cumplan las condiciones (revise cupos y perfiles).")
    return creados


def responder_designacion(miembro, acepta, motivo, usuario):
    tesis = miembro.tesis
    _abierta(tesis)
    if miembro.estado_designacion != "propuesto":
        raise TesisError("Esta designación ya fue respondida.")
    miembro.fecha_respuesta = datetime.now()
    if acepta:
        miembro.estado_designacion = "aceptado"
        registrar_evento(tesis, "aceptacion", f"{miembro.docente.nombre_completo} aceptó su designación como {miembro.rol_nombre.lower()}.", usuario)
        if miembro.rol == "asesor" and tesis.etapa == "asesor":
            tesis.etapa = "dictamen" if tesis.modalidad == "suficiencia" else "proyecto"
            registrar_evento(tesis, "etapa", f"Pasa a la etapa: {tesis.etapa_nombre}.", usuario)
        _abrir_dictamenes(tesis)
        return None

    if not (motivo or "").strip():
        raise TesisError("Indique el motivo del impedimento.")
    miembro.estado_designacion = "impedimento"
    miembro.motivo_impedimento = motivo.strip()
    asignacion_service.reordenar_prelacion(tesis)
    registrar_evento(tesis, "impedimento", f"{miembro.docente.nombre_completo} declaró impedimento como {miembro.rol_nombre.lower()}: {motivo.strip()}", usuario)
    notificar_gestion(f"Impedimento en la tesis {tesis.codigo}", f"{miembro.docente.nombre_completo}: {motivo.strip()}",
                      url_for("tesis.detalle", tesis_id=tesis.id), roles=("admin", "director", "operador"))
    return _reponer(tesis, miembro.rol, usuario)


def _reponer(tesis, rol, usuario):
    """Propone automaticamente al siguiente candidato para el rol que quedo vacante."""
    propuestos = asignacion_service.proponer(tesis, rol, 1)
    if not propuestos:
        notificar_gestion(f"Sin candidatos disponibles para {tesis.codigo}",
                          f"No hay docentes disponibles para {ROLES_TESIS[rol].lower()}.",
                          url_for("tesis.detalle", tesis_id=tesis.id))
        return None
    return designar(tesis, propuestos[0]["docente"], rol, usuario, candidato=propuestos[0])


def reemplazar(miembro, motivo, usuario):
    """Cambio de dictaminante/asesor (Art. 63, 84, 110): queda 'reemplazado' y se propone otro."""
    tesis = miembro.tesis
    _abierta(tesis)
    if not miembro.activo:
        raise TesisError("El docente ya no está activo en esta tesis.")
    miembro.estado_designacion = "reemplazado"
    for d in miembro.dictamenes:
        if d.pendiente:
            db.session.delete(d)
    db.session.flush()
    asignacion_service.reordenar_prelacion(tesis)
    registrar_evento(tesis, "reemplazo", f"{miembro.docente.nombre_completo} fue reemplazado(a) como {miembro.rol_nombre.lower()}. Motivo: {motivo or 'no indicado'}", usuario)
    _notificar_miembro(miembro, f"Se registró su reemplazo en la tesis {tesis.codigo}", motivo)
    return _reponer(tesis, miembro.rol, usuario)


def retirar(miembro, usuario):
    tesis = miembro.tesis
    miembro.estado_designacion = "retirado"
    for d in miembro.dictamenes:
        if d.pendiente:
            db.session.delete(d)
    db.session.flush()
    asignacion_service.reordenar_prelacion(tesis)
    registrar_evento(tesis, "retiro", f"{miembro.docente.nombre_completo} fue retirado(a) como {miembro.rol_nombre.lower()}.", usuario)


# ----------------------------------------------------------------------
# Documentos y dictamenes
# ----------------------------------------------------------------------
def _emisores(tesis):
    return [m for m in tesis.miembros if m.rol in ("dictaminante", "dirimente") and m.estado_designacion == "aceptado"]


def _abrir_dictamenes(tesis, nueva_ronda=False):
    """Crea los dictamenes pendientes de la ronda actual con su fecha limite."""
    etapa = tesis.etapa_dictamen
    if not etapa:
        return
    doc_etapa = "proyecto" if etapa == "proyecto" else "tesis"
    if not any(v.etapa == doc_etapa for v in tesis.versiones):
        return
    ronda = tesis.ronda_actual(etapa) + (1 if nueva_ronda else 0)
    ronda = max(ronda, 1)
    hoy = date.today()
    plazo_inicial = parametros.obtener("plazo_dictamen_proyecto" if etapa == "proyecto" else "plazo_dictamen_tesis")
    plazo_revision = parametros.obtener("plazo_revision_subsanacion")
    for m in _emisores(tesis):
        ultimo = tesis.ultimo_dictamen(m, etapa)
        if ultimo is None:
            plazo = plazo_inicial
        elif ultimo.resultado == "con_observaciones" and ultimo.ronda < ronda:
            plazo = plazo_revision
        else:
            continue
        db.session.add(Dictamen(tesis=tesis, miembro=m, etapa=etapa, ronda=ronda, inicio=hoy,
                                limite=calendario.sumar_habiles(hoy, plazo)))
        _notificar_miembro(m, f"Documento para dictaminar: {tesis.codigo}",
                           f"Plazo: {plazo} días hábiles (hasta el {calendario.sumar_habiles(hoy, plazo):%d/%m/%Y}).")
    db.session.flush()


def hay_observaciones_pendientes(tesis):
    etapa = tesis.etapa_dictamen
    if not etapa:
        return False
    return any((d := tesis.ultimo_dictamen(m, etapa)) and d.resultado == "con_observaciones" for m in _emisores(tesis))


def subir_version(tesis, ruta, nombre, comentario, usuario, subsanacion=(None, None)):
    _abierta(tesis)
    if tesis.etapa in ("asesor", "proyecto"):
        etapa_doc = "tesis" if tesis.modalidad == "suficiencia" else "proyecto"
    elif tesis.etapa in ("desarrollo", "dictamen"):
        etapa_doc = "tesis"
    elif tesis.etapa == "observaciones":
        etapa_doc = "final"
    else:
        raise TesisError(f"En la etapa '{tesis.etapa_nombre}' no se reciben documentos.")

    es_subsanacion = hay_observaciones_pendientes(tesis)
    if es_subsanacion and not subsanacion[0]:
        raise TesisError("Adjunte el documento que indica cómo se levantaron las observaciones (Art. 78, 103).")

    numero = max((v.numero for v in tesis.versiones), default=0) + 1
    tesis.versiones.insert(0, TesisVersion(
        numero=numero, etapa=etapa_doc, archivo_ruta=ruta, archivo_nombre=nombre,
        subsanacion_ruta=subsanacion[0], subsanacion_nombre=subsanacion[1],
        comentario=(comentario or "").strip() or None, subido_por_id=usuario.id,
    ))
    db.session.flush()

    if tesis.etapa == "desarrollo":
        if tesis.fecha_limite_entrega and date.today() > tesis.fecha_limite_entrega:
            raise TesisError("Venció el plazo para presentar la tesis (Art. 87-88). Solicite ampliación.")
        tesis.etapa = "dictamen"
        registrar_evento(tesis, "etapa", "El tesista presentó la tesis para dictamen.", usuario)
    texto = "levantamiento de observaciones" if es_subsanacion else ("versión final" if etapa_doc == "final" else "documento")
    registrar_evento(tesis, "version", f"Se subió la versión {numero} ({texto}).", usuario)
    _abrir_dictamenes(tesis, nueva_ronda=es_subsanacion)
    if etapa_doc == "final":
        notificar_gestion(f"Versión final de {tesis.codigo}", "Verifique la subsanación de observaciones de la sustentación.",
                          url_for("tesis.detalle", tesis_id=tesis.id), roles=("admin", "director", "operador"))


def emitir_dictamen(dictamen, resultado, observaciones, usuario, archivo=(None, None)):
    tesis = dictamen.tesis
    _abierta(tesis)
    if not dictamen.pendiente:
        raise TesisError("Este dictamen ya fue emitido.")
    if resultado not in RESULTADOS_DICTAMEN:
        raise TesisError("Seleccione el resultado del dictamen.")
    if resultado != "suficiente" and not (observaciones or "").strip():
        raise TesisError("Detalle las observaciones o el sustento del dictamen.")
    if dictamen.miembro.estado_designacion != "aceptado":
        raise TesisError("Su designación no está vigente.")
    dictamen.resultado = resultado
    dictamen.observaciones = (observaciones or "").strip() or None
    dictamen.emitido_en = datetime.now()
    if archivo[0]:
        dictamen.archivo_ruta, dictamen.archivo_nombre = archivo
    m = dictamen.miembro
    registrar_evento(tesis, "dictamen",
                     f"{m.docente.nombre_completo} ({m.rol_nombre.lower()}) emitió dictamen "
                     f"{RESULTADOS_DICTAMEN[resultado].lower()} ({'proyecto' if dictamen.etapa == 'proyecto' else 'tesis'}, ronda {dictamen.ronda}).",
                     usuario)
    _notificar_estudiantes(tesis, f"Dictamen {RESULTADOS_DICTAMEN[resultado].lower()} de su {'proyecto' if dictamen.etapa == 'proyecto' else 'tesis'}",
                           dictamen.observaciones)

    if resultado == "con_observaciones":
        rondas = sum(1 for d in m.dictamenes if d.etapa == dictamen.etapa and d.resultado == "con_observaciones")
        if rondas >= parametros.obtener("rondas_maximas_observacion"):
            notificar_gestion(f"{tesis.codigo}: {rondas} rondas de observaciones",
                              f"{m.docente.nombre_completo} observó {rondas} veces. Puede evaluarse su cambio (Art. 110 d).",
                              url_for("tesis.detalle", tesis_id=tesis.id))
    db.session.flush()
    evaluar_dictamenes(tesis, usuario)


def estado_revision(tesis):
    """Situacion de la etapa de dictamen actual (para mostrar)."""
    etapa = tesis.etapa_dictamen
    if not etapa:
        return None
    doc_etapa = "proyecto" if etapa == "proyecto" else "tesis"
    if tesis.decision_pendiente == "dirimente":
        return "requiere_dirimente"
    if tesis.decision_pendiente == "decano":
        return "decision_decano"
    aceptados = [m for m in tesis.dictaminantes if m.estado_designacion == "aceptado"]
    if len(aceptados) < objetivo_dictaminantes(tesis):
        return "esperando_designacion"
    if not any(v.etapa == doc_etapa for v in tesis.versiones):
        return "esperando_documento"
    if hay_observaciones_pendientes(tesis) and not any(d.pendiente for d in tesis.dictamenes_de(etapa)):
        return "observada"
    return "en_revision"


ESTADOS_REVISION_TEXTO = {
    "esperando_designacion": "Esperando la designación y aceptación de dictaminantes",
    "esperando_documento": "Esperando el documento del tesista",
    "en_revision": "En revisión por los dictaminantes",
    "observada": "Con observaciones: el tesista debe subsanar",
    "requiere_dirimente": "Requiere docente dirimente",
    "decision_decano": "Requiere decisión del Decano / comisión revisora",
}


def evaluar_dictamenes(tesis, usuario=None):
    """Aplica las reglas del reglamento cuando todos los dictaminantes emitieron dictamen."""
    etapa = tesis.etapa_dictamen
    if not etapa:
        return
    objetivo = objetivo_dictaminantes(tesis)

    # 1) Resultado del dirimente (Art. 83, 108)
    for dir_m in [m for m in _emisores(tesis) if m.rol == "dirimente"]:
        d = tesis.ultimo_dictamen(dir_m, etapa)
        if not d or d.pendiente:
            return
        insuficientes = [m for m in tesis.dictaminantes if (x := tesis.ultimo_dictamen(m, etapa)) and x.resultado == "insuficiente"]
        if d.resultado in ("suficiente", "con_observaciones") and insuficientes:
            reemplazado = insuficientes[0]
            reemplazado.estado_designacion = "reemplazado"
            dir_m.rol = "dictaminante"
            tesis.decision_pendiente = None
            asignacion_service.reordenar_prelacion(tesis)
            registrar_evento(tesis, "dirimente", f"El dirimente {dir_m.docente.nombre_completo} reemplaza a {reemplazado.docente.nombre_completo}.", usuario)
            db.session.flush()
        elif d.resultado == "insuficiente":
            if etapa == "proyecto":
                return _rechazar(tesis, "El dirimente ratificó el dictamen insuficiente del proyecto (Art. 83).", usuario)
            dir_m.estado_designacion = "retirado"
            tesis.decision_pendiente = "decano"
            registrar_evento(tesis, "dirimente", "El dirimente dictaminó insuficiente. Puede designarse un segundo dirimente o una comisión revisora (Art. 108).", usuario)
            return

    miembros = [m for m in tesis.dictaminantes if m.estado_designacion == "aceptado"]
    if len(miembros) < objetivo:
        return
    ultimos = [tesis.ultimo_dictamen(m, etapa) for m in miembros]
    if any(d is None or d.pendiente for d in ultimos):
        return
    res = [d.resultado for d in ultimos]
    n_ins, n_suf = res.count("insuficiente"), res.count("suficiente")

    if n_suf == len(res):
        tesis.decision_pendiente = None
        if etapa == "proyecto":
            tesis.etapa = "inscripcion"
            registrar_evento(tesis, "favorable", "Dictamen del proyecto: suficiente por todos los dictaminantes. Corresponde inscribir el tema (Art. 85).", usuario)
            _notificar_estudiantes(tesis, "Su proyecto obtuvo dictamen suficiente", "Solicite la inscripción del tema de tesis.")
        else:
            tesis.etapa = "apto"
            registrar_evento(tesis, "favorable", "Dictamen de la tesis: suficiente por todos los dictaminantes. Corresponde la declaración de apto (Art. 112).", usuario)
            _notificar_estudiantes(tesis, "Su tesis obtuvo dictamen suficiente", "Solicite la declaración de apto y la fecha de sustentación.")
        notificar_gestion(f"Dictamen favorable: {tesis.codigo}", tesis.titulo[:150], url_for("tesis.detalle", tesis_id=tesis.id))
    elif n_ins == len(res):
        _rechazar(tesis, "Todos los dictaminantes emitieron dictamen insuficiente (Art. 82, 107).", usuario)
    elif n_ins == 1 and n_suf == len(res) - 1:
        tesis.decision_pendiente = "dirimente"
        registrar_evento(tesis, "dirimente", "Un dictamen insuficiente frente a los demás suficientes: corresponde designar un dirimente (Art. 83, 108).", usuario)
        notificar_gestion(f"{tesis.codigo} requiere dirimente", None, url_for("tesis.detalle", tesis_id=tesis.id))
    elif n_ins >= 1:
        tesis.decision_pendiente = "decano"
        registrar_evento(tesis, "decano", "Dictámenes discrepantes: el Decano o una comisión revisora define la continuidad (Art. 109).", usuario)
        notificar_gestion(f"{tesis.codigo} requiere decisión del Decano", None, url_for("tesis.detalle", tesis_id=tesis.id))
    # Si solo hay 'con observaciones' (y suficientes) el tesista debe subsanar.


def _rechazar(tesis, motivo, usuario):
    tesis.etapa = "rechazada"
    tesis.decision_pendiente = None
    registrar_evento(tesis, "rechazo", motivo + " El tesista debe iniciar un nuevo trámite con otro tema.", usuario)
    _notificar_estudiantes(tesis, "Su tesis fue rechazada", motivo)


def decision_decano(tesis, decision, sustento, usuario):
    _abierta(tesis)
    if tesis.decision_pendiente != "decano":
        raise TesisError("No hay una decisión pendiente.")
    if not (sustento or "").strip():
        raise TesisError("Registre el sustento de la decisión.")
    if decision == "rechazar":
        _rechazar(tesis, f"Decisión del Decano: {sustento.strip()}", usuario)
    elif decision == "dirimente":
        tesis.decision_pendiente = "dirimente"
        registrar_evento(tesis, "decano", f"El Decano dispone designar dirimente: {sustento.strip()}", usuario)
    elif decision == "continuar":
        tesis.decision_pendiente = None
        registrar_evento(tesis, "decano", f"El Decano / comisión dispone continuar: {sustento.strip()}", usuario)
    else:
        raise TesisError("Decisión no válida.")


# ----------------------------------------------------------------------
# Resoluciones, sustentacion y cierre
# ----------------------------------------------------------------------
def registrar_resolucion(tesis, tipo, numero, fecha, usuario):
    _abierta(tesis)
    if tipo not in TIPOS_RESOLUCION:
        raise TesisError("Tipo de resolución no válido.")
    if not (numero or "").strip() or not fecha:
        raise TesisError("Indique número y fecha de la resolución.")
    if tipo == "inscripcion" and tesis.etapa != "inscripcion":
        raise TesisError("La inscripción del tema corresponde cuando el proyecto tiene dictamen suficiente.")
    if tipo == "ampliacion" and (tesis.etapa != "desarrollo" or tesis.plazo_ampliado):
        raise TesisError("Solo se puede ampliar una vez el plazo durante el desarrollo de la tesis (Art. 88).")
    if tipo == "apto" and tesis.etapa != "apto":
        raise TesisError("La declaración de apto corresponde tras el dictamen favorable de la tesis.")

    db.session.add(ResolucionTesis(tesis=tesis, tipo=tipo, numero=numero.strip(), fecha=fecha, registrada_por_id=usuario.id))
    if tipo == "inscripcion":
        tesis.fecha_inscripcion = fecha
        tesis.fecha_limite_entrega = _sumar_anio(fecha)
        tesis.etapa = "desarrollo"
        _notificar_estudiantes(tesis, "Tema de tesis inscrito", f"Tiene hasta el {tesis.fecha_limite_entrega:%d/%m/%Y} para presentar su tesis.")
    elif tipo == "ampliacion":
        tesis.fecha_limite_entrega = _sumar_anio(tesis.fecha_limite_entrega or fecha)
        tesis.plazo_ampliado = True
    registrar_evento(tesis, "resolucion", f"Resolución registrada: {TIPOS_RESOLUCION[tipo]} N.° {numero.strip()} del {fecha:%d/%m/%Y}.", usuario)


def _sumar_anio(f):
    try:
        return f.replace(year=f.year + 1)
    except ValueError:
        return f + timedelta(days=365)


def programar_sustentacion(tesis, fecha, lugar, modalidad, usuario):
    _abierta(tesis)
    if tesis.etapa not in ("apto", "sustentacion"):
        raise TesisError("La sustentación se programa con la tesis declarada apta.")
    if not tesis.resolucion("apto"):
        raise TesisError("Registre primero la resolución de declaración de apto (Art. 115).")
    jurado = tesis.jurado
    requeridos = 4 if tesis.regimen == "anterior" else objetivo_dictaminantes(tesis)
    if len([m for m in jurado if m.estado_designacion == "aceptado"]) < requeridos:
        raise TesisError("El jurado no está completo o tiene designaciones sin aceptar.")
    if fecha.hour < 7 or fecha.hour >= 18:
        raise TesisError("Las sustentaciones se programan entre las 7:00 y las 18:00 (Art. 123).")
    if tesis.etapa == "apto":
        tesis.numero_sustentacion += 1
    tesis.fecha_sustentacion, tesis.lugar_sustentacion = fecha, (lugar or "").strip() or None
    tesis.modalidad_sustentacion = modalidad if modalidad in ("presencial", "virtual") else "presencial"
    tesis.etapa = "sustentacion"
    presidente, secretario = tesis.presidente, tesis.secretario
    registrar_evento(tesis, "sustentacion",
                     f"Sustentación {tesis.modalidad_sustentacion} programada el {fecha:%d/%m/%Y %H:%M}. "
                     f"Preside {presidente.docente.nombre_completo}; secretario(a) {secretario.docente.nombre_completo if secretario else '-'}.",
                     usuario)
    _notificar_estudiantes(tesis, "Sustentación programada", f"{fecha:%d/%m/%Y %H:%M} · {tesis.lugar_sustentacion or tesis.modalidad_sustentacion}")
    for m in jurado:
        _notificar_miembro(m, f"Sustentación {tesis.codigo}: {fecha:%d/%m/%Y %H:%M}", tesis.lugar_sustentacion)


def calcular_nota_final(notas):
    """Art. 130: se descarta la nota que difiere en 4 o mas de la mas proxima; promedio redondeado a favor."""
    notas = sorted(float(n) for n in notas)
    validas = []
    for i, n in enumerate(notas):
        otras = notas[:i] + notas[i + 1:]
        if otras and min(abs(n - o) for o in otras) >= 4:
            continue
        validas.append(n)
    if not validas:
        validas = notas
    promedio = sum(validas) / len(validas)
    final = int(promedio + 0.5)
    descartadas = [n for n in notas if n not in validas]
    return final, descartadas


def calificacion_texto(nota):
    if nota < 14:
        return "Desaprobado"
    if nota <= 16:
        return "Aprobado"
    if nota <= 18:
        return "Aprobado con distinción"
    return "Aprobado con excelencia y felicitación pública"


def registrar_notas(tesis, notas, con_observaciones, usuario):
    """notas: {miembro_id: nota}. Aplica Art. 129-134."""
    _abierta(tesis)
    if tesis.etapa != "sustentacion":
        raise TesisError("No hay una sustentación programada.")
    jurado = tesis.jurado
    valores = []
    for m in jurado:
        n = notas.get(m.id)
        if n is None or not 0 <= n <= 20:
            raise TesisError(f"Registre la nota (0 a 20) de {m.docente.nombre_completo}.")
        m.nota_sustentacion = n
        valores.append(n)
    final, descartadas = calcular_nota_final(valores)
    tesis.nota_sustentacion = final
    tesis.calificacion = calificacion_texto(final)
    detalle = f"Nota final {final} ({tesis.calificacion})" + (f"; nota(s) descartada(s) por discordancia: {', '.join(f'{d:g}' for d in descartadas)}" if descartadas else "")
    if final < 14:
        if tesis.numero_sustentacion >= 2:
            _rechazar(tesis, f"Desaprobado en segunda sustentación. {detalle} (Art. 134).", usuario)
        else:
            tesis.etapa = "apto"
            registrar_evento(tesis, "sustentacion", f"Sustentación desaprobada. {detalle}. Puede solicitar segunda sustentación en 90 días (Art. 134).", usuario)
            _notificar_estudiantes(tesis, "Resultado de sustentación: desaprobado", "Puede solicitar una segunda sustentación en un plazo de 90 días.")
        return final
    if con_observaciones:
        tesis.etapa = "observaciones"
        limite = calendario.sumar_habiles(date.today(), parametros.obtener("plazo_observaciones_sustentacion"))
        registrar_evento(tesis, "sustentacion", f"Sustentación aprobada con observaciones. {detalle}. Plazo para subsanar: {limite:%d/%m/%Y} (Art. 132).", usuario)
        _notificar_estudiantes(tesis, f"Sustentación aprobada: {final}", f"Levante las observaciones del jurado hasta el {limite:%d/%m/%Y}.")
    else:
        tesis.etapa = "titulado"
        registrar_evento(tesis, "sustentacion", f"Sustentación aprobada. {detalle}.", usuario)
        _notificar_estudiantes(tesis, f"¡Felicitaciones! Sustentación aprobada con {final}", tesis.calificacion)
    return final


def conformidad_observaciones(tesis, usuario):
    if tesis.etapa != "observaciones":
        raise TesisError("No hay observaciones de sustentación pendientes.")
    tesis.etapa = "titulado"
    registrar_evento(tesis, "conformidad", "El jurado dio conformidad al levantamiento de observaciones de la sustentación.", usuario)
    _notificar_estudiantes(tesis, "Conformidad del jurado registrada", "Su proceso de tesis está concluido.")


def anular(tesis, motivo, usuario):
    if not (motivo or "").strip():
        raise TesisError("Indique el motivo.")
    tesis.etapa = "anulada"
    registrar_evento(tesis, "anulacion", f"Tesis anulada: {motivo.strip()}", usuario)


# ----------------------------------------------------------------------
# Control de plazos (se ejecuta al abrir las vistas de gestion)
# ----------------------------------------------------------------------
def revisar_plazos(usuario=None):
    """Designaciones sin respuesta en plazo -> impedimento automatico y reposicion.
    Devuelve alertas: dictamenes vencidos y con mas de N dias calendario sin respuesta."""
    from models import Tesis

    hoy = date.today()
    plazo_aceptar = parametros.obtener("plazo_aceptar_designacion")
    dias_reemplazo = parametros.obtener("dias_reemplazo_sin_dictamen")
    alertas = []
    cambios = False
    for m in TesisMiembro.query.join(Tesis).filter(TesisMiembro.estado_designacion == "propuesto",
                                                    Tesis.etapa.notin_(("titulado", "rechazada", "anulada"))).all():
        if calendario.sumar_habiles(m.fecha_designacion, plazo_aceptar) < hoy:
            m.estado_designacion = "impedimento"
            m.fecha_respuesta = datetime.now()
            m.motivo_impedimento = f"Sin respuesta en {plazo_aceptar} días hábiles"
            registrar_evento(m.tesis, "impedimento", f"{m.docente.nombre_completo} no respondió su designación en plazo; se propone a otro docente.", usuario)
            _reponer(m.tesis, m.rol, usuario)
            cambios = True
    for d in Dictamen.query.join(Tesis).filter(Dictamen.resultado.is_(None),
                                               Tesis.etapa.notin_(("titulado", "rechazada", "anulada"))).all():
        if (hoy - d.inicio).days > dias_reemplazo:
            alertas.append({"tipo": "reemplazo", "dictamen": d,
                            "texto": f"{d.miembro.docente.nombre_completo} lleva {(hoy - d.inicio).days} días sin dictaminar {d.tesis.codigo}: puede reemplazarse (Art. 84/110)."})
        elif hoy > d.limite:
            alertas.append({"tipo": "vencido", "dictamen": d,
                            "texto": f"Dictamen vencido: {d.miembro.docente.nombre_completo} en {d.tesis.codigo} (límite {d.limite:%d/%m/%Y})."})
    if cambios:
        db.session.commit()
    return alertas
