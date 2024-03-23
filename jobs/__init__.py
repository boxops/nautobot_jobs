"""The __init__.py module is required for Nautobot to load the jobs via Git."""

from .get_version import GetShowVersion

__all__ = [
    "GetShowVersion",
]
