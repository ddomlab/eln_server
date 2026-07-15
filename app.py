from flask import Flask, request

from web.automation_api import automation_bp
from web.interface import interface_bp

app = Flask(__name__)

app.register_blueprint(interface_bp)
app.register_blueprint(automation_bp)

# PTH tracking is a separate project; its blueprint is registered here when its
# files (pth_server.py etc.) are present alongside app.py, and skipped otherwise.
try:
    import pth_server
    app.register_blueprint(pth_server.pth_bp)
    pth_server.init_app_db(app)
except ImportError:
    print("pth_server not found, skipping PTH blueprint")


@app.errorhandler(404)
def not_found(e):
    return f"404 Not Found: {request.path}", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
