Build Actions
=============

Build-actions intends to simplify building and testing C++ projects within a CI environment.


Work in Progress
----------------

This is a work-in-progress project that was created to share commons in CI workflows. It's very likely that things will change a bit until the interface and project options are stabilized.


Introduction
------------


It's likely that if you maintain multiple C++ projects their CI setup would be very similar. Usually there is a lot of repeating steps that are simply copied from one project to another. Build-actions tries to simplify this a bit by providing a script, which provides support for various stages of a build.

Build-actions provides 4 steps callable from CI environment via `action.py` script:

  - `prepare` - Downloads and installs C++ compilers and build tools required for build.
  - `configure` - Invokes CMake or other project generator.
  - `build` - Builds the configured project.
  - `test` - Runs tests.

It should be possible to call these steps on a dev machine as well to make sure that the build works even before the code executes on CI environment.


Configuration
-------------

Build-actions would usually require two files

  - CI workflow (for example build.yaml for GitHub actions)
  - Configuration (JSON file that provides project-dependent configuration)


Example
-------

The following is an example of using build-actions for `some-project`. Let's start with a workflow:

```yml
name: "Build"
on: [push, pull_request]

defaults:
  run:
    shell: bash

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - { title: "linux"   , os: "ubuntu-latest" , cc: "clang-10", arch: "x86", build_type: "Release", defs: "SOME_PROJECT_TEST=ON" }
          - { title: "linux"   , os: "ubuntu-latest" , cc: "clang-10", arch: "x64", build_type: "Release", defs: "SOME_PROJECT_TEST=ON" }
          - { title: "windows" , os: "windows-latest", cc: "vs2019"  , arch: "x86", build_type: "Release", defs: "SOME_PROJECT_TEST=ON" }
          - { title: "windows" , os: "windows-latest", cc: "vs2019"  , arch: "x64", build_type: "Release", defs: "SOME_PROJECT_TEST=ON" }

    name: "${{matrix.title}} (${{matrix.cc}}, ${{matrix.arch}}, ${{matrix.build_type}})"
    runs-on: "${{matrix.os}}"

    steps:
      - name: "Checkout"
        uses: actions/checkout@v2
        with:
          path: "source"

      - name: "Checkout build-actions"
        run: git clone https://github.com/build-actions/build-actions.git build-actions --depth=1

      - name: "Python"
        uses: actions/setup-python@v2
        with:
          python-version: "3.x"

      - name: "Prepare"
        run: python build-actions/action.py
                    --step=prepare
                    --compiler=${{matrix.cc}}
                    --architecture=${{matrix.arch}}

      - name: "Configure"
        run: python build-actions/action.py
                    --step=configure
                    --config=source/.github/workflows/build-config.json
                    --source-dir=source
                    --compiler=${{matrix.cc}}
                    --architecture=${{matrix.arch}}
                    --build-type=${{matrix.build_type}}
                    --build-defs=${{matrix.defs}}

      - name: "Build"
        run: python build-actions/action.py --step=build

      - name: "Test"
        run: python build-actions/action.py --step=test
```

And a simple build configuration `build-config.json`:

```json
{
  "tests": [
    {
      "cmd": ["test_a", "--some-argument=1"],
      "optional": true
    },
    {
      "cmd": ["test_b", "--arg-1", "--arg-2"]
    }
  ]
}
```

It should be possible to invoke the workflow on a dev machine as well:

```bash
git clone https://github.com/some-org/some-project.git
git clone https://github.com/build-actions/build-actions.git

# Install build requirements (clang-10) - requires sudo on Linux.
python build-actions/action.py \
       --step=prepare \
       --compiler=clang-10 \
       --architecture=x64

# Configure the project by using cmake (uses 'build' directory by default).
python build-actions/action.py \
       --step=configure \
       --config=some-project/.github/workflows/build-config.json
       --compiler=clang-10 \
       --architecture=x64 \
       --source-dir=some-project

# Build your project.
python build-actions/action.py --step=build

# Test your project - would run all executables as specified in the configuration.
python build-actions/action.py --step=test
```


Projects Using Build-Actions
----------------------------

These projects use build-actions and can be considered as living examples:

  - [asmjit](https://github.com/asmjit/asmjit)
  - [blend2d](https://github.com/blend2d/blend2d)
