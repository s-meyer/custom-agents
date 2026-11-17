# Demo project

An intentionally broken ARM32 C project used by the agent tasks in this repository. It does not build on purpose: one compiler error and several warnings under strict flags.

## Layout

- `src/main.c`, `src/util.c`, `include/util.h` — the sources
- `Makefile` — builds `out/app` with `arm-linux-gnueabihf-gcc` and the flags `-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wformat=2 -Wcast-align=strict`
- `Dockerfile` — a standalone compiler image with the ARM32 cross toolchain

## Build it without an agent

To see the compiler error and warnings without any agent SDK or model credentials:

```sh
docker build -f Dockerfile -t codex-demo-compiler:dev .
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/workspace" -w /workspace codex-demo-compiler:dev make
```

The build fails with `error: conflicting types for 'parsed'` in `src/util.c:23` (the variable is declared twice) and reports warnings for `strlen` used without `<string.h>`, a signedness mismatch in the loop bound, the unaligned pointer cast in `read_unaligned`, and an unused variable in `main.c`. Run the same container with `make clean` to reset the build output.

## How agents use it

`make -C ../shared demo-repo` exports this project as a bare Git repository at `shared/work/demo-repo.git`. Every task checks out a fresh work branch from it; the runner verifies the agent's work with the completion checks (`make clean`, then `make` with zero warnings or errors) and republishes the fixed sources as a branch and patch.

The canonical guide, including the expected diagnostics, is in the [root README](../README.md#demonstrate-a-failed-compiler-run).
