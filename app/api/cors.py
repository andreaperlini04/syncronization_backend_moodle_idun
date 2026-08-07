from flask import Flask, request


def register_cors(app: Flask) -> None:
    """Aggiunge gli header CORS necessari perché il JS del plugin Moodle
    (servito da un'origine diversa: server SUPSI remoto o container Docker
    locale) possa chiamare questo backend via fetch().

    Access-Control-Allow-Origin non ammette una lista: si confronta l'Origin
    della richiesta con quelle configurate e si risponde con quella che
    combacia."""

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in app.config["ALLOWED_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response