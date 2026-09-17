import os
from flask import Flask
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    os.makedirs(app.config["DATA_DIR"], exist_ok=True)

    from app.routes.page_routes import page_bp
    from app.routes.project_routes import project_bp
    from app.routes.network_routes import network_bp
    from app.routes.meta_routes import meta_bp
    from app.routes.scenario_routes import scenario_bp
    from app.routes.optimize_routes import optimize_bp, runs_bp
    from app.routes.whatif_routes import whatif_bp
    from app.routes.simulation_routes import simulation_bp
    from app.routes.analytics_routes import analytics_bp
    from app.routes.report_routes import report_bp
    from app.routes.excel_routes import excel_bp
    from app.routes.assumption_routes import assumption_bp

    app.register_blueprint(page_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(network_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(scenario_bp)
    app.register_blueprint(optimize_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(whatif_bp)
    app.register_blueprint(simulation_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(excel_bp)
    app.register_blueprint(assumption_bp)

    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Not found"}, 404

    @app.errorhandler(500)
    def server_error(e):
        return {"error": "Internal server error"}, 500

    return app
