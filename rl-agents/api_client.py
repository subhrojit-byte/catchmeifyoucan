"""Compatibility name for the shared CatchMeIfYouCan API client."""

try:
    from .client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError
except ImportError:  # Supports running modules directly from rl-agents.
    from client import CatchMeIfYouCanApiClient, CatchMeIfYouCanApiError

__all__ = ["CatchMeIfYouCanApiClient", "CatchMeIfYouCanApiError"]
