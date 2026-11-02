# DAIS – Sistema de Gestion Docente (EPIS · UAC)

Sistema web para la Direccion del DAIS: evaluacion integral docente, portal del docente
(resultados, puntos de mejora, capacitaciones y publicaciones), gestion de tesis y portal
del estudiante.

## Instalacion

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # edite SECRET_KEY y, opcionalmente, ADMIN_PASSWORD
venv\Scripts\flask --app app init-db --semestre 2026-II --importar
venv\Scripts\flask --app app run
```

`init-db` aplica las migraciones, crea las cuentas `directora` y `practicante` (muestra sus
contrasenas temporales en consola) y, con `--importar`, carga el Excel oficial de `data/`.

### Comandos utiles

| Comando | Uso |
|---|---|
| `flask --app app db upgrade` | Aplica migraciones pendientes de la base de datos |
| `flask --app app db migrate -m "mensaje"` | Genera una migracion tras modificar `models/` |
| `flask --app app importar-excel 2026-II` | Importa la Ficha Integral en un semestre |
| `flask --app app crear-cuentas-docentes` | Crea cuentas para todos los docentes sin acceso |
| `flask --app app reset-password <usuario>` | Genera una contrasena temporal |
| `venv\Scripts\python -m pytest` | Ejecuta las pruebas automaticas |

## Roles

| Rol | Puede |
|---|---|
| Director(a) / Administrador | Todo: usuarios, publicar resultados, asignar tesis, validar produccion |
| Operador | Importar datos, registrar/corregir notas, validar produccion, generar fichas |
| Docente | Ver su puesto y puntos de mejora (semestres publicados), registrar capacitaciones y publicaciones con archivos, revisar/dictaminar sus tesis |
| Estudiante | Seguir el avance de su tesis, ver observaciones y subir versiones corregidas |

Toda cuenta nueva o restablecida usa una contrasena temporal que debe cambiarse al primer ingreso.

## Proceso de evaluacion

* Escala unica 0–10. Promedio final = Encuesta × 40% + Normas × 40% + Autoevaluacion × 20%.
* Normas = suma de 7 criterios (reuniones 15, silabos 20, notas 15, horas lectivas 20,
  puntualidad 15, ERP 10, delegados 5) / 10.
* Clasificacion oficial del Excel; si falta: Excelente ≥ 9, Muy Bueno ≥ 8, Bueno ≥ 7, Regular ≥ 6.
* Ranking con empates compartidos (1, 2, 2, 4) — el mismo en dashboard, fichas y portal docente.
* Los docentes ven sus resultados solo cuando la Direccion **publica** el semestre (Semestres).

## Tesis

Registro → asesor → dictaminantes (max. 3, el asesor no puede dictaminar) → el estudiante sube su
documento → cada dictaminante da *visto bueno* u *observa* → una nueva version reabre las revisiones
observadas → con todos los vistos buenos queda en *dictamen favorable* → sustentacion programada →
sustentada. Cada paso queda en la bitacora y se notifica a los involucrados.

## Estructura

```
app.py, config.py, commands.py, utils.py
models/      SQLAlchemy (con restricciones CHECK, claves foraneas y migraciones en migrations/)
services/    logica: evaluacion_service, excel_service, ficha_service, tesis_service, ...
routes/      blueprints por modulo (gestion, portal_docente, portal_estudiante, tesis, ...)
templates/   Jinja2 (_macros.html, _analisis.html, _tesis_seguimiento.html compartidos)
storage/     archivos subidos (certificados, tesis, dictamenes) — no se versiona
tests/       pytest
```
