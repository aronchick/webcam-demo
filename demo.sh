#!/bin/bash
# Thin wrapper for backward compatibility - delegates to demo.py
exec uv run -s demo.py "$@"
