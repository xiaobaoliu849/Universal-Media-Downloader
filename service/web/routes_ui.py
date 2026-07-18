import os
from flask import Blueprint, render_template
import logging

logger = logging.getLogger(__name__)

ui_bp = Blueprint('ui', __name__)

@ui_bp.route('/')
def index():
    from config import APP_VERSION, resource_path

    try:
        static_version = str(int(os.path.getmtime(resource_path(os.path.join('static', 'main.js')))))
    except Exception:
        static_version = APP_VERSION
    logger.info(f"[UI] index requested ui_version={APP_VERSION} static_version={static_version}")
    return render_template('index.html', ui_version=APP_VERSION, static_version=static_version)
