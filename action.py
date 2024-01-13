#!/usr/bin/env python3

import argparse
import json
import os
import platform
import re
import subprocess
import time
import urllib
import urllib.request


build_actions_root = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))


# Constants & Features
# --------------------


actions_config_name = "build-action-config.json"

# LLVM provides its own APT repository that offers pre-built LLVM + clang. We have
# to cherry-pick the versions we want from LLVM APT vs Ubuntu test toolchain PPA.
apt_llvm_versions = ["16", "17"]
apt_llvm_repository_url = "https://apt.llvm.org"
apt_llvm_gpg_file_url = "https://apt.llvm.org/llvm-snapshot.gpg.key"

# Ubuntu offers a PPA test-toolchain, however, it's sometimes few versions behind.
apt_ubuntu_test_toolchain_ppa = "ppa:ubuntu-toolchain-r/test"

# Retry when apt-get fails with the following message (happens on CI occasionally).
apt_retry_patterns = [
  "Connection timed out",
  "Internal Server Error"
]

problem_matcher_definitions = {
  "compile"      : { "scope": "build"  , "provides": ["compile-gcc", "compile-msvc"] },
  "analyze-build": { "scope": "analyze", "provides": ["analyze-build"] },
  "asan"         : { "scope": "run"    , "provides": ["asan"] },
  "msan"         : { "scope": "run"    , "provides": ["msan"] },
  "ubsan"        : { "scope": "run"    , "provides": ["ubsan"] },
  "valgrind"     : { "scope": "run"    , "provides": ["valgrind-commons", "valgrind-memcheck"] }
}

# backward compatibility - use substitution to support old problem matcher names
problem_matcher_substitutions = { "cpp": "compile" }

default_valgrind_arguments = [
  "--leak-check=full",
  "--show-reachable=yes",
  "--track-origins=yes"
]

architecture_normalize_map = {
  "i386"   : "x86",
  "amd64"  : "x64",
  "x86_64" : "x64",
  "x86-64" : "x64",
  "arm/v6" : "arm",
  "arm/v7" : "arm",
  "arm/v8" : "arm",
  "arm64"  : "aarch64"
}

architecture_vs_platform_map = {
  "x86"    : "Win32",
  "x64"    : "x64",
  "arm"    : "ARM",
  "aarch64": "ARM64"
}


# Common Utilities
# ----------------


log_options = { "groups": False }

def log(message):
  print(message, flush=True)

def begin_group(group):
  if log_options["groups"]:
    log("::group::" + group)

def end_group(group):
  if log_options["groups"]:
    log("::endgroup::")

def pluralize(s, count):
  if count == 1:
    return s
  return s + "s"

def parse_key_value_data(content):
  d = {}
  r = re.compile("^(\\w+)\\s*=\\s*(.*)$")

  for line in content.split("\n"):
    line = line.strip()
    m = r.match(line)
    if m:
      key = m[1]
      value = m[2]
      if value.startswith('"') and value.endswith('"'):
          value = value[1:len(value)-1]
      d[key] = value

  return d

def as_list(x):
  if isinstance(x, list):
    return x
  elif not x:
    return []
  else:
    return [x]

def read_text_file(file_name):
  with open(file_name, "r", encoding="utf-8") as f:
    return f.read()

def read_json_file(file_name):
  with open(file_name, "r", encoding="utf-8") as f:
    return json.load(f)

def write_text_file(file_name, data):
  with open(file_name, "w", encoding="utf-8") as f:
    f.write(data)

def write_json_file(file_name, data):
  with open(file_name, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

def download_text_file(url, method="GET", encoding="utf-8"):
  try:
    req = urllib.request.Request(url=url, method=method)
    with urllib.request.urlopen(req) as f:
      return f.read().decode(encoding)
  except:
    return None

globals = {
  "sudo": None
}

def has_sudo():
  if globals["sudo"] is None:
    try:
      subprocess.run(["sudo", "--version"], check=True)
      globals["sudo"] = True
    except:
      globals["sudo"] = False
  return globals["sudo"]

def run(args, cwd=None, env=None, check=True, input=None, sudo=False, print_command=True, retry_patterns=None, retry_count=3):
  encoding = "utf-8"

  def decode_stdout_stderr(result):
    out = result.stdout.decode(encoding)
    err = result.stderr.decode(encoding)
    return (out, err)

  if sudo and has_sudo():
    args = ["sudo"] + args

  if input:
    input = input.encode(encoding)

  if print_command:
    log(" ".join(args))

  retry_count = max(retry_count, 1)

  for i in range(retry_count):
    try:
      result = subprocess.run(args, cwd=cwd, env=env, input=input, check=check, capture_output=True)
      out, err = decode_stdout_stderr(result)
      print(out)
      print(err)
      return result
    except subprocess.CalledProcessError as e:
      out, err = decode_stdout_stderr(e)
      retry_pattern_matched = None

      if retry_patterns:
        for retry_pattern in retry_patterns:
          if retry_pattern in out or retry_pattern in err:
            retry_pattern_matched = retry_pattern
            break

      if retry_pattern_matched and i < retry_count - 1:
        if print_command:
          log("Retrying command because of '{}' error (retry pattern matched)".format(retry_pattern_matched))
        time.sleep(1)
        continue

      print(out)
      print(err)
      raise e

def run_test(args):
  try:
    subprocess.run(args, check=True, capture_output=True)
    return True
  except:
    return False


# Host OS & Architecture Utilities
# --------------------------------


host_os = platform.system()

def is_root():
  return os.geteuid() == 0

def cpu_count():
  try:
    return len(os.sched_getaffinity(0))
  except:
    return os.cpu_count()

def detect_architecture():
  return "x64"

def normalize_architecture(arch):
  arch = arch.lower()
  if arch in architecture_normalize_map:
    return architecture_normalize_map[arch]
  return arch

def os_release_info():
  out = {
    "id": "",
    "name": "",
    "codename": "",
    "unstable": False
  }

  if host_os == "Linux":
    try:
      obj = parse_key_value_data(read_text_file("/etc/os-release"))

      for k, v in obj.items():
        if k == "ID":
          out["id"] = v
        elif k == "NAME":
          out["name"] = v
        elif k == "VERSION_CODENAME":
          out["codename"] = v
        elif k == "PRETTY_NAME":
          if v.endswith("/sid") or v.endswith("/testing"):
            out["unstable"] = True
    except:
      pass

  return out


# Build Utilities
# ---------------


def is_compiler_gcc(compiler):
  return compiler.startswith("gcc")

def is_compiler_clang(compiler):
  return compiler.startswith("clang")

def compiler_version(compiler):
  if compiler.startswith("gcc-"):
    return compiler[4:]

  if compiler.startswith("clang-"):
    return compiler[6:]

  return ""

def match_compiler_versions(compiler, versions):
  ver = compiler_version(compiler)
  return ver in versions

def c_compiler_executable(compiler):
  if is_compiler_gcc(compiler) or is_compiler_clang(compiler):
    return compiler
  else:
    raise ValueError("Invalid compiler: {}".format(compiler))

def cpp_compiler_executable(compiler):
  if is_compiler_gcc(compiler):
    return compiler.replace("gcc", "g++")
  elif is_compiler_clang(compiler):
    return compiler.replace("clang", "clang++")
  else:
    raise ValueError("Invalid compiler: {}".format(compiler))

def analyze_build_executable(compiler):
  return compiler.replace("clang", "analyze-build")

def cmake_exists():
  return run_test(["cmake", "--version"])

def ninja_exists():
  return run_test(["ninja", "--version"])

def valgrind_exists():
  return run_test(["valgrind", "--version"])

def c_compiler_exists(compiler):
  return run_test([c_compiler_executable(compiler), "--version"])

def cpp_compiler_exists(compiler):
  return run_test([cpp_compiler_executable(compiler), "--version"])

def analyze_build_exists(compiler):
  return run_test([analyze_build_executable(compiler), "--help"])


# Problem Matcher Utilities
# -------------------------


def process_problem_matchers(problem_matcher, diagnostics):
  out = []

  if problem_matcher == "auto":
    out.append("compile")

    if diagnostics == "analyze-build":
      out.append("analyze-build")

    if diagnostics == "asan":
      out.append("asan")

    if diagnostics == "msan":
      out.append("msan")

    if diagnostics == "ubsan":
      out.append("ubsan")

    if diagnostics == "valgrind":
      out.append("valgrind")

  else:
    for pm in problem_matcher.split(","):
      if pm == "":
        continue

      # Substitute first.
      if pm in problem_matcher_substitutions:
        pm = problem_matcher_substitutions[pm]

      # Verify the problem matcher exists.
      if pm not in problem_matcher_definitions:
        raise("Problem matcher {} is not provided by build-actions".format(pm))

      out.append(pm)

  return out

def begin_problem_matchers(problem_matchers, scope):
  for pm in problem_matchers:
    info = problem_matcher_definitions[pm]
    if info["scope"] == scope:
      log("::add-matcher::" + os.path.join(build_actions_root, "problem-matcher-{}.json".format(pm)))

def end_problem_matchers(problem_matchers, scope):
  for pm in problem_matchers:
    info = problem_matcher_definitions[pm]
    if info["scope"] == scope:
      for item in info["provides"]:
        log("::remove-matcher owner={}::".format(item))


# Prepare & Configure Utilities
# -----------------------------


def normalize_arguments(args):
  if args.architecture:
    args.architecture = normalize_architecture(args.architecture)
  else:
    args.architecture = detect_architecture()

  # Backwards compatibility - analyze-build used to be scan-build in the past
  if args.diagnostics == "scan-build":
    args.diagnostics = "analyze-build"

  if not args.generator:
    if args.compiler == "vs2015":
      args.generator = "Visual Studio 14 2015"
    elif args.compiler == "vs2017":
      args.generator = "Visual Studio 15 2017"
    elif args.compiler == "vs2019":
      args.generator = "Visual Studio 16 2019"
    elif args.compiler == "vs2022":
      args.generator = "Visual Studio 17 2022"
    elif host_os == "Darwin" or host_os == "FreeBSD" or host_os == "NetBSD" or host_os == "OpenBSD":
      args.generator = "Unix Makefiles"
    else:
      args.generator = "Ninja"

  args.problem_matcher = process_problem_matchers(args.problem_matcher, args.diagnostics)


# APT Utilities
# -------------


# Based on:
#   - https://stackoverflow.com/questions/68992799/warning-apt-key-is-deprecated-manage-keyring-files-in-trusted-gpg-d-instead
#
# Formats the following string:
#
# Types: deb
# URIs: https://example.com/apt
# Suites: stable
# Components: main
# Signed-By:
#  -----BEGIN PGP PUBLIC KEY BLOCK-----
#  .
#  KEY-DATA
#  -----END PGP PUBLIC KEY BLOCK-----
def apt_format_sources(types, uri, suites, components, key):
  s = "Types: {}\nURIs: {}\nSuites: {}\n".format(types, uri, suites)
  if components:
    s += "Components: {}\n".format(components)
  s += "Signed-By:\n"
  for line in key.split("\n"):
    if line == "":
      line = "."
    s += " " + line + "\n"
    if line == "-----END PGP PUBLIC KEY BLOCK-----":
      break
  return s + "\n"

def apt_add_llvm_toolchain_repository(version):
  rel_info = os_release_info()

  if rel_info["codename"]:
    codename = rel_info["codename"]
    if rel_info["unstable"]:
      codename = "unstable"
    log("Detected OS release codename: {} ({} for llvm repository)".format(rel_info["codename"], codename))

    url = "{}/{}".format(apt_llvm_repository_url, codename)
    log("Verifying whether LLVM provides builds for this OS release (url={})".format(url))

    check = download_text_file(url, method="HEAD", encoding="LATIN-1")
    if check != None:
      link_name = ""
      if codename != "unstable":
        link_name = "-" + codename

      gpg_data = download_text_file(apt_llvm_gpg_file_url, method="GET", encoding="utf-8")

      sources_data = apt_format_sources(
        types="deb",
        uri=url + "/",
        suites="llvm-toolchain{}-{}".format(link_name, version),
        components="main",
        key=gpg_data)
      log("Writing apt sources file:\n" + sources_data)

      write_text_file("llvm.sources", sources_data)
      # We need to run this as root as we need to change files in /etc.
      run(["mv", "llvm.sources", "/etc/apt/sources.list.d/llvm.sources"], sudo=True)
    else:
      log("!! Failure !!")
      raise ValueError("LLVM toolchain doesn't exist on remote")
  else:
    raise ValueError("Failed to get a distribution codename, cannot continue")

def apt_add_test_ubuntu_toolchain():
  run(["add-apt-repository", "-y", apt_ubuntu_test_toolchain_ppa], sudo=True)


# Prepare Step
# ------------

def prepare_step(args):
  """
  Prepare step is responsible for configuring the environment for the
  selected compiler, generator, and diagnostic options.

  NOTE: Prepare only configures the environment, but it doesn't create or use build
  directory. This is the main reason why some parameters must be repeatedly passed
  to the 'configure' step.
  """

  begin_group("Prepare")

  compiler = args.compiler
  generator = args.generator

  # Windows Support
  # ---------------

  if host_os == "Windows":
    pass

  # Apple Support
  # -------------

  elif host_os == "Darwin":
    pass

  # BSD Support
  # -----------

  elif host_os == "FreeBSD":
    packages = []

    if not cmake_exists():
      packages.append("cmake")

    if is_compiler_clang(compiler):
      if not run_test([compiler, "--version"]):
        if compiler == "clang":
          if not run_test(["clang", "--version"]):
            packages.append("llvm")
        else:
          if not run_test([compiler, "--version"]):
            packages.append(compiler.replace("clang-", "llvm"))
    else:
      raise ValueError("{} compiler not supported: use clang on this platform".format(compiler))

    if packages:
      log("Need to install {} packages".format(packages))
      run(["pkg", "install", "-y"] + packages, sudo=not is_root())

  elif host_os == "NetBSD":
    packages = []

    if not cmake_exists():
      packages.append("cmake")

    if compiler.startswith("clang"):
      if not run_test([compiler, "--version"]):
        packages.append(compiler)
    else:
      raise ValueError("{} compiler not supported: use clang on this platform".format(compiler))

    if packages:
      log("Need to install {} packages".format(packages))
      if os.getenv("CI_NETBSD_USE_PKGIN"):
        run(["pkgin", "-y", "install"] + packages, sudo=not is_root())
      else:
        run(["pkg_add", "-I"] + packages, sudo=not is_root())

  elif host_os == "OpenBSD":
    packages = []

    if not cmake_exists():
      packages.append("cmake")

    if compiler.startswith("clang"):
      if not run_test([compiler, "--version"]):
        packages.append(compiler)
    else:
      raise ValueError("{} compiler not supported: use clang on this platform".format(compiler))

    if packages:
      log("Need to install {} packages".format(packages))
      run(["pkg_add", "-I"] + packages, sudo=not is_root())

  # Linux Support
  # -------------

  elif host_os == "Linux":
    packages = []
    compiler_package = None

    if is_compiler_gcc(compiler):
      compiler_package = compiler.replace("gcc", "g++")
    elif is_compiler_clang(compiler):
      compiler_package = compiler
    else:
      raise ValueError("Invalid compiler: {}".format(compiler))

    compiler_exists = c_compiler_exists(compiler) and cpp_compiler_exists(compiler)
    if not compiler_exists:
      packages.append(compiler_package)

    if args.architecture == "x86":
      run(["dpkg", "--add-architecture", "i386"], sudo=True)
      packages.append("linux-libc-dev:i386")
      if is_compiler_gcc(compiler):
        packages.append(compiler_package + "-multilib")
      else:
        # Even clang requires this if libstdc++ is used.
        packages.append("g++-multilib")

    if not cmake_exists():
      packages.append("cmake")

    if generator == "Ninja" and not ninja_exists():
      packages.append("ninja-build")

    if args.diagnostics == "valgrind" and not valgrind_exists():
      packages.append("valgrind")

    if args.diagnostics == "analyze-build" and not analyze_build_exists(compiler):
      if not is_compiler_clang(compiler):
        raise ValueError("analyze-build can only be used with clang compiler, not {}".format(compiler))
      packages.append(compiler.replace("clang", "clang-tools"))

    if packages:
      log("Need to install {} packages".format(packages))

      if compiler.startswith("clang-") and not compiler_exists and match_compiler_versions(compiler, apt_llvm_versions):
        apt_add_llvm_toolchain_repository(compiler_version(compiler))
      elif os_release_info()["id"] == "ubuntu":
        apt_add_test_ubuntu_toolchain()

      run(["apt-get", "update", "-qq"], sudo=True, retry_patterns=apt_retry_patterns)
      run(["apt-get", "install", "-qq"] + packages, sudo=True, retry_patterns=apt_retry_patterns)

  else:
    raise ValueError("Unknown platform: {}".format(host_os))

  end_group("Prepare")


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

  begin_group("Configure")

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

  cmd = ["cmake", source_dir, "-G", generator]
  env = os.environ.copy()

  if generator.startswith("Visual Studio"):
    cmd.extend(["-A", architecture_vs_platform_map[args.architecture]])
  else:
    env["CC"] = c_compiler_executable(compiler)
    env["CXX"] = cpp_compiler_executable(compiler)

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

  cmd.append("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON")

  # Create build directory and invoke cmake.
  os.makedirs(build_dir, exist_ok=True)
  run(cmd, cwd=build_dir, env=env, print_command=True)

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

  end_group("Configure")


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

  if diagnostics == "analyze-build":
    analyze_cmd = [
      analyze_build_executable(args.compiler),
      "-v",
      "--cdb", build_dir + "/" + "compile_commands.json",
      "--output", "analysis-output"
    ]

    begin_group("Analysis")
    begin_problem_matchers(args.problem_matcher, "analyze")
    run(analyze_cmd)
    end_problem_matchers(args.problem_matcher, "analyze")
    end_group("Analysis")

  cmd = ["cmake", "--build", build_dir, "--parallel", str(cpu_count())]
  if generator.startswith("Visual Studio"):
    cmd.extend(["--config", build_type, "--", "-nologo", "-v:minimal"])

  begin_group("Build")
  begin_problem_matchers(args.problem_matcher, "build")
  run(cmd)
  end_problem_matchers(args.problem_matcher, "build")
  end_group("Build")


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

  if tests:
    begin_problem_matchers(args.problem_matcher, "run")

    for test in tests:
      cmd = test["cmd"]
      app = cmd[0]

      executable = os.path.abspath(os.path.join(build_dir, app))
      if host_os == "Windows":
        executable += ".exe"

      # Ignore tests, which were not built, because of disabled features.
      if os.path.isfile(executable):
        group = " ".join(cmd)
        try:
          begin_group(group)
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
          end_group(group)
      else:
        if test.get("optional", False) != True:
          log("Test {} not found and it's not optional.".format(app))
          failures.append(app)

    end_problem_matchers(args.problem_matcher, "run")

    if failures:
      n = len(failures)
      log("{} {} out of {} failed: {}".format(n, pluralize("test", n), len(tests), ", ".join(failures)))
      exit(1)


# Main & Arguments
# ----------------


def create_argument_parser():
  parser = argparse.ArgumentParser(description="Step runner")

  # Step - must be always provided.
  parser.add_argument("--step", help="Step to execute (prepare|configure|build|test|all)")

  # Environment - Must be provided when invoking both 'prepare' and 'configure' steps.
  parser.add_argument("--config", default=None, help="Path to a JSON configuration.")
  parser.add_argument("--compiler", default="", help="C++ compiler to use (gcc|gcc-X|clang|clang-X|vs2015-2022)")
  parser.add_argument("--diagnostics", default="", help="Diagnostics (analyze-build|asan|msan|ubsan|valgrind)")
  parser.add_argument("--generator", default="", help="CMake generator to use")
  parser.add_argument("--architecture", default="default", help="Target architecture (x86|x64|aarch64)")

  # Build options - must be provided when invoking 'configure' step.
  parser.add_argument("--source-dir", default=".", help="Source directory")
  parser.add_argument("--build-type", default="", help="Build type (Debug|Release)")
  parser.add_argument("--build-defs", default="", help="Build definitions (DEF1=???,DEF2=???)")
  parser.add_argument("--problem-matcher", default="", help="Problem matchers to use (auto|compiler|asan|msan|ubsan|valgrind)")

  # Build directory - must be provided when invoking 'configure', 'build', and 'test' steps.
  parser.add_argument("--build-dir", default="build", help="Build directory")

  return parser

def execute_step(step, args):
  if step == "prepare":
    return prepare_step(args)

  if step == "configure":
    return configure_step(args)

  if step == "build":
    return build_step(args)

  if step == "test":
    return test_step(args)

  raise ValueError("Unknown step: {}".format(step))

def main():
  args = create_argument_parser().parse_args()
  step = args.step

  normalize_arguments(args)

  if step == "all":
    log_options["groups"] = True
    execute_step("prepare", args)
    execute_step("configure", args)
    execute_step("build", args)
    execute_step("test", args)
  else:
    execute_step(step, args)

  exit(0)


if __name__ == "__main__":
  main()
