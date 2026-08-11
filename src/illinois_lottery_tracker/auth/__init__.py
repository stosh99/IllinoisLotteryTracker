"""Authentication primitives and services.

Google/provider code is intentionally isolated from application sessions and
FastAPI route wiring.  Importing this package has no network or database side
effects.
"""

from .config import AuthSettings, load_auth_settings
from .types import AuthPrincipal, VerifiedIdentity

__all__ = ["AuthPrincipal", "AuthSettings", "VerifiedIdentity", "load_auth_settings"]
