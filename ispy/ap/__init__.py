"""Archipelago integration for the I Spy Spooky Mansion Deluxe port.

Layers (each importable without pygame, except `menu`/`hooks` which are added later):
    options   YAML / slot_data options
    data      item + location ID tables
    protocol  websocket + AP packet client
    state     received/checked bookkeeping and the yes/no rules the game hooks ask
"""
from .options import APOptions          # noqa: F401
from .state import APState              # noqa: F401
from .protocol import APClient          # noqa: F401
