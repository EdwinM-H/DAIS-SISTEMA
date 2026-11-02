from flask import Blueprint, render_template, redirect, session
from flask_login import login_required, current_user

from routes.auth import destino_inicio
from services.dashboard_service import get_dashboard_stats

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    if not current_user.es_gestion:
        return redirect(destino_inicio(current_user))
    stats = get_dashboard_stats(session.get("semestre_id"))
    return render_template("dashboard.html", stats=stats)
