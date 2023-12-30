#!/usr/bin/env sh

# The intention of this script is to prepare the environment. The necessary
# tools are Python3 and then some core packages depending on the platform.
#
# It should only use 'sh' capabilities in case 'bash' is not available.

echo "Running prepare-environment.sh"

ACTIONS_DIR="$(dirname $0)"
SUDO_COMMAND=""
BUILD_HOST_OS="$(uname)"

if [ -x "$(command -v sudo)" ]; then
  SUDO_COMMAND="sudo"
fi

if [ "$BUILD_HOST_OS" = "NetBSD" ]; then
  if [ -z "$PKG_PATH" ]; then
    echo "PKG_PATH was not set, setting it up..."
    PKG_PATH="http://cdn.netbsd.org/pub/pkgsrc/packages/NetBSD/$(uname -p)/$(uname -r|cut -f '1 2' -d.)/All"
    export PKG_PATH
  fi
fi

echo "PATH=$PATH"
echo "BUILD_HOST_OS=$BUILD_HOST_OS"
echo "SUDO_COMMAND=$SUDO_COMMAND"
echo "PKG_PATH=$PKG_PATH"

if [ "$BUILD_HOST_OS" = "NetBSD" ]; then
  if ! [ -z "$CI_NETBSD_USE_PKGIN" ]; then
    if ! [ -x "$(command -v pkgin)" ]; then
      echo "Trying to install 'pkgin' as it's not installed"
      $SUDO_COMMAND pkg_add -I pkgin
      $SUDO_COMMAND pkgin update
    fi
  fi
fi

set -e

if ! [ -x "$(command -v python3)" ]; then
  if [ "$BUILD_HOST_OS" = "FreeBSD" ]; then
    echo "Trying to install 'python3' as it's not installed"
    $SUDO_COMMAND pkg install -y python3
  fi

  if [ "$BUILD_HOST_OS" = "OpenBSD" ]; then
    echo "Trying to install 'python3' as it's not installed"
    $SUDO_COMMAND pkg_add -I python3
  fi

  if [ "$BUILD_HOST_OS" = "NetBSD" ]; then
    echo "Trying to install 'python3' as it's not installed"
    if ! [ -z "$CI_NETBSD_USE_PKGIN" ]; then
      $SUDO_COMMAND pkgin -y install python310
    else
      $SUDO_COMMAND pkg_add -I python310
    fi
    ln -s /usr/pkg/bin/python3.10 $ACTIONS_DIR/python3
  fi

  if [ "$BUILD_HOST_OS" = "Linux" ]; then
    $SUDO_COMMAND apt-get update
    $SUDO_COMMAND apt-get install -qq python3
  fi
fi
