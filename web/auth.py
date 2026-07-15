from flask import request

from eln_common.resourcemanage import Resource_Manager


def get_key() -> str:
    """
    Pulls the caller's eLabFTW API key from the request.
    Accepts an Authorization header (with or without a "Bearer " prefix) for API
    clients, falling back to the apiKey cookie set by the web interface.
    """
    key = request.headers.get("Authorization")
    if key:
        return key.removeprefix("Bearer ").strip()
    key = request.cookies.get("apiKey")
    if key is None:
        raise ValueError("No API key provided")
    return key


def rm() -> Resource_Manager:
    """
    Initialize a Resource_Manager with the caller's API key.
    Called in each route that needs to act on the ELN.
    """
    return Resource_Manager(key=get_key())
