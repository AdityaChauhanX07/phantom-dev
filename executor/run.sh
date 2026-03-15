#!/bin/bash
# Wrapper script to run phantom.py

cd "$(dirname "$0")"
export PHANTOM_MODE=cloud
python3 ./phantom.py "$@"
