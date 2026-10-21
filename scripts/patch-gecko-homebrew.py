#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""Native SDK ABI preparation from pinned upstream, without layering musl fixes."""
import hashlib
import json
import io
from pathlib import Path
import runpy
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'


def write_changed(path, contents):
    if path.read_bytes() != contents:
        path.write_bytes(contents)


def prepare_libc(source, native_sdk=True):
    # Generate both producer-owned variants in scratch space. Refuse to erase
    # unknown edits; never reset a whole source checkout or touch old SDK trees.
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION,
                                       'third_party/rust/libc'])
    with tempfile.TemporaryDirectory(prefix='orbisfox-native-libc-') as tmp:
        tmp = Path(tmp)
        for variant in ('native', 'legacy'):
            root = tmp / variant
            root.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(root, filter='data')
        native, legacy = (tmp / v / 'third_party/rust/libc' for v in ('native', 'legacy'))
        runpy.run_path(str(ROOT / 'scripts/bootstrap-homebrew-rust.py'))['patch_libc'](native)
        runpy.run_path(str(ROOT / 'scripts/patch-rust-libc.py'))['patch'](legacy)
        selected = native if native_sdk else legacy
        changes = []
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            pristine = {Path(member.name).relative_to('third_party/rust/libc'): tar.extractfile(member).read()
                        for member in tar if member.isfile()}
        for path in selected.rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(selected)
            output = source / 'third_party/rust/libc' / relative
            original, wanted = pristine[relative], path.read_bytes()
            variants = ((native / relative).read_bytes(), (legacy / relative).read_bytes())
            current = output.read_bytes()
            if current not in (original, *variants):
                raise RuntimeError('Refusing to overwrite non-producer libc edit: ' + str(output))
            if current != wanted:
                changes.append((output, wanted))
        # Validate every affected file before the first write.
        for output, wanted in changes:
            write_changed(output, wanted)
        return {'changed_files': [str(path.relative_to(source)) for path, _ in changes],
                'sha256': {str(path.relative_to(selected)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in selected.rglob('*.rs')}}


def patch_rust_detection(source):
    path = source / 'build/moz.configure/rust.configure'
    text = path.read_text()
    old = '            info = split_triplet(t, allow_wasi=True)'
    new = ('            # Our JSON target emits native PS4 code with the audited BSD-9 ABI.\n'
           '            info = split_triplet(\n'
           '                "x86_64-orbis-freebsd9.0" if t == "x86_64-scei-ps4" else t,\n'
           '                allow_wasi=True)')
    previous = new.replace('x86_64-orbis-freebsd9.0', 'x86_64-scei-freebsd9.0')
    if previous in text:
        text = text.replace(previous, new)
        write_changed(path, text.encode())
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Pinned Gecko Rust target detection drift')
        write_changed(path, text.replace(old, new).encode())


def patch_native_js_thread(source):
    # The legacy platform header deliberately omits pthread_np.h. Native BSD
    # provides the genuine void pthread_set_name_np declaration there; include
    # it at the use site without changing legacy thread/get-name behavior.
    path = Path(source) / 'js/src/threading/posix/PosixThread.cpp'
    old = '#include "mozilla/Assertions.h"\n'
    new = old + '\n#ifdef ORBISFOX_HOMEBREW_SDK\n#  include <pthread_np.h>\n#endif\n'
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1 or '#ifdef ORBISFOX_HOMEBREW_SDK' in text:
        raise RuntimeError('Native JavaScript thread declaration drift')
    write_changed(path, text.replace(old, new).encode())


def patch_native_file_handle_clone(source):
    path = Path(source) / 'mfbt/UniquePtrExtensions.cpp'
    text = path.read_text()
    old = '''#    ifdef F_DUPFD_CLOEXEC
    fd = fcntl(aFile, F_DUPFD_CLOEXEC, 0);
#    else'''
    previous = '''#    ifdef F_DUPFD_CLOEXEC
    fd = fcntl(aFile, F_DUPFD_CLOEXEC, 0);
#      ifdef MOZ_ORBIS_HOMEBREW_SDK
    // Header availability is not firmware command availability. Retain the
    // atomic operation when supported; only EINVAL selects the POSIX fallback.
    // Orbis content is single-process; this fallback is not atomic across exec.
    if (fd < 0 && errno == EINVAL) {
      fd = dup(aFile);
      if (fd >= 0) {
        const int flags = fcntl(fd, F_GETFD);
        if (flags < 0 || fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0) {
          const int error = errno;
          close(fd);
          errno = error;
          return nullptr;
        }
      }
    }
#      endif
#    else'''
    new = '''#    ifdef MOZ_ORBIS_HOMEBREW_SDK
    // Native command 17 returns zero without duplicating the descriptor.
    // Use genuine dup plus checked CLOEXEC; not atomic across fork/exec.
    fd = dup(aFile);
    if (fd < 0) {
      return nullptr;
    }
    const int flags = fcntl(fd, F_GETFD);
    if (flags < 0 || fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0) {
      const int error = errno;
      close(fd);
      errno = error;
      return nullptr;
    }
#    elif defined(F_DUPFD_CLOEXEC)
    fd = fcntl(aFile, F_DUPFD_CLOEXEC, 0);
#    else'''
    if new in text:
        return
    if previous in text:
        text = text.replace(previous, old)
    if text.count(old) != 1 or '#      ifdef MOZ_ORBIS_HOMEBREW_SDK' in text:
        raise RuntimeError('Native file-handle clone declaration drift')
    write_changed(path, text.replace(old, new).encode())


def patch_native_file_handle_truthiness(source):
    path = Path(source) / 'mfbt/UniquePtrExtensions.h'
    text = path.read_text()
    old = '  operator FileHandleType() const { return mHandle; }'
    new = '''#ifdef MOZ_ORBIS_HOMEBREW_SDK
  // libc++ reset tests the pointer contextually; a genuine fd 0 is owned.
  explicit operator bool() const { return IsValid(mHandle); }
#endif
''' + old
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Native file-handle truthiness drift')
        write_changed(path, text.replace(old, new).encode())


def patch_native_descriptor_shuffle(source):
    path = Path(source) / 'ipc/glue/FileDescriptorShuffle.cpp'
    text = path.read_text()
    old = '#ifdef F_DUPFD_CLOEXEC\nstatic const int kDupFdCmd'
    new = '#if defined(F_DUPFD_CLOEXEC) && !defined(MOZ_ORBIS_HOMEBREW_SDK)\nstatic const int kDupFdCmd'
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Native descriptor shuffle command drift')
        text = text.replace(old, new)
    old = '''      mTempFds.AppendElement(src);'''
    new = '''#ifdef MOZ_ORBIS_HOMEBREW_SDK
      // Preserve F_DUPFD's lower bound and reject success-shaped bad results.
      if (src <= maxDst) {
        return false;
      }
      const int flags = fcntl(src, F_GETFD);
      if (flags < 0 || fcntl(src, F_SETFD, flags | FD_CLOEXEC) < 0) {
        // Register ownership before returning; the destructor closes this fd.
        mTempFds.AppendElement(src);
        return false;
      }
#endif
      mTempFds.AppendElement(src);'''
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Native descriptor shuffle ownership drift')
        text = text.replace(old, new)
    write_changed(path, text.encode())


def patch_native_shared_memory_errors(source):
    path = Path(source) / 'ipc/glue/SharedMemoryPlatform_posix.cpp'
    text = path.read_text()
    old = '''  if (!rv) {
    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning,
                "failed to duplicate file descriptor: {}", strerror(errno));
  }'''
    new = '''  if (!rv) {
    const int error = errno;
    MOZ_LOG_FMT(gSharedMemoryLog, LogLevel::Warning,
                "failed to duplicate file descriptor: {}", strerror(error));
    errno = error;
  }'''
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError('Native shared-memory clone error-path drift')
    write_changed(path, text.replace(old, new).encode())


def patch_native_demangling(source):
    path = Path(source) / 'mozglue/misc/StackWalk.cpp'
    text = path.read_text()
    old = '#  if defined(MOZ_DEMANGLE_SYMBOLS)'
    new = old + ' || defined(MOZ_ORBIS_HOMEBREW_SDK)'
    if text.count(new) != 2:
        if text.count(old) != 2 or new in text:
            raise RuntimeError('Native stack demangling declaration drift')
        write_changed(path, text.replace(old, new).encode())


def patch_native_platform_capabilities(source):
    changes = []
    replacements = (
        ('third_party/abseil-cpp/absl/time/internal/cctz/src/time_zone_format.cc',
         'char* strptime(const char* s, const char* fmt, std::tm* tm) {',
         'char* PortableStrptime(const char* s, const char* fmt, std::tm* tm) {'),
        ('third_party/abseil-cpp/absl/time/internal/cctz/src/time_zone_format.cc',
         '    dp = strptime(dp, fmt, tm);',
         '#if HAS_STRPTIME\n    dp = strptime(dp, fmt, tm);\n'
         '#else\n    dp = PortableStrptime(dp, fmt, tm);\n#endif'),
        ('ipc/chromium/src/base/process_util_posix.cc',
         '#ifndef __OpenBSD__\n#  define HAVE_WAITID\n#endif',
         '#if !defined(__OpenBSD__) && !defined(MOZ_ORBIS_HOMEBREW_SDK)\n'
         '#  define HAVE_WAITID\n#endif'),
        # Repair the earlier call-site-only selection: the capability must also
        # select handleStatus and every other dependent declaration together.
        ('ipc/chromium/src/base/process_util_posix.cc',
         '#if defined(HAVE_WAITID) && !defined(MOZ_ORBIS_HOMEBREW_SDK)\n',
         '#ifdef HAVE_WAITID\n'),
        ('third_party/rust/getrandom/src/backends.rs',
         '    } else if #[cfg(any(\n        target_os = "haiku",',
         '    } else if #[cfg(any(\n        all(target_os = "freebsd", target_vendor = "scei"),\n        target_os = "haiku",'),
        ('netwerk/dns/PlatformDNSUnix.cpp',
         '                                HTTPSAliasTarget& aAlias) {\n  DNSPacket packet;',
         '                                HTTPSAliasTarget& aAlias) {\n'
         '#if defined(MOZ_ORBIS_HOMEBREW_SDK)\n'
         '  // No raw resolver-query API in this SDK. Preserve a real error,\n'
         '  // not a fabricated empty HTTPS record or a successful DNS answer.\n'
         '  return NS_ERROR_NOT_AVAILABLE;\n'
         '#else\n  DNSPacket packet;'),
        ('netwerk/dns/PlatformDNSUnix.cpp',
         '  return ParseHTTPSRecord(host, packet, aResult, aTTL, aAlias);\n}',
         '  return ParseHTTPSRecord(host, packet, aResult, aTTL, aAlias);\n#endif\n}'),
    )
    staged = {}
    for relative, old, new in replacements:
        path = Path(source) / relative
        text = staged.get(path, path.read_text())
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError('Native platform capability drift: ' + relative)
            text = text.replace(old, new)
        staged[path] = text
        if relative == 'third_party/rust/getrandom/src/backends.rs':
            checksum = Path(source) / 'third_party/rust/getrandom/.cargo-checksum.json'
            data = json.loads(checksum.read_text())
            valid = {hashlib.sha256(value.encode()).hexdigest()
                     for value in (text, text.replace(new, old))}
            if data['files'].get('src/backends.rs') not in valid:
                raise RuntimeError('Native getrandom source/checksum drift')
            data['files']['src/backends.rs'] = hashlib.sha256(text.encode()).hexdigest()
            staged[checksum] = json.dumps(data, sort_keys=True) + '\n'
    marker = '# Native SDK: use CCTZ\'s genuine portable parser, not absent strptime.'
    block = '\n' + marker + '\nif CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n    DEFINES["HAS_STRPTIME"] = 0\n'
    # Parent moz.build DEFINES are not inherited by the generated GN target.
    # Migrate the earlier ineffective parent setting to the actual owning leaf.
    parent = Path(source) / 'third_party/abseil-cpp/moz.build'
    text = parent.read_text()
    if marker in text and text.count(block) != 1:
        raise RuntimeError('Native CCTZ parent configuration drift')
    staged[parent] = text.replace(block, '')
    path = Path(source) / 'third_party/abseil-cpp/absl/time/internal/cctz/time_zone_gn/moz.build'
    text = path.read_text()
    if block not in text:
        if marker in text:
            raise RuntimeError('Native CCTZ parser configuration drift')
        text += block
    staged[path] = text
    old_condition = 'target_os = "freebsd",'
    condition = 'all(target_os = "freebsd", not(target_vendor = "scei")),'
    for relative, begin, end in (
        ('src/socket.rs', '    pub fn accept(&self)', '    /// Accept a new incoming connection'),
        ('src/socket.rs', '/// Set `FD_CLOEXEC` on the `socket`', '/// A local interface'),
        ('src/sys/unix.rs', '    /// Accept a new incoming connection', '    /// Sets `CLOEXEC` on the socket.'),
    ):
        path = Path(source) / 'third_party/rust/socket2' / relative
        text = staged.get(path, path.read_text())
        if text.count(begin) != 1:
            raise RuntimeError('Native socket2 capability anchor drift: ' + relative)
        start = text.index(begin)
        stop = text.find(end, start + len(begin))
        if stop < 0:
            raise RuntimeError('Native socket2 capability end drift: ' + relative)
        region = text[start:stop]
        if region.count(condition) != 2:
            if region.count(old_condition) != 2 or condition in region:
                raise RuntimeError('Native socket2 capability configuration drift: ' + relative)
            region = region.replace(old_condition, condition)
        staged[path] = text[:start] + region + text[stop:]
    old_clone = '''pub(crate) fn try_clone(fd: RawSocket) -> io::Result<RawSocket> {
    syscall!(fcntl(fd, libc::F_DUPFD_CLOEXEC, 0))
}'''
    new_clone = '''pub(crate) fn try_clone(fd: RawSocket) -> io::Result<RawSocket> {
    #[cfg(target_vendor = "scei")]
    {
        // Native command 17 silently returns zero; checked dup is non-atomic.
        let owned = unsafe { OwnedFd::from_raw_fd(syscall!(dup(fd))?) };
        fcntl_add(owned.as_raw_fd(), libc::F_GETFD, libc::F_SETFD, libc::FD_CLOEXEC)?;
        Ok(owned.into_raw_fd())
    }
    #[cfg(not(target_vendor = "scei"))]
    {
        syscall!(fcntl(fd, libc::F_DUPFD_CLOEXEC, 0))
    }
}'''
    path = Path(source) / 'third_party/rust/socket2/src/sys/unix.rs'
    text = staged[path]
    if new_clone not in text:
        if text.count(old_clone) != 1:
            raise RuntimeError('Native socket2 clone capability drift')
        staged[path] = text.replace(old_clone, new_clone)
    checksum = Path(source) / 'third_party/rust/socket2/.cargo-checksum.json'
    data = json.loads(checksum.read_text())
    for relative in ('src/socket.rs', 'src/sys/unix.rs'):
        text = staged[Path(source) / 'third_party/rust/socket2' / relative]
        previous = text.replace(new_clone, old_clone)
        valid = {hashlib.sha256(value.encode()).hexdigest()
                 for value in (text, previous, previous.replace(condition, old_condition))}
        if data['files'].get(relative) not in valid:
            raise RuntimeError('Native socket2 source/checksum drift: ' + relative)
        data['files'][relative] = hashlib.sha256(text.encode()).hexdigest()
    staged[checksum] = json.dumps(data, sort_keys=True) + '\n'
    # Cargo treats registry sources as immutable and Make omits their files
    # from libgkrust.d. A path patch makes this adapted crate a watched input.
    path = Path(source) / 'Cargo.toml'
    text = path.read_text()
    marker = '# Orbis native socket2 adaptation is a watched workspace input.'
    block = ('\n' + marker + '\n[patch.crates-io.socket2]\n'
             'path = "third_party/rust/socket2"\n')
    if block not in text:
        if marker in text or '[patch.crates-io.socket2]' in text:
            raise RuntimeError('Native socket2 workspace patch drift')
        text += block
    staged[path] = text
    path = Path(source) / 'Cargo.lock'
    text = path.read_text()
    packages = text.split('[[package]]')
    found = 0
    registry = ('source = "registry+https://github.com/rust-lang/crates.io-index"\n'
                'checksum = "3a766e1110788c36f4fa1c2b71b387a7815aa65f88ce0229841826633d93723e"\n')
    for index, package in enumerate(packages):
        if package.startswith('\nname = "socket2"\n'):
            found += 1
            if not package.startswith('\nname = "socket2"\nversion = "0.6.3"\n'):
                raise RuntimeError('Native socket2 locked version drift')
            if registry in package:
                packages[index] = package.replace(registry, '')
            elif 'source =' in package or 'checksum =' in package:
                raise RuntimeError('Native socket2 locked source drift')
    if found != 1:
        raise RuntimeError('Native socket2 locked package drift')
    staged[path] = '[[package]]'.join(packages)
    for path, text in staged.items():
        if path.read_text() != text:
            changes.append((path, text.encode()))
    for path, content in changes:
        write_changed(path, content)


def patch_native_engine_libraries(source):
    changes = []
    for relative, condition, library, count in (
            ('js/src/build/moz.build', '!= "WINNT"', 'm', 1),
            ('toolkit/library/moz.build', '== "FreeBSD"', 'util', 2)):
        path = Path(source) / relative
        text = path.read_text()
        old = (f'if CONFIG["OS_ARCH"] {condition}:\n'
               f'    OS_LIBS += [\n        "{library}",\n    ]')
        new = old.replace(':\n', ' and not CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n', 1)
        if text.count(new) == count:
            continue
        if text.count(old) != count or new in text:
            raise RuntimeError('Native engine system library drift: ' + relative)
        changes.append((path, text.replace(old, new).encode()))
    for path, content in changes:
        write_changed(path, content)


def patch_native_ffvpx_math(source):
    old = "if CONFIG['OS_TARGET'] != 'WINNT':\n    OS_LIBS += ['m']"
    new = ("# Native SDK math is provided by real system-libc imports, not libm.\n"
           "if CONFIG['OS_TARGET'] != 'WINNT' and not CONFIG['MOZ_ORBIS_HOMEBREW_SDK']:\n"
           "    OS_LIBS += ['m']")
    changes = []
    for library in ('libavutil', 'libavcodec'):
        path = Path(source) / 'media/ffvpx' / library / 'moz.build'
        text = path.read_text()
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError('Native FFVPX math library drift: ' + library)
            changes.append((path, text.replace(old, new).encode()))
    for path, content in changes:
        write_changed(path, content)


def patch_native_dav1d_headers(source):
    path = Path(source) / 'third_party/dav1d/src/mem.h'
    text = path.read_text()
    old = '#if defined(_WIN32) || HAVE_MEMALIGN\n#include <malloc.h>\n#endif'
    new = ('// Native BSD uses the declared POSIX allocation branch below; its\n'
           '// malloc.h is an intentional error header, not an allocator API.\n'
           '#if defined(_WIN32) || (HAVE_MEMALIGN && \\\n'
           '    !(defined(ORBISFOX_HOMEBREW_SDK) && HAVE_POSIX_MEMALIGN))\n'
           '#include <malloc.h>\n#endif')
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Native dav1d allocator header drift')
        write_changed(path, text.replace(old, new).encode())


def patch_native_signal_stack(source):
    path = Path(source) / 'third_party/abseil-cpp/absl/debugging/failure_signal_handler.cc'
    text = path.read_text()
    replacements = (
        ('  sigstk.ss_sp = mmap(nullptr, sigstk.ss_size, PROT_READ | PROT_WRITE,\n'
         '                      MAP_PRIVATE | MAP_ANONYMOUS | MAP_STACK, -1, 0);',
         '  sigstk.ss_sp = static_cast<decltype(sigstk.ss_sp)>(\n'
         '      mmap(nullptr, sigstk.ss_size, PROT_READ | PROT_WRITE,\n'
         '           MAP_PRIVATE | MAP_ANONYMOUS | MAP_STACK, -1, 0));'),
        ('  sigstk.ss_sp = malloc(sigstk.ss_size);',
         '  sigstk.ss_sp = static_cast<decltype(sigstk.ss_sp)>(malloc(sigstk.ss_size));'))
    # Both native BSD char* and modern void* fields retain their real type.
    # Do not change the stack allocation, protection or fatal error policy.
    for old, new in replacements:
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError('Native alternate signal stack declaration drift')
            text = text.replace(old, new)
    write_changed(path, text.encode())


def patch_native_js_stack(source):
    path = Path(source) / 'js/src/util/NativeStack.cpp'
    text = path.read_text()
    include = '#include "util/NativeStack.h"\n'
    header = include + '\n#ifdef ORBISFOX_HOMEBREW_SDK\n#  include <pthread_np.h>\n#endif\n'
    anchor = '#elif defined(__wasi__)\n\n// Since we rearrange the layout'
    native = '''#elif defined(ORBISFOX_HOMEBREW_SDK)

void* js::GetNativeStackBaseImpl() {
  pthread_attr_t attributes;
  MOZ_RELEASE_ASSERT(pthread_attr_init(&attributes) == 0,
                     "native pthread_attr_init failed");
  const int queried = pthread_attr_get_np(pthread_self(), &attributes);
  void* stackBase = nullptr;
  size_t stackSize = 0;
  const int described = queried == 0
      ? pthread_attr_getstack(&attributes, &stackBase, &stackSize) : queried;
  const int destroyed = pthread_attr_destroy(&attributes);
  MOZ_RELEASE_ASSERT(queried == 0, "native pthread_attr_get_np failed");
  MOZ_RELEASE_ASSERT(described == 0, "native pthread_attr_getstack failed");
  MOZ_RELEASE_ASSERT(destroyed == 0, "native pthread_attr_destroy failed");
  MOZ_RELEASE_ASSERT(stackBase && stackSize, "invalid native thread stack");
  const uintptr_t low = reinterpret_cast<uintptr_t>(stackBase);
  MOZ_RELEASE_ASSERT(stackSize <= UINTPTR_MAX - low, "native stack range overflow");
#  if JS_STACK_GROWTH_DIRECTION > 0
  return stackBase;
#  else
  return reinterpret_cast<void*>(low + stackSize);
#  endif
}

''' + anchor
    # Refuse partially edited prior output instead of inserting a second branch.
    if (('#ifdef ORBISFOX_HOMEBREW_SDK' in text and header not in text) or
            ('#elif defined(ORBISFOX_HOMEBREW_SDK)\n\nvoid*' in text and native not in text)):
        raise RuntimeError('Native JavaScript stack query drift')
    # Validate every owned insertion before changing either one.
    for old, new in ((include, header), (anchor, native)):
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError('Native JavaScript stack query drift')
            text = text.replace(old, new)
    write_changed(path, text.encode())


def patch_allocator_fallback(source):
    path = source / 'memory/build/Fallback.cpp'
    text = path.read_text()
    # Migrate the known first native adaptation without accepting arbitrary
    # edits. With a genuine exported memalign, import it rather than exporting
    # a same-named POSIX fallback from the browser.
    previous = ('#if defined(MOZ_ORBIS_HOMEBREW_SDK)\n'
                '#  include <errno.h>\n'
                '#endif\n'
                '// The native SDK exports memalign but does not declare it. Use the\n'
                '// existing POSIX fallback with the same SDK allocator ownership.\n'
                '#if !defined(HAVE_MEMALIGN) || defined(MOZ_ORBIS_HOMEBREW_SDK)\n')
    if previous in text:
        text = text.replace(previous, '#ifndef HAVE_MEMALIGN\n')
    replacements = [
        ('#ifndef HAVE_MEMALIGN\n',
         '#if defined(MOZ_ORBIS_HOMEBREW_SDK)\n'
         '#  include <errno.h>\n'
         '#  ifdef HAVE_MEMALIGN\n'
         '// Native libc exports this API but the SDK omits its declaration.\n'
         'extern "C" void* memalign(size_t, size_t);\n'
         '#  endif\n'
         '#endif\n'
         '#ifndef HAVE_MEMALIGN\n'),
        ('  if (posix_memalign(&ret, aAlignment, aSize) != 0) {\n'
         '    return nullptr;\n',
         '  const int error = posix_memalign(&ret, aAlignment, aSize);\n'
         '  if (error != 0) {\n'
         '#  ifdef MOZ_ORBIS_HOMEBREW_SDK\n'
         '    errno = error;\n'
         '#  endif\n'
         '    return nullptr;\n'),
    ]
    for old, new in replacements:
        if new in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError('Pinned Gecko native allocator fallback drift')
        text = text.replace(old, new)
    declaration = source / 'memory/mozalloc/mozalloc.cpp'
    original = declaration.read_text()
    old_guard = '#  ifndef HAVE_MEMALIGN\n// We always have a definition of memalign'
    new_guard = ('#  if !defined(HAVE_MEMALIGN) || defined(MOZ_ORBIS_HOMEBREW_SDK)\n'
                 '// We always have a definition of memalign')
    if new_guard not in original and original.count(old_guard) != 1:
        raise RuntimeError('Pinned Gecko native allocator fallback declaration drift')
    # Validate the definition AND its consumer before either file is changed.
    write_changed(path, text.encode())
    write_changed(declaration, original.replace(old_guard, new_guard).encode())


def patch_native_ffi(source):
    # Sony's native compiler supports the platform SysV ABI, not ms_abi.
    # Keep working native calls; never compile a Windows closure as SysV.
    changes = {}

    def replace(relative, old, new, count=1):
        path = source / relative
        text = changes.get(path, path.read_text())
        if text.count(new) == count and text.count(old) == new.count(old) * count:
            return
        if text.count(old) != count or new in text:
            raise RuntimeError('Pinned Gecko native libffi ABI drift: ' + relative)
        changes[path] = text.replace(old, new)

    replace('config/external/ffi/moz.build',
            '        ffi_srcs = ("ffi64.c", "unix64.S", "ffiw64.c", "win64.S")',
            '        ffi_srcs = ("ffi64.c", "unix64.S")\n'
            '        if not CONFIG["MOZ_ORBIS_HOMEBREW_SDK"]:\n'
            '            ffi_srcs += ("ffiw64.c", "win64.S")')
    relative = 'js/src/ctypes/libffi/src/x86/ffi64.c'
    replace(relative,
            '#ifndef __ILP32__\n  if (cif->abi == FFI_EFI64 || cif->abi == FFI_GNUW64)',
            '#if !defined(__ILP32__) && !defined(ORBISFOX_HOMEBREW_SDK)\n'
            '  if (cif->abi == FFI_EFI64 || cif->abi == FFI_GNUW64)', count=5)
    for signature in (
        'ffi_call (ffi_cif *cif, void (*fn)(void), void *rvalue, void **avalue)\n{\n',
        'ffi_call_go (ffi_cif *cif, void (*fn)(void), void *rvalue,\n'
        '\t     void **avalue, void *closure)\n{\n',
    ):
        replace(relative, signature,
                signature + '#ifdef ORBISFOX_HOMEBREW_SDK\n'
                '  /* A prepared native cif cannot name an unsupported ABI. */\n'
                '  if (cif->abi != FFI_UNIX64)\n'
                '    abort ();\n'
                '#endif\n')
    # Validate both build selection and all dispatch sites before any write.
    for path, text in changes.items():
        write_changed(path, text.encode())


def patch_maybe_constexpr(source):
    # FreeBSD libc++ ABI v1 deliberately gives std::pair a nontrivial copy
    # constructor. Keep that ABI: C++20 permits constexpr storage/destructors
    # for this literal type without claiming that its copy is trivial.
    changes = []
    blocks = [
        ('mfbt/MaybeStorageBase.h', 'struct MaybeStorageBase<T, false> {',
         'template <typename T>\nstruct MaybeStorageBase<T, true>', [
             ('    explicit Union(', '    constexpr explicit Union('),
             ('    ~Union() {}', '    constexpr ~Union() {}'),
             ('  explicit MaybeStorageBase(', '  constexpr explicit MaybeStorageBase('),
             ('  const T* addr() const', '  constexpr const T* addr() const'),
             ('  T* addr()', '  constexpr T* addr()'),
         ]),
        ('mfbt/Maybe.h', 'struct MaybeStorage<T, false> : MaybeStorageBase<T> {',
         '#ifdef __GNUC__\n#  pragma GCC diagnostic push', [
             ('  explicit MaybeStorage(', '  constexpr explicit MaybeStorage('),
             ('  MaybeStorage(const MaybeStorage&)', '  constexpr MaybeStorage(const MaybeStorage&)'),
             ('  MaybeStorage(MaybeStorage&&)', '  constexpr MaybeStorage(MaybeStorage&&)'),
             # Only the trivially destructible payload needs constexpr here.
             # Making the nontrivial destructor constexpr eagerly instantiates
             # nested DOM union cleanup while its owning type is incomplete.
             ('  ~MaybeStorage() {',
              '  constexpr ~MaybeStorage() requires(std::is_trivially_destructible_v<T>) {}\n'
              '  ~MaybeStorage() requires(!std::is_trivially_destructible_v<T>) {'),
         ]),
    ]
    for relative, start, end, replacements in blocks:
        path = source / relative
        text = path.read_text()
        if text.count(start) != 1 or text.count(end) != 1:
            raise RuntimeError('Pinned Gecko constexpr Maybe storage drift: ' + relative)
        head, body = text.split(start)
        body, tail = body.split(end)
        # Recognize only the earlier owned unconditional-constexpr adaptation.
        body = body.replace('  constexpr ~MaybeStorage() {', '  ~MaybeStorage() {')
        for old, new in replacements:
            if new in body and old not in body:
                continue
            if old not in body or new in body:
                raise RuntimeError('Pinned Gecko constexpr Maybe storage drift: ' + relative)
            body = body.replace(old, new)
        changes.append((path, head + start + body + end + tail))
    # Both storage layers must validate before either file changes.
    for path, text in changes:
        write_changed(path, text.encode())


def prepare(source):
    source = Path(source)
    result = prepare_libc(source)
    patch_rust_detection(source)
    patch_allocator_fallback(source)
    patch_native_ffi(source)
    patch_maybe_constexpr(source)
    return result


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
