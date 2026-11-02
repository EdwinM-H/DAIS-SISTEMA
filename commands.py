"""Comandos de consola:  flask --app app <comando>"""

import glob
import os
import shutil

import click
from flask import current_app

from models import db, Usuario, Semestre
from utils import generar_password


def _crear_usuario(username, nombre, rol, password=None):
    if Usuario.query.filter_by(username=username).first():
        return None
    password = password or generar_password()
    u = Usuario(username=username, nombre_completo=nombre, rol=rol, debe_cambiar_password=True)
    u.set_password(password)
    db.session.add(u)
    return password


def register_commands(app):
    @app.cli.command("init-db")
    @click.option("--semestre", default=None, help="Crea y activa este semestre (ej. 2026-II).")
    @click.option("--importar/--no-importar", default=False, help="Importa el Excel oficial de data/.")
    def init_db(semestre, importar):
        """Aplica las migraciones y crea las cuentas iniciales de gestion."""
        from flask_migrate import upgrade

        upgrade()
        creadas = []
        pwd = _crear_usuario("directora", "Directora DAIS", "director", current_app.config.get("ADMIN_PASSWORD"))
        if pwd:
            creadas.append(("directora", pwd))
        pwd = _crear_usuario("practicante", "Practicante DAIS", "operador")
        if pwd:
            creadas.append(("practicante", pwd))
        db.session.commit()
        for usuario, pwd in creadas:
            click.echo(f"Cuenta creada  usuario={usuario}  contrasena temporal={pwd}")

        sem = None
        if semestre:
            datos = Semestre.parsear_codigo(semestre)
            if not datos:
                raise click.BadParameter("Use el formato AAAA-I o AAAA-II")
            sem = Semestre.query.filter_by(codigo=semestre.upper()).first() or Semestre.crear(*datos)
            Semestre.query.update({"activo": False})
            sem.activo = True
            db.session.add(sem)
            db.session.commit()
            click.echo(f"Semestre {sem.codigo} activo.")

        if importar:
            if not sem:
                raise click.UsageError("Indique --semestre para importar el Excel.")
            _importar_excel(sem)
        click.echo("Base de datos lista.")

    @app.cli.command("importar-excel")
    @click.argument("semestre")
    @click.option("--archivo", default=None, help="Ruta del Excel (por defecto, el de data/).")
    def importar_excel(semestre, archivo):
        """Importa la Ficha de Evaluacion Integral en el SEMESTRE indicado."""
        sem = Semestre.query.filter_by(codigo=semestre.upper()).first()
        if not sem:
            raise click.UsageError(f"El semestre {semestre} no existe.")
        _importar_excel(sem, archivo)

    @app.cli.command("crear-cuentas-docentes")
    def crear_cuentas():
        """Crea cuentas para todos los docentes activos que aun no tienen una."""
        from services.cuentas_service import crear_cuentas_docentes

        for c in crear_cuentas_docentes():
            click.echo(f"{c['codigo']}\t{c['username']}\t{c['password']}\t{c['nombre']}")

    @app.cli.command("reset-password")
    @click.argument("username")
    def reset_password(username):
        """Genera una contrasena temporal para USERNAME."""
        from services.cuentas_service import restablecer_password

        u = Usuario.query.filter_by(username=username).first()
        if not u:
            raise click.UsageError("Usuario no encontrado.")
        pwd = restablecer_password(u)
        db.session.commit()
        click.echo(f"Nueva contrasena temporal para {username}: {pwd}")


def _importar_excel(sem, archivo=None):
    from services.excel_service import importar_ficha_integral

    if not archivo:
        candidatos = sorted(glob.glob(os.path.join(current_app.config["DATA_FOLDER"], "*.xlsx")))
        if not candidatos:
            raise click.UsageError("No hay archivos .xlsx en data/.")
        archivo = candidatos[0]
    temporal = os.path.join(current_app.config["UPLOAD_FOLDER"], "cli_" + os.path.basename(archivo))
    shutil.copyfile(archivo, temporal)
    try:
        res = importar_ficha_integral(temporal, sem.id, None)
    finally:
        os.remove(temporal)
    click.echo(
        f"Importados={res['importados']} actualizados={res['actualizados']} rechazados={res['rechazados']} "
        f"capacitaciones={res['capacitaciones']} investigaciones={res['investigaciones']}"
    )
    for e in res["errores"] + res["advertencias"]:
        click.echo(f"  - {e}")
