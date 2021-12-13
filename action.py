import argparse
import json
import os
import platform
import subprocess


build_actions_root = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))

actions_config_name = "build-action-config.json"

ubuntu_test_toolchain_ppa = "ppa:ubuntu-toolchain-r/test"

default_valgrind_arguments = [
  "--leak-check=full",
  "--show-reachable=yes",
  "--track-origins=yes"
]

# Utilities
# ---------


def log(message):
  print(message, flush=True)


def pluralize(s, count):
  if count == 1:
    return s
  return s + "s"


def as_list(x):
  if isinstance(x, list):
    return x
  elif not x:
    return []
  else:
    return [x]


def read_json_file(file_name):
  with open(file_name, "r", encoding="utf-8") as f:
    return json.load(f)


def write_json_file(file_name, data):
  with open(file_name, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)


def run(args, cwd=None, env=None, check=True, sudo=False, print_command=True):
  if sudo:
    args = ["sudo"] + args

  if print_command:
    log(" ".join(args))

  return subprocess.run(args, cwd=cwd, env=env, check=check)


# Host OS & Architecture
# ----------------------


host_os = platform.system()


architecture_normalize_map = {
  "i386"   : "x86",
  "x86_64" : "x64",
  "x86-64" : "x64",
  "arm64"  : "aarch64"
}


architecture_vs_platform_map = {
  "x86"    : "Win32",
  "x64"    : "x64",
  "arm"    : "ARM",
  "aarch64": "ARM64"
}


def detect_architecture():
  return "x64"


def normalize_architecture(arch):
  arch = arch.lower()
  if arch in architecture_normalize_map:
    return architecture_normalize_map[arch]
  return arch


def scan_build_executable(compiler):
    if compiler.startswith("clang"):
      return compiler.replace("clang", "scan-build")
    else:
      return "scan-build"


# Prepare & Configure Utilities
# -----------------------------


def normalize_arguments(args):
  if args.architecture:
    args.architecture = normalize_architecture(args.architecture)
  else:
    args.architecture = detect_architecture()

  if not args.generator:
    if args.compiler == "vs2015":
      args.generator = "Visual Studio 14 2015"
    elif args.compiler == "vs2017":
      args.generator = "Visual Studio 15 2017"
    elif args.compiler == "vs2019":
      args.generator = "Visual Studio 16 2019"
    elif args.compiler == "vs2022":
      args.generator = "Visual Studio 17 2022"
    elif host_os == "Darwin":
      args.generator = "Unix Makefiles"
    else:
      args.generator = "Ninja"


# Prepare Step
# ------------


def prepare_step(args):
  """
  Prepare step is responsible for configuring the environment for the
  selected compiler, generator, and diagnostic options.

  NOTE: Prepare is a stateless step. It only configures the environment,
  but it doesn't create or use build directory. This is the main reason
  why some parameters must be repeatedly passed to the 'configure' step.
  """

  normalize_arguments(args)
  compiler = args.compiler
  generator = args.generator

  if host_os == "Windows":
    return

  if host_os == "Darwin":
    return

  if host_os == "Linux":
    if compiler.startswith("gcc"):
      compiler_package = compiler.replace("gcc", "g++")
    elif compiler.startswith("clang"):
      compiler_package = compiler
    else:
      raise ValueError("Invalid compiler: {}".format(compiler))

    apt_packages = [compiler_package]

    if generator == "Ninja":
      apt_packages.append("ninja-build")

    if args.architecture == "x86":
      run(["dpkg", "--add-architecture", "i386"], sudo=True)
      apt_packages.append("linux-libc-dev:i386")
      if compiler.startswith("gcc"):
        apt_packages.append(compiler_package + "-multilib")
      else:
        # Even clang requires this if libstdc++ is used.
        apt_packages.append("g++-multilib")

    if args.diagnostics == "valgrind":
      apt_packages.append("valgrind")

    if args.diagnostics == "scan-build":
      if compiler.startswith("clang"):
        apt_packages.append(compiler.replace("clang", "clang-tools"))
      else:
        apt_packages.append("clang-tools")

    run(["apt-add-repository", "-y", ubuntu_test_toolchain_ppa], sudo=True)
    run(["apt-get", "update", "-qq"], sudo=True)
    run(["apt-get", "install", "-qq"] + apt_packages, sudo=True)
    return

  raise ValueError("Unknown platform: {}".format(host_os))


# Configure Step
# --------------


def configure_step(args):
  """
  Configure step is responsible for configuring the project by using 'cmake'.

  Configure is responsible for the following:
    - Create build directory (see --build-dir argument).
    - Store the build configuration there so later steps can load it.
    - Invoke cmake to configure the build.
  """

  normalize_arguments(args)
  compiler = args.compiler
  generator = args.generator

  source_dir = args.source_dir
  build_dir = args.build_dir

  if not source_dir:
    source_dir = os.getcwd()
  else:
    source_dir = os.path.abspath(source_dir)

  if args.config:
    actions_config = read_json_file(args.config)
  else:
    actions_config = {}

  if args.problem_matcher:
    log("::add-matcher::" + os.path.join(build_actions_root, "problem-matcher-{}.json".format(args.problem_matcher)))

  cmd = []

  # Support scan-build diagnostics (static analysis).
  if args.diagnostics == "scan-build":
    cmd.append(scan_build_executable(compiler))

  cmd.extend(["cmake", source_dir, "-G", generator])
  env = os.environ.copy()

  if generator.startswith("Visual Studio"):
    cmd.extend(["-A", architecture_vs_platform_map[args.architecture]])
  else:
    if compiler.startswith("gcc"):
      cc_bin = compiler
      cxx_bin = compiler.replace("gcc", "g++")
    elif compiler.startswith("clang"):
      cc_bin = compiler
      cxx_bin = compiler.replace("clang", "clang++")
    else:
      raise ValueError("Invalid compiler: {}".format(compiler))

    env["CC"] = cc_bin
    env["CXX"] = cxx_bin

    if args.architecture == "x86":
      env["CFLAGS"] = "-m32"
      env["CXXFLAGS"] = "-m32"
      env["LDFLAGS"] = "-m32"

    if args.build_type:
      cmd.append("-DCMAKE_BUILD_TYPE=" + args.build_type)

  if args.build_defs:
    for build_def in args.build_defs.split(","):
      cmd.append("-D" + build_def)


  if args.diagnostics:
    diag_config = actions_config.get("diagnostics", {}).get(args.diagnostics, {})
    for dd in as_list(diag_config.get("definitions", [])):
      cmd.append("-D" + dd)

  # Create build directory and invoke cmake.
  os.makedirs(build_dir, exist_ok=True)
  run(cmd, cwd=build_dir, env=env)

  actions_config["build"] = {
    "build_tool": "cmake",
    "build_type": args.build_type,
    "build_defs": args.build_defs,
    "config": args.config,
    "compiler": compiler,
    "generator": generator,
    "diagnostics": args.diagnostics,
    "architecture": args.architecture,
  }

  # Store build configuration for later steps only if cmake succeeded.
  write_json_file(os.path.join(build_dir, actions_config_name), actions_config)


# Build Step
# ----------


def build_step(args):
  """
  Build step is responsible for building a previously configured project.
  """

  actions_config = read_json_file(os.path.join(args.build_dir, actions_config_name))
  build_dir = args.build_dir
  generator = actions_config["build"]["generator"]
  build_type = actions_config["build"]["build_type"]
  diagnostics = actions_config["build"]["diagnostics"]

  cmd = []

  if diagnostics == "scan-build":
    cmd.append(scan_build_executable(actions_config["build"]["compiler"]))

  cmd.extend(["cmake", "--build", build_dir, "--parallel"])

  if generator.startswith("Visual Studio"):
    cmd.extend(["--config", build_type, "--", "-nologo", "-v:minimal"])

  run(cmd)


# Test Step
# ---------


def test_step(args):
  """
  Test step is responsible for executing all tests and to fail if any test fails.
  """

  actions_config = read_json_file(os.path.join(args.build_dir, actions_config_name))
  build_dir = args.build_dir
  build_type = actions_config["build"]["build_type"]

  # Multi-configuration build uses a nested directory.
  if build_type and os.path.isdir(os.path.join(build_dir, build_type)):
    build_dir = os.path.join(build_dir, build_type)

  tests = actions_config.get("tests", [])
  failures = []

  for test in tests:
    cmd = test["cmd"]
    app = cmd[0]

    executable = os.path.abspath(os.path.join(build_dir, app))
    if host_os == "Windows":
      executable += ".exe"

    # Ignore tests, which were not built, because of disabled features.
    if os.path.isfile(executable):
      try:
        log("::group::" + " ".join(cmd))
        cmd[0] = executable

        if actions_config["build"]["diagnostics"] == "valgrind":
          valgrind_arguments = actions_config.get("valgrind_arguments", default_valgrind_arguments)
          cmd = ["valgrind"] + valgrind_arguments + cmd

        out = run(cmd, cwd=build_dir, check=False, print_command=False)
        if out.returncode != 0:
          log("Test returned {}".format(out.returncode))
          failures.append(app)
      except:
        failures.append(app)
        raise
      finally:
        log("::endgroup::")
    else:
      if test.get("optional", False) != True:
        log("Test {} not found and it's not optional.".format(app))
        failures.append(app)

  if failures:
    n = len(failures)
    log("{} {} out of {} failed: {}".format(n, pluralize("test", n), len(tests), ", ".join(failures)))
    exit(1)


# Main & Arguments
# ----------------


def create_argument_parser():
  parser = argparse.ArgumentParser(description="Step runner")

  # Step - must be always provided.
  parser.add_argument("--step", help="Step to execute (prepare|configure|build|test)")

  # Environment - Must be provided when invoking both 'prepare' and 'configure' steps.
  parser.add_argument("--config", default=None, help="Path to a JSON configuration.")
  parser.add_argument("--compiler", default="", help="C++ compiler to use")
  parser.add_argument("--diagnostics", default="", help="Diagnostics (valgrind|address|undefined)")
  parser.add_argument("--generator", default="", help="CMake generator to use")
  parser.add_argument("--architecture", default="default", help="Target architecture")

  # Build options - must be provided when invoking 'configure' step.
  parser.add_argument("--source-dir", default=".", help="Source directory")
  parser.add_argument("--build-type", default="", help="Build type (Debug|Release)")
  parser.add_argument("--build-defs", default="", help="Build definitions")
  parser.add_argument("--problem-matcher", default="", help="Whether to setup a problem matcher")

  # Build directory - must be provided when invoking 'configure', 'build', and 'test' steps.
  parser.add_argument("--build-dir", default="build", help="Build directory")

  return parser


def execute_step(args):
  if args.step == "prepare":
    prepare_step(args)
    exit(0)

  if args.step == "configure":
    configure_step(args)
    exit(0)

  if args.step == "build":
    build_step(args)
    exit(0)

  if args.step == "test":
    test_step(args)
    exit(0)

  raise ValueError("Unknown step: {}".format(step))


def main():
  args = create_argument_parser().parse_args()
  execute_step(args)


if __name__ == "__main__":
  main()
