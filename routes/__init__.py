from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.docentes import docentes_bp
from routes.importacion import importacion_bp
from routes.semestres import semestres_bp
from routes.seleccion import seleccion_bp
from routes.documentos import documentos_bp
from routes.ranking import ranking_bp
from routes.historial import historial_bp
from routes.usuarios import usuarios_bp
from routes.produccion import produccion_bp
from routes.tesis import tesis_bp
from routes.portal_docente import docente_bp
from routes.portal_estudiante import estudiante_bp
from routes.archivos import archivos_bp

BLUEPRINTS = (
    auth_bp, dashboard_bp, docentes_bp, importacion_bp, semestres_bp, seleccion_bp,
    documentos_bp, ranking_bp, historial_bp, usuarios_bp, produccion_bp, tesis_bp,
    docente_bp, estudiante_bp, archivos_bp,
)


def register_routes(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
