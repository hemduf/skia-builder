# SKIA BUILDER

This is a python script and github actions workflow to manage building static libraries for [SKIA](https://skia.org/).

![output](https://github.com/user-attachments/assets/b40cc273-272c-4f38-a64f-968327408fa5)

The script automates the process of building the libraries for various platforms (macOS, iOS, visionOS, Windows, Linux, WASM). It handles the setup of the build environment, cloning of the Skia repository, configuration of build parameters, and compilation. The script also includes functionality for creating universal binaries for macOS and an XCFramework for apple platforms.

The GN Args are supplied in constants which you will need to tweak if you want to modify the build. The CLI and CI default to `chrome/m153`; pass `-branch`/`skia_branch` to test another Skia branch.

## Building

Skia's build scripts requires ninja and python3 to be installed on all platforms. Emscripten is installed via skia.

## Helper commands

There is a Makefile with helper commands to build the libraries for each platform (from macOS/Linux). On windows you can use the `build-win.sh` script.

```bash
make example-mac # Build example for macOS (will also build libSkia etc)
./example/build-mac/example
Image saved as output.png
```

Other options:
```bash
make skia-mac # Build libraries for macOS
make skia-ios # Build libraries for iOS
make skia-linux # Build libraries for Linux x64
make skia-linux-arm64 # Build libraries for Linux ARM64 / Raspberry Pi OS 64-bit
make skia-wasm # Build libraries for WASM
make skia-xcframework # Build XCFramework
make example-mac # Build example for macOS
make example-wasm # Build example for WASM
make serve-wasm # Serve the WASM example
```

## Build script

The script is called as follows

```
build-skia.py [-h] [-config {Debug,Release}] [-archs ARCHS] [-branch BRANCH] [--shallow] {mac,ios,visionos,win,linux,wasm,xcframework}
```

## Building on macOS

Note: you may need to call 

```bash
ulimit -n 2048
```

in order to increase the number of files that can be opened at once.

Note: macOS builds target macOS 11+ (Big Sur). This is hardcoded in Skia's `gn/skia/BUILD.gn` via the `-target` compiler flag.

### Build for macOS universal (arm64 & x86_64 intel)

```bash
python3 build-skia.py -config Release -branch chrome/m153 mac
```

### Build for iOS (including x86_64 simulator)

```bash
python3 build-skia.py -config Release -branch chrome/m153 ios
```

### Build an XCFramework

```bash
python3 build-skia.py -config Release -branch chrome/m153 xcframework
```

## Building on Linux / Raspberry Pi

Linux builds support both `x64` and `arm64`. Raspberry Pi support targets a 64-bit Linux userspace (for example Raspberry Pi OS 64-bit).

Install the Linux build dependencies:

```bash
sudo apt-get update
sudo apt-get install -y ninja-build clang libfontconfig1-dev libgl1-mesa-dev libglu1-mesa-dev libx11-xcb-dev libxcb1-dev libxcb-xkb-dev libwayland-dev
```

Build the ARM64 package directly on a Raspberry Pi or another AArch64 Linux machine:

```bash
python3 build-skia.py linux -archs arm64 -variant gpu -config Release -branch chrome/m153
```

or:

```bash
make skia-linux-arm64
```

The GPU variant enables Vulkan and Dawn/Graphite. The generated libraries are written under:

```text
build/linux-gpu/lib/Release/arm64/
```

CI also builds this target natively on GitHub's ARM64 Linux runner and publishes `skia-build-linux-arm64-gpu-release.zip` with full releases.

## Building on Windows 

On Windows, you need to install LLVM in order to compile Skia with clang, as recommened by the authors.

LLVM should be installed in `C:\Program Files\LLVM\`

```bash
py -3 build-skia.py -config Release -branch chrome/m153 win
```

### CRT linkage (/MT vs /MD)

By default Windows libraries are built with the static CRT (`/MT`, `/MTd` for Debug). Pass `-crt MD` to build against the dynamic CRT (`/MD`, `/MDd` for Debug) instead — this also switches Dawn's CMake build to `MultiThreadedDLL`. MD builds are output to `build/win-gpu-md/lib/` so they don't collide with the default MT output in `build/win-gpu/lib/`.

```bash
py -3 build-skia.py -config Release -branch chrome/m153 -crt MD win
```

In CI, MD builds are published as separate zips: `skia-build-win-x64-gpu-md-release.zip` and `skia-build-win-x64-gpu-md-debug.zip` (the existing MT artifact names are unchanged).

### ANGLE

Windows GPU builds enable ANGLE (`skia_use_angle=true`). The Windows packages include `libEGL.dll`/`libGLESv2.dll` and their import libs (`libEGL.dll.lib`/`libGLESv2.dll.lib`) alongside the Skia libraries, plus the ANGLE headers (EGL, GLES2/3, KHR) under `include/angle/` — add that directory to your include paths to use `<EGL/egl.h>` etc. The ANGLE DLLs are self-contained, so the same DLLs work with both MT and MD packages.

## CI / GitHub Actions

The repository includes a GitHub Actions workflow (`.github/workflows/build-skia.yml`) that builds all platforms in parallel and creates releases tagged with the Skia branch name.

Linux is built for both x64 and ARM64; the ARM64 job runs natively on `ubuntu-24.04-arm` and is suitable for Raspberry Pi OS 64-bit / generic AArch64 Linux targets.

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `skia_branch` | Skia branch to build | `chrome/m153` |
| `platforms` | Platforms to build (comma-separated or `all`) | `all` |
| `skip_release` | Skip creating release | `false` |
| `test_mode` | Skip build, create dummy files | `false` |

### Trigger Builds

```bash
# Build all platforms and create release
gh workflow run build-skia.yml

# Build specific platform(s) without creating a release
gh workflow run build-skia.yml -f platforms=visionos -f skip_release=true
gh workflow run build-skia.yml -f platforms=mac,ios -f skip_release=true
gh workflow run build-skia.yml -f platforms=linux -f skip_release=true
gh workflow run build-skia.yml -f platforms=win -f skip_release=true

# Build with a different Skia branch
gh workflow run build-skia.yml -f skia_branch=chrome/m154
```

### Check CI Status

```bash
gh run list
gh run view <run-id> --log-failed
```

### Create XCFramework from Existing Release

If you've already built all platforms, you can create an XCFramework without rebuilding:

```bash
gh workflow run create-xcframework.yml -f release_tag=chrome/m153
```

This downloads mac, ios, and visionos artifacts from the specified release and creates a combined XCFramework.
