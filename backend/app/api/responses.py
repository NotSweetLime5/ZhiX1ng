from app.core.serialization import serial


def ok(data=None):
    return {"code": 0, "message": "ok", "data": serial(data)}
