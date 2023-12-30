#!/usr/bin/env sh

if ! [ -x "$(command -v python3)" ]; then
  sh ./prepare-environment.sh
fi

PYTHON_CMD="python3"
if ! [ -x "$(command -v python3)" ]; then
  PYTHON_CMD="python"
fi

$PYTHON_CMD action.py "$@"
