from flask import Blueprint, render_template
import logging

logger = logging.getLogger(__name__)

ui_bp = Blueprint('ui', __name__)

@ui_bp.route('/')
def index():
    # In a real scenario, we might want to pass some initial state or version
    return render_template('index.html', ui_version="3.0.0")
