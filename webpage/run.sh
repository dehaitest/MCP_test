#!/bin/bash

echo "Starting local web server for AI Agents Academic Works website..."
echo "Navigate to http://localhost:8000 in your browser to view the site."
echo "Press Ctrl+C to stop the server."
echo ""

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Change to the directory of this script
cd "$DIR"

# Check if Python 3 is available
if command -v python3 &>/dev/null; then
    python3 -m http.server 8000
# Fall back to Python 2 if Python 3 is not available
elif command -v python &>/dev/null; then
    python -m SimpleHTTPServer 8000
else
    echo "Error: Python is not installed. Please install Python to run this server."
    exit 1
fi 