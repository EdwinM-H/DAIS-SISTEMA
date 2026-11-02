from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# Convencion de nombres para que las migraciones (Alembic) generen
# nombres de restricciones estables, tambien en SQLite.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas(dbapi_conn, _record):
    """SQLite no aplica FOREIGN KEY / ON DELETE CASCADE salvo que se active por conexion."""
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class TimestampMixin:
    creado_en = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    actualizado_en = db.Column(
        db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now()
    )


from models.usuario import Usuario, Notificacion, ROLES, ROLES_GESTION, ROLES_DIRECCION  # noqa: E402
from models.semestre import Semestre  # noqa: E402
from models.docente import Docente, DocenteSemestre, normalizar_nombre  # noqa: E402
from models.evaluacion import Evaluacion, CriterioNorma, CRITERIOS_NORMA, clasificar  # noqa: E402
from models.importacion import Importacion  # noqa: E402
from models.documento import DocumentoGenerado  # noqa: E402
from models.produccion import Capacitacion, Investigacion, ESTADOS_VALIDACION  # noqa: E402
from models.tesis import (  # noqa: E402
    Estudiante, Tesis, TesisMiembro, TesisVersion, TesisEvento,
    ESTADOS_TESIS, ROLES_TESIS, ESTADOS_REVISION,
)
