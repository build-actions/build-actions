#!/usr/bin/env sh

# The intention of this script is to install Python3 on various CI environments
# and VM images. It should only use 'sh' in case bash is not available (BSDs).

if [ -x "$(command -v python3)" ]; then
  echo "Python3 found, exiting..."
  exit 0
fi

ACTIONS_DIR="$(dirname $0)"
SUDO_COMMAND=""
BUILD_HOST_OS="$(uname)"

echo "PATH=$PATH"

if [ -x "$(command -v sudo)" ]; then
  SUDO_COMMAND="sudo"
fi

set -e

if [ "$BUILD_HOST_OS" = "FreeBSD" ]; then
  echo "Detected FreeBSD - trying to install python3"
  $SUDO_COMMAND pkg install -y python3
fi

if [ "$BUILD_HOST_OS" = "OpenBSD" ]; then
  echo "Detected OpenBSD - trying to install python3"
  $SUDO_COMMAND pkg_add -I python3
fi

if [ "$BUILD_HOST_OS" = "NetBSD" ]; then
  $SUDO_COMMAND pkg_add -I python310
  ln -s /usr/pkg/bin/python3.10 $ACTIONS_DIR/python3
fi
