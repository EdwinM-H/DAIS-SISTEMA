from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from models import db, Semestre, Evaluacion, DocenteSemestre, Usuario
from utils import gestion_required, direccion_required, notificar

semestres_bp = Blueprint("semestres", __name__)


@semestres_bp.route("/semestres")
@gestion_required
def index():
    semestres = Semestre.ordenados()
    conteos = dict(db.session.query(Evaluacion.semestre_id, db.func.count(Evaluacion.id)).group_by(Evaluacion.semestre_id).all())
    docentes = dict(db.session.query(DocenteSemestre.semestre_id, db.func.count(DocenteSemestre.id)).group_by(DocenteSemestre.semestre_id).all())
    return render_template("semestres/index.html", semestres=semestres, conteos=conteos, docentes=docentes)


@semestres_bp.route("/semestres/crear", methods=["POST"])
@gestion_required
def crear():
    datos = Semestre.parsear_codigo(f"{request.form.get('anio', '').strip()}-{request.form.get('periodo', '').strip()}")
    if not datos:
        flash("Datos invalidos. El anio debe ser 20XX y el periodo I o II.", "danger")
        return redirect(url_for("semestres.index"))
    codigo = f"{datos[0]}-{datos[1]}"
    if Semestre.query.filter_by(codigo=codigo).first():
        flash(f"El semestre {codigo} ya existe.", "warning")
        return redirect(url_for("semestres.index"))
    sem = Semestre.crear(*datos)
    db.session.add(sem)
    db.session.commit()
    session["semestre_id"], session["semestre_codigo"] = sem.id, sem.codigo
    flash(f"Semestre {codigo} creado y seleccionado como semestre de trabajo.", "success")
    return redirect(url_for("semestres.index"))


@semestres_bp.route("/semestres/<int:semestre_id>/activar", methods=["POST"])
@direccion_required
def activar(semestre_id):
    sem = db.get_or_404(Semestre, semestre_id)
    Semestre.query.update({"activo": False})
    sem.activo = True
    db.session.commit()
    session["semestre_id"], session["semestre_codigo"] = sem.id, sem.codigo
    flash(f"{sem.codigo} es ahora el semestre vigente del sistema.", "success")
    return redirect(url_for("semestres.index"))


@semestres_bp.route("/semestres/<int:semestre_id>/publicar", methods=["POST"])
@direccion_required
def publicar(semestre_id):
    """Publica (o retira) los resultados para que los docentes los vean en su portal."""
    sem = db.get_or_404(Semestre, semestre_id)
    if not sem.publicado and sem.estado_resultados != "vigente":
        flash("Primero calcule (o recalcule) los resultados en Proceso de evaluacion.", "warning")
        return redirect(url_for("semestres.index"))
    sem.publicado = not sem.publicado
    if sem.publicado:
        ids = [p.docente_id for p in DocenteSemestre.query.filter_by(semestre_id=sem.id)]
        for u in Usuario.query.filter(Usuario.docente_id.in_(ids), Usuario.activo.is_(True)).all():
            notificar(u, f"Resultados de evaluacion {sem.codigo} publicados",
                      "Ya puede revisar su puesto y sus puntos de mejora.", "/docente")
        flash(f"Resultados de {sem.codigo} publicados para los docentes.", "success")
    else:
        flash(f"Resultados de {sem.codigo} ocultados para los docentes.", "info")
    db.session.commit()
    return redirect(url_for("semestres.index"))
