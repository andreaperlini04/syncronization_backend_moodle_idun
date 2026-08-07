from flask import jsonify


def error_response(code: str, message: str, status: int):
    """Formato uniforme per tutti gli errori dell'API:
    {"error": {"code": "...", "message": "..."}}
    """
    return jsonify({"error": {"code": code, "message": message}}), status
