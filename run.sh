#!/bin/bash
set -e

# Start the simple HTTP server on port 8080 via xvfb so SeleniumBase has a virtual display
echo "Starting gas price HTTP API server with xvfb..."
xvfb-run -a python3 main.py
