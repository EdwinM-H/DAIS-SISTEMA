MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]


def fecha_larga(f):
    return f"{f.day} de {MESES[f.month - 1]} de {f.year}"
