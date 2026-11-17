"""FastAPI application serving TraceGit Merkle Store, C++20 Diff/Bisect, CI Gate & React UI."""

from tracegit.api.app import create_app

__all__ = ["create_app"]
