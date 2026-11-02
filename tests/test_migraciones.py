"""Las migraciones no deben perder datos.

En SQLite los cambios de tabla recrean la tabla; con las claves foraneas activas eso dispararia
ON DELETE CASCADE / SET NULL y borraria evaluaciones, criterios o vinculos de cuentas.
"""

import os

import sqlalchemy as sa
from flask_migrate import upgrade

from app import create_app
from models import db

PRIMERA_REVISION = "62b7ebd1e0cb"
DIR_MIGRACIONES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def test_migraciones_conservan_datos_y_vinculos(tmp_path):
    ruta = tmp_path / "migracion.db"
    app = create_app("testing", SQLALCHEMY_DATABASE_URI=f"sqlite:///{ruta}")
    with app.app_context():
        upgrade(directory=DIR_MIGRACIONES, revision=PRIMERA_REVISION)
        with db.engine.begin() as con:
            con.execute(sa.text("INSERT INTO semestres (id, codigo, anio, periodo, activo, publicado) VALUES (1, '2026-II', 2026, 'II', 1, 0)"))
            con.execute(sa.text("INSERT INTO docentes (id, codigo, nombres, apellidos, nombre_normalizado, escuela, estado) "
                                "VALUES (1, 'DOC-0001', 'Ana', 'Quispe', 'ANA QUISPE', 'EPIS', 'activo')"))
            con.execute(sa.text("INSERT INTO usuarios (id, username, password_hash, nombre_completo, rol, docente_id, activo, debe_cambiar_password) "
                                "VALUES (1, 'aquispe', 'x', 'Ana Quispe', 'docente', 1, 1, 0)"))
            con.execute(sa.text("INSERT INTO docentes_semestre (docente_id, semestre_id) VALUES (1, 1)"))
            con.execute(sa.text("INSERT INTO evaluaciones (docente_id, semestre_id, encuesta, normas, autoevaluacion, promedio_final, editado_manual) "
                                "VALUES (1, 1, 8.5, 9.0, 10, 9.0, 0)"))
            con.execute(sa.text("INSERT INTO criterios_norma (docente_id, semestre_id, reuniones) VALUES (1, 1, 15)"))
            con.execute(sa.text("INSERT INTO capacitaciones (docente_id, nombre, anio, estado_validacion, origen) "
                                "VALUES (1, 'Curso', 2025, 'validado', 'excel')"))

        upgrade(directory=DIR_MIGRACIONES)   # hasta la ultima version

        with db.engine.connect() as con:
            def contar(tabla):
                return con.execute(sa.text(f"SELECT COUNT(*) FROM {tabla}")).scalar()

            assert con.execute(sa.text("SELECT docente_id FROM usuarios WHERE username = 'aquispe'")).scalar() == 1
            for tabla in ("docentes_semestre", "evaluaciones", "criterios_norma", "capacitaciones"):
                assert contar(tabla) == 1, tabla
            assert contar("temas_investigacion") == 53
            assert con.execute(sa.text("PRAGMA foreign_key_check")).fetchall() == []
            # Tras migrar, la integridad referencial vuelve a estar activa
            assert con.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
        db.session.remove()
        db.engine.dispose()
