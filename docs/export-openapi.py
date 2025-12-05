#!/usr/bin/env python3
"""
Export OpenAPI specification from FastAPI server to docs/openapi.json

Usage:
    python docs/export-openapi.py

Or with server running:
    curl http://localhost:8000/api/v1/openapi.json > docs/openapi.json
"""

import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    print("Error: httpx not installed. Install with: uv add httpx")
    sys.exit(1)

OPENAPI_URL = "http://localhost:8000/api/v1/openapi.json"
OUTPUT_FILE = Path(__file__).parent / "openapi.json"


def main():
    """Export OpenAPI spec from running server."""
    print(f"Fetching OpenAPI spec from {OPENAPI_URL}...")

    try:
        response = httpx.get(OPENAPI_URL, timeout=10.0)
        response.raise_for_status()
        spec = response.json()
        source = f"server at {OPENAPI_URL}"
    except Exception as http_error:
        print(f"HTTP fetch failed ({http_error}). Falling back to local app import...")
        try:
            from app.main import app
        except Exception as import_error:
            print("Error: Could not import FastAPI app for offline export.")
            print(import_error)
            sys.exit(1)

        try:
            spec = app.openapi()
            source = "local app import (offline)"
        except Exception as openapi_error:
            print("Error: Failed to generate OpenAPI spec from app.")
            print(openapi_error)
            sys.exit(1)

    # Write to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    print(f"✓ OpenAPI spec exported to {OUTPUT_FILE} (source: {source})")
    print(f"  Total endpoints: {len(spec.get('paths', {}))}")


if __name__ == "__main__":
    main()
