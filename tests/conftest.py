import os
import sys

import openpyxl
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from models import db, Usuario, Semestre  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    app = create_app("testing")
    app.config.update(
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        GENERATED_FOLDER=str(tmp_path / "generated"),
        STORAGE_FOLDER=str(tmp_path / "storage"),
    )
    for k in ("UPLOAD_FOLDER", "GENERATED_FOLDER", "STORAGE_FOLDER"):
        os.makedirs(app.config[k], exist_ok=True)
    with app.app_context():
        db.create_all()
        sem = Semestre.crear(2026, "II")
        sem.activo = True
        db.session.add(sem)
        for username, rol in (("directora", "director"), ("operador", "operador")):
            u = Usuario(username=username, nombre_completo=username.title(), rol=rol)
            u.set_password("Clave2026")
            db.session.add(u)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username, password="Clave2026"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=False)


@pytest.fixture()
def ficha_xlsx(tmp_path):
    """Excel con la misma estructura que la Ficha de Evaluacion Integral oficial."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "EVALUACION INTEGRAL"
    ws.append(["DATOS", None, None, "ENCUESTA ESTUDIANTES", "CUMPLIMIENTO DE NORMAS", None, None, None, None, None, None, None, None, "AUTOEVALUACION", "RESULTADO FINAL"])
    ws.append([None, None, None, "Peso total: 40%", "Peso total: 40%", None, None, None, None, None, None, None, None, "Peso total: 20%", "Promedio"])
    ws.append(["N", "APELLIDOS Y NOMBRES", "MODALIDAD", "NOTA\n/10", "Reuniones\n15%", "Silabos\n20%", "Notas/Config\n15%", "Hrs Lect.\n20%",
               "Puntual.\n10%", "ERP\n10%", "Delegado\n10%", "SUBTOTAL\n/100", "NOTA\n/10", "NOTA\n/10", "PROMEDIO\nFINAL /10", "CLASIFICACION", "POS."])
    ws.append([1, "ACURIO GUTIERREZ MARIA ISABEL", "Contratado", 8.24, 15, 20, 15, 16.67, 13.125, 10, 10, 99.795, 9.9795, 10, 9.2878, "Excelente", 1])
    ws.append([2, "ARDILES ROMERO VELIA", "Contratado", 7.85, 7.5, 20, 15, 9.34, 12.5625, 10, 10, 84.4025, 8.44025, 10, 8.5161, "Muy Bueno", 3])
    ws.append([3, "CUBA DEL CASTILLO MARIA YORNET", "Nombrado", 9.16, 15, 20, 15, 15, 7.25, 10, 9, 91.25, 9.125, 10, 9.314, "Excelente", 2])
    ws.append([4, "PEREZ ROJAS JUAN", "Contratado", 7.85, 7.5, 20, 15, 9.34, 12.5625, 10, 10, 84.4025, 8.44025, 10, 8.5161, "Muy Bueno", 3])
    ws.append([5, "MAL DATO PRUEBA", "Contratado", 12, 15, 20, 15, 20, 10, 10, 10, 100, 10, 10, 10, "Excelente", 0])
    ws.append([None, "PROMEDIO GENERAL", None, 8.5])

    cap = wb.create_sheet("CAPACITACIONES")
    cap.append(["N", "APELLIDOS Y NOMBRES", "Nombre de la Capacitacion", "Ano", "Horas"])
    cap.append([1, "ACURIO GUTIERREZ MARIA ISABEL", "Habilidades Blandas en el Aula", 2025, 10])
    cap.append([None, None, "Power BI Avanzado", 2026, 24])
    cap.append([2, "ARDILES ROMERO VELIA", "No tiene", None, None])

    inv = wb.create_sheet("INVESTIGACIONES")
    inv.append(["N", "APELLIDOS Y NOMBRES", "Nombre de Proyecto", "Ano", "Tipo de Investigacion", "SubTipo de Investigacion"])
    inv.append([1, "ACURIO GUTIERREZ MARIA ISABEL", "Modelamiento de indicadores", 2025, "Proyectos", "Investigacion y Desarrollo"])

    ruta = tmp_path / "uploads" / "abc12345_ficha.xlsx"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    wb.save(ruta)
    return str(ruta)
