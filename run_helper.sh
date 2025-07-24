#!/bin/bash
# Helper script to ensure commands run from correct directory
# Usage: ./run_helper.sh "command to run"

cd /home/svend/shear-app
exec "$@"
