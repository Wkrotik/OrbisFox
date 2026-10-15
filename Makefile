OO_PS4_TOOLCHAIN ?= $(CURDIR)/.deps/OpenOrbis/PS4Toolchain
SDK := $(OO_PS4_TOOLCHAIN)
CXX := clang++
HOST_CXX ?= c++
LD := ld.lld
RESOURCE_DIR := $(shell $(CXX) -print-resource-dir)
CXX_RUNTIME := $(CURDIR)/.deps/libcxx-orbis
GECKO_BUILD := $(CURDIR)/build/gecko-spidermonkey
CPPFLAGS := --target=x86_64-pc-freebsd12-elf -nostdinc -D__ORBIS__ -D_GNU_SOURCE -D_POSIX_C_SOURCE=200809L -isystem $(CXX_RUNTIME)/include/c++/v1 -isystem $(CURDIR)/.deps/sdk-overlay -isystem $(SDK)/include -isystem $(RESOURCE_DIR)/include -Iinclude
CXXFLAGS := -std=c++20 -O2 -g -fPIC -mno-red-zone -funwind-tables -fno-exceptions -fno-rtti -fno-sized-deallocation -fno-aligned-new -Wall -Wextra -Werror -MMD -MP
SOURCES := $(wildcard src/*.cpp) $(wildcard src/ps4/*.cpp)
OBJECTS := $(patsubst src/%.cpp,build/obj/%.o,$(SOURCES))
# Optional firmware services are explicitly loaded and resolved at runtime.
LIBS := -L$(CXX_RUNTIME)/lib -lc++ -lc++abi -lunwind -lc -lkernel -lSceSysmodule
GECKO_LIBS := $(GECKO_BUILD)/js/src/build/libjs_static.a $(GECKO_BUILD)/liborbisfox-gecko-support.a $(GECKO_BUILD)/x86_64-orbis-freebsd/release/libjsrust.a

VIDEOOUT_OBJECTS := $(filter-out build/obj/ps4/main.o build/obj/ps4/piglet.o,$(OBJECTS)) build/obj/ps4/main-videoout.o
.PHONY: all bootstrap check-sdk pkg pkg-videoout pkg-gecko test test-js clean validate validate-probe validate-videoout upload source-release gecko-configure gecko-build gecko-layout-configure gecko-layout-build gecko-app-build libcxx
# The browser is the default. `pkg` remains the historical standalone lane.
all: pkg-gecko
bootstrap:
	./scripts/bootstrap-sdk.sh
check-sdk:
	@test -f "$(SDK)/lib/crt1.o" || (echo 'Run make bootstrap or set OO_PS4_TOOLCHAIN'; exit 1)
build/obj/js_canvas.o: src/js_canvas.cpp Makefile $(GECKO_BUILD)/js/src/build/libjs_static.a | check-sdk
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -isystem $(GECKO_BUILD)/dist/include -include $(GECKO_BUILD)/js/src/js-confdefs.h -c $< -o $@
$(GECKO_LIBS) &: scripts/build-gecko.py scripts/configure-gecko.py scripts/patch-gecko.py scripts/orbis-cc.py scripts/sdk-overlay.py | build/rust/liborbisfox.a $(CXX_RUNTIME)/lib/libc++.a
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-gecko.py
$(CXX_RUNTIME)/lib/libc++.a: scripts/build-libcxx.py scripts/sdk-overlay.py scripts/orbis-cc.py
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-libcxx.py
build/obj/%.o: src/%.cpp Makefile $(CXX_RUNTIME)/lib/libc++.a | check-sdk
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@
build/obj/ps4/main-videoout.o: src/ps4/main.cpp Makefile | check-sdk
	@mkdir -p $(dir $@)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -DORBISFOX_VIDEOOUT_ONLY -c $< -o $@
build/swgl/libswgl.a: scripts/fetch-swgl.py scripts/build-swgl.py scripts/swgl-Cargo.lock Makefile
	SWGL_CXX="$(CXX)" ORBIS_CXX_HEADERS="$(CXX_RUNTIME)/include/c++/v1" OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-swgl.py
build/swgl/libswgl-host.a: scripts/fetch-swgl.py scripts/build-swgl.py scripts/swgl-Cargo.lock
	python3 scripts/build-swgl.py --host-only
build/rust/liborbisfox.a: scripts/bootstrap-rust.py scripts/build-rust.py scripts/patch-rust-libc.py scripts/orbis-rustc.py targets/x86_64-orbis-freebsd.json rust/runtime-probe/Cargo.toml rust/runtime-probe/src/lib.rs
	python3 scripts/build-rust.py
build/videoout/orbisfox.elf: $(VIDEOOUT_OBJECTS) build/swgl/libswgl.a build/rust/liborbisfox.a $(GECKO_LIBS) Makefile scripts/ps4.ld
	@mkdir -p $(dir $@)
	$(LD) -m elf_x86_64 -pie -z max-page-size=0x4000 --no-rosegment --gc-sections --script scripts/ps4.ld --eh-frame-hdr -L$(CXX_RUNTIME)/lib -L$(SDK)/lib -o $@ $(SDK)/lib/crt1.o $(VIDEOOUT_OBJECTS) build/swgl/libswgl.a build/rust/liborbisfox.a $(GECKO_LIBS) $(LIBS)
build/orbisfox.elf: $(OBJECTS) build/swgl/libswgl.a build/rust/liborbisfox.a $(GECKO_LIBS) Makefile scripts/ps4.ld
	$(LD) -m elf_x86_64 -pie -z max-page-size=0x4000 --no-rosegment --gc-sections --script scripts/ps4.ld --eh-frame-hdr -L$(CXX_RUNTIME)/lib -L$(SDK)/lib -o $@ $(SDK)/lib/crt1.o $(OBJECTS) build/swgl/libswgl.a build/rust/liborbisfox.a $(GECKO_LIBS) $(LIBS)
pkg: build/orbisfox.elf
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/package.py
pkg-videoout: build/videoout/orbisfox.elf
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/package.py --variant videoout
validate:
	python3 scripts/verify-gecko-package.py
validate-probe:
	DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$(SDK)/bin/linux/PkgTool.Core" pkg_validate dist/OrbisFox.pkg
validate-videoout:
	DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$(SDK)/bin/linux/PkgTool.Core" pkg_validate dist/IV0000-ORBV00001_00-ORBISFOXVIDEO000.pkg
test-js:
	python3 scripts/test-javascript.py
test: build/swgl/libswgl-host.a
	@mkdir -p build
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/surface_test.cpp src/surface.cpp src/ui.cpp -o build/surface_test
	./build/surface_test
	$(HOST_CXX) -std=c++17 -O2 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/pixel_blit_test.cpp src/surface.cpp -o build/pixel_blit_test
	./build/pixel_blit_test
	$(HOST_CXX) -std=c++17 -O2 -g -Wall -Wextra -Werror -fsanitize=address,undefined -U__SSE2__ -Iinclude tests/pixel_blit_test.cpp src/surface.cpp -o build/pixel_blit_scalar_test
	./build/pixel_blit_scalar_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/shader_table_test.cpp src/shader_table.cpp -o build/shader_table_test
	./build/shader_table_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/module_binding_test.cpp -o build/module_binding_test
	./build/module_binding_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/swgl_test.cpp src/swgl_canvas.cpp src/surface.cpp build/swgl/libswgl-host.a -o build/swgl_test
	./build/swgl_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/artwork_test.cpp src/artwork.cpp src/surface.cpp -o build/artwork_test
	./build/artwork_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/touch_cursor_test.cpp src/touch_cursor.cpp -o build/touch_cursor_test
	./build/touch_cursor_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/stick_cursor_test.cpp -o build/stick_cursor_test
	./build/stick_cursor_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/stick_scroll_test.cpp -o build/stick_scroll_test
	./build/stick_scroll_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/keyboard_session_test.cpp -o build/keyboard_session_test
	./build/keyboard_session_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/keyboard_launch_test.cpp -o build/keyboard_launch_test
	./build/keyboard_launch_test
	python3 scripts/test-native-stdio.py --compiler "$(HOST_CXX)"
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/heap_diagnostics_test.cpp -o build/heap_diagnostics_test
	./build/heap_diagnostics_test
	python3 scripts/test-skia-semaphore.py
	python3 scripts/test-skia-glyph-invariants.py
	python3 scripts/test-orbis-window-provider.py
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/heap_reclaim_probe_test.cpp -o build/heap_reclaim_probe_test
	./build/heap_reclaim_probe_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/heap_advice_probe_test.cpp -o build/heap_advice_probe_test
	./build/heap_advice_probe_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/heap_bin_audit_test.cpp -o build/heap_bin_audit_test
	./build/heap_bin_audit_test
	python3 scripts/test-native-allocator.py
	python3 scripts/test-sdk-allocator.py
	python3 scripts/test-pointer-reentrancy.py
	python3 scripts/test-orbis-blob-font.py
	$(HOST_CXX) -std=c++20 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/jit_memory_probe_test.cpp -o build/jit_memory_probe_test
	./build/jit_memory_probe_test
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/browser_controls_test.cpp -o build/browser_controls_test
	./build/browser_controls_test
	node tests/browser_shell_test.js
	node tests/browser_shell_ui_test.js
	node tests/browser_shell_host_test.js
	$(HOST_CXX) -std=c++17 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -Iinclude tests/pthread_attribute_test.cpp -o build/pthread_attribute_test
	./build/pthread_attribute_test
	python3 -m unittest discover -s tests -p '*_test.py'
libcxx:
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-libcxx.py
gecko-build: check-sdk
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-gecko.py
gecko-configure:
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/configure-gecko.py
# Full-engine browser lane. The standalone JS lane supplies regression inputs.
gecko-layout-configure:
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/configure-gecko-layout.py
gecko-layout-build:
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-gecko-layout.py
gecko-app-build: gecko-build
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/build-gecko-app.py
pkg-gecko: gecko-app-build
	OO_PS4_TOOLCHAIN="$(SDK)" python3 scripts/package-gecko.py
# Explicit destination only; never install or launch a console application.
CONSOLE_PORT ?= 2121
upload:
	@test -n "$(CONSOLE_HOST)" || (echo 'Set CONSOLE_HOST=<console IP>; no default public destination'; exit 1)
	$(MAKE) pkg-gecko
	python3 scripts/deploy-console.py --host "$(CONSOLE_HOST)" --port "$(CONSOLE_PORT)"
source-release:
	python3 scripts/prepare-source-release.py
clean:
	@test "$(CONFIRM_CLEAN)" = yes || (echo 'Refusing to delete build/dist: archive baselines and crash evidence first; explicit CONFIRM_CLEAN=yes required'; exit 1)
	rm -rf build dist
-include $(OBJECTS:.o=.d) build/obj/ps4/main-videoout.d
