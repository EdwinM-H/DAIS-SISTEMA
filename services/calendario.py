"""Dias habiles para los plazos de tesis.

Segun el Reglamento (Art. 79, 104 y Disposicion Final Cuarta) los plazos solo corren durante el
semestre academico: no cuentan fines de semana, feriados ni el periodo vacacional (dias fuera de
las fechas de inicio/fin de los semestres registrados). Si ningun semestre tiene fechas, solo se
descuentan fines de semana y feriados.
"""

from datetime import date, datetime, timedelta

from models import Feriado, Semestre


def _contexto():
    feriados = {f.fecha for f in Feriado.query.all()}
    periodos = [(s.fecha_inicio, s.fecha_fin) for s in Semestre.query.all() if s.fecha_inicio and s.fecha_fin]
    return feriados, periodos


def _es_habil(d, feriados, periodos):
    if d.weekday() >= 5 or d in feriados:
        return False
    if periodos and not any(ini <= d <= fin for ini, fin in periodos):
        return False
    return True


def es_habil(d):
    feriados, periodos = _contexto()
    return _es_habil(d, feriados, periodos)


def _a_fecha(valor):
    return valor.date() if isinstance(valor, datetime) else valor


def sumar_habiles(desde, dias):
    """Fecha limite: 'dias' habiles contados desde el dia siguiente a 'desde'."""
    feriados, periodos = _contexto()
    d = _a_fecha(desde)
    contados = 0
    limite = 0
    while contados < dias and limite < 2000:
        d += timedelta(days=1)
        limite += 1
        if _es_habil(d, feriados, periodos):
            contados += 1
    return d


def habiles_entre(desde, hasta):
    """Dias habiles transcurridos despues de 'desde' hasta 'hasta' inclusive."""
    feriados, periodos = _contexto()
    d, fin = _a_fecha(desde), _a_fecha(hasta)
    n = 0
    while d < fin:
        d += timedelta(days=1)
        if _es_habil(d, feriados, periodos):
            n += 1
    return n


def semaforo(inicio, limite, hoy=None):
    """'verde' | 'amarillo' (ultimo tercio del plazo) | 'rojo' (vencido)."""
    hoy = hoy or date.today()
    if hoy > limite:
        return "rojo"
    total = max(habiles_entre(inicio, limite), 1)
    usados = habiles_entre(inicio, hoy)
    return "amarillo" if usados >= total * 2 / 3 else "verde"
