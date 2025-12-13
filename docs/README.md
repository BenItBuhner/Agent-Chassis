# Mintlify Documentation

This directory contains the Mintlify documentation for Agent Chassis.

## Setup

1. **Install Mintlify CLI:**
   ```bash
   npm i -g mint
   ```

2. **Export OpenAPI spec (required for API Reference):**
   
   **Option A: Using the export script (recommended):**
   ```bash
   # Make sure server is running first
   uv run uvicorn app.main:app --reload
   
   # In another terminal, export the spec
   python docs/export-openapi.py
   ```
   
   **Option B: Using curl:**
   ```bash
   curl http://localhost:8000/api/v1/openapi.json > docs/openapi.json
   ```

3. **Start local development server:**
   ```bash
   cd docs
   mint dev
   ```

   Visit `http://localhost:3000` to preview your documentation.

## Structure

- `docs.json` - Mintlify configuration
- `*.mdx` - Documentation pages
- `openapi.json` - OpenAPI specification (exported from server)

## Deployment

Push the `docs/` directory to GitHub and connect it to Mintlify via the GitHub App.

## Known limitations / follow-ups

- MCP OAuth currently requires pre-seeded tokens; interactive callbacks are not implemented yet.
- User auth requires Redis + Postgres connectivity; when disabled, auth endpoints return 503.
- Access control intentionally lets blacklist override even the owner; revisit if requirements change.