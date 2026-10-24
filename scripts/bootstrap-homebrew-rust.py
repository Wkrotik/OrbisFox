#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install pristine pinned Rust sources and native-SDK-only ABI adaptations.

Never follows the old SDK sysroot symlink for writes. No target execution.
"""
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
SYSROOT = ROOT / '.deps/rust-homebrew-sysroot'


def replace(file, old, new, count=1):
    text = file.read_text()
    if new not in text:
        if text.count(old) != count:
            raise RuntimeError('Pinned native Rust source drift: ' + str(file))
        file.write_text(text.replace(old, new))


def patch_libc(root):
    # The native SDK uses the original small-inode FreeBSD ABI. libc has no
    # FreeBSD-9 selector; its FreeBSD-11 layout has the matching fields, which
    # must still pass the independent C/Rust ABI table comparison.
    replace(root / 'build.rs', 'let which_freebsd = if let Ok(version)',
            'let which_freebsd = if env::var("CARGO_CFG_TARGET_VENDOR").as_deref() == Ok("scei") { 11 } else if let Ok(version)')
    for relative, old, new in (
        ('src/unix/bsd/freebsdlike/freebsd/x86_64/mod.rs', 'pub type wchar_t = i32;',
         '#[cfg(not(target_vendor = "scei"))]\npub type wchar_t = i32;\n#[cfg(target_vendor = "scei")]\npub type wchar_t = u16;'),
        ('src/unix/bsd/freebsdlike/freebsd/mod.rs', 'pub type blksize_t = i32;',
         '#[cfg(not(target_vendor = "scei"))]\npub type blksize_t = i32;\n#[cfg(target_vendor = "scei")]\npub type blksize_t = u32;'),
    ):
        replace(root / relative, old, new)
    for file in (root / 'src/unix').rglob('*.rs'):
        text = file.read_text()
        pattern = r'#\[cfg_attr\(([^\]]*?),\s*link_name = "([^"\n]+@FBSD_[^"\n]+)"\s*\)\]'
        def unversion(match):
            condition, symbol = match.groups()
            if 'target_vendor = "scei"' in condition:
                return match.group(0)
            return f'#[cfg_attr(all(not(target_vendor = "scei"), {condition}), link_name = "{symbol}")]'
        new = re.sub(pattern, unversion, text)
        if new != text:
            file.write_text(new)
    checksum = root / '.cargo-checksum.json'
    hashes = json.loads(checksum.read_text())
    # Preserve package identity; record all deliberate source changes locally.
    for name in hashes['files']:
        hashes['files'][name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    updated = json.dumps(hashes, sort_keys=True)
    if checksum.read_text() != updated:
        checksum.write_text(updated)


def patch_native_std_io(library):
    # Command 17 returns success-shaped zero on the console without cloning.
    # Own the genuine dup before checked CLOEXEC setup, including fd 0.
    file = library / 'std/src/os/fd/owned.rs'
    old = '''    #[cfg(not(any(
        all(target_arch = "wasm32", not(target_os = "emscripten")),
        target_os = "hermit",
        target_os = "trusty",
        target_os = "motor"
    )))]'''
    new = '''    #[cfg(target_vendor = "scei")]
    #[stable(feature = "io_safety", since = "1.63.0")]
    pub fn try_clone_to_owned(&self) -> io::Result<OwnedFd> {
        // Genuine checked, non-atomic CLOEXEC duplication; no fork/exec guarantee.
        let fd = cvt(unsafe { libc::dup(self.as_raw_fd()) })?;
        let fd = unsafe { crate::sys::fd::FileDesc::from_raw_fd(fd) };
        fd.set_cloexec()?;
        Ok(fd.into_inner())
    }

''' + old.replace('#[cfg(not(any(', '#[cfg(not(any(\n        target_vendor = "scei",', 1)
    replace(file, old, new)
    file = library / 'std/src/sys/fd/unix.rs'
    # Select both sides of upstream's ioctl/fcntl setter cfg together.
    for old in ('    #[cfg(not(any(\n        target_env = "newlib",',
                '    #[cfg(any(\n        all(\n            target_env = "newlib",'):
        new = old.replace('any(\n', 'any(\n        target_vendor = "scei",\n', 1)
        replace(file, old, new)
    # Use upstream's checked descriptor-owning fallbacks. Never export fake
    # pipe2/accept4 symbols or silently ignore CLOEXEC setup failures.
    replace(library / 'std/src/sys/pipe/unix.rs',
            '            target_os = "freebsd",',
            '            all(target_os = "freebsd", not(target_vendor = "scei")),')
    file = library / 'std/src/sys/net/connection/socket/unix.rs'
    text = file.read_text()
    start = text.index('    pub fn accept(&self,')
    end = text.index('    pub fn duplicate(&self)', start)
    before = text[start:end]
    old = '                target_os = "freebsd",'
    new = '                all(target_os = "freebsd", not(target_vendor = "scei")),'
    if new not in before:
        if before.count(old) != 1:
            raise RuntimeError('Pinned native Rust accept fallback drift')
        file.write_text(text[:start] + before.replace(old, new) + text[end:])
    file = library / 'std/src/sys/fs/unix.rs'
    # The SDK lacks the timestamp APIs with UTIME_OMIT/NOFOLLOW semantics.
    # Select upstream's explicit Unsupported errors, never fake timestamps or
    # approximate omitted fields with a racy read/modify/write sequence.
    for old in (
            'any(target_os = "redox", target_os = "espidf", target_os = "horizon", target_os = "nuttx", target_os = "l4re") => {',
            'any(target_os = "redox", target_os = "espidf", target_os = "horizon", target_os = "nuttx", target_os = "vita", target_os = "rtems") => {'):
        replace(file, old, old.replace('any(', 'any(target_vendor = "scei", ', 1))
    file = library / 'std/src/os/unix/net/ucred.rs'
    text = file.read_text()
    start = text.index('mod impl_bsd {')
    end = text.index('\n#[cfg(target_vendor = "apple")]', start)
    before = text[start:end]
    old = ('    pub fn peer_cred(socket: &UnixStream) -> io::Result<UCred> {\n'
           '        let mut cred = UCred { uid: 1, gid: 1, pid: None };\n'
           '        unsafe {\n'
           '            let ret = libc::getpeereid(socket.as_raw_fd(), &mut cred.uid, &mut cred.gid);\n\n'
           '            if ret == 0 { Ok(cred) } else { Err(io::Error::last_os_error()) }\n'
           '        }\n'
           '    }')
    new = ('    pub fn peer_cred(socket: &UnixStream) -> io::Result<UCred> {\n'
           '        #[cfg(target_vendor = "scei")]\n'
           '        {\n'
           '            let _ = socket;\n'
           '            Err(io::const_error!(io::ErrorKind::Unsupported, "peer credentials unavailable in native SDK"))\n'
           '        }\n'
           '        #[cfg(not(target_vendor = "scei"))]\n'
           '        {\n'
           '            let mut cred = UCred { uid: 1, gid: 1, pid: None };\n'
           '            unsafe {\n'
           '                let ret = libc::getpeereid(socket.as_raw_fd(), &mut cred.uid, &mut cred.gid);\n'
           '                if ret == 0 { Ok(cred) } else { Err(io::Error::last_os_error()) }\n'
           '            }\n'
           '        }\n'
           '    }')
    if new not in before:
        if before.count(old) != 1:
            raise RuntimeError('Pinned native Rust peer credential drift')
        file.write_text(text[:start] + before.replace(old, new) + text[end:])


def patch_std(library):
    # The SDK has no dl_iterate_phdr module-enumeration API. Keep genuine
    # libunwind stack PCs, but select upstream's unavailable-symbolization
    # backend rather than returning invented module headers or names.
    replace(library / 'backtrace/src/symbolize/mod.rs',
            '        not(target_vendor = "uwp"),\n        not(target_os = "emscripten"),',
            '        not(target_vendor = "uwp"),\n        not(target_vendor = "scei"),\n        not(target_os = "emscripten"),')
    random = library / 'std/src/sys/random/mod.rs'
    replace(random, 'cfg_select! {\n    // Tier 1',
            'cfg_select! {\n    target_vendor = "scei" => {\n        mod unix_legacy;\n        pub use unix_legacy::fill_bytes;\n    }\n    // Tier 1')
    # Select upstream's genuine pthread/queue backends, not modern FreeBSD
    # timed-umtx structures that differ from the console's FreeBSD-9 ABI.
    for name in ('mutex', 'condvar', 'once', 'rwlock', 'thread_parking'):
        file = library / f'std/src/sys/sync/{name}/mod.rs'
        replace(file, 'target_os = "freebsd",',
                'all(target_os = "freebsd", not(target_vendor = "scei")),')
    file = library / 'std/src/sys/thread/unix.rs'
    # Preserve CPU-count error handling and the native SDK's real sysconf.
    replace(file, '#[cfg(target_os = "freebsd")]\n            {',
            '#[cfg(all(target_os = "freebsd", not(target_vendor = "scei")))]\n            {')
    # Native SDK exports the older, genuinely void-returning BSD name setter.
    # Do not alias it to modern pthread_setname_np's int-returning declaration.
    replace(file, '    target_os = "linux",\n    target_os = "freebsd",\n    target_os = "dragonfly",',
            '    target_os = "linux",\n    all(target_os = "freebsd", not(target_vendor = "scei")),\n    target_os = "dragonfly",')
    replace(file, '#[cfg(target_os = "openbsd")]\npub fn set_name(name: &CStr) {',
            '#[cfg(target_vendor = "scei")]\npub fn set_name(name: &CStr) {\n    unsafe { libc::pthread_set_name_np(libc::pthread_self(), name.as_ptr()) };\n}\n\n#[cfg(target_os = "openbsd")]\npub fn set_name(name: &CStr) {')
    # This SDK does not provide clock_nanosleep. Use upstream's relative
    # nanosleep path with EINTR remainder handling, never a fake success shim.
    replace(file, '        // Any unix that has clock_nanosleep\n        // If this list changes update the MIRI chock_nanosleep shim\n        any(\n            target_os = "freebsd",',
            '        // Any unix that has clock_nanosleep\n        // If this list changes update the MIRI chock_nanosleep shim\n        any(\n            all(target_os = "freebsd", not(target_vendor = "scei")),')
    replace(file, '#[cfg(any(\n    target_os = "freebsd",\n    target_os = "netbsd",\n    target_os = "linux",',
            '#[cfg(any(\n    all(target_os = "freebsd", not(target_vendor = "scei")),\n    target_os = "netbsd",\n    target_os = "linux",')
    # Select Rust's deadline-checked generic sleep_until fallback as well.
    replace(library / 'std/src/sys/thread/mod.rs', 'target_os = "freebsd",',
            'all(target_os = "freebsd", not(target_vendor = "scei")),', count=2)
    replace(library / 'std/src/sys/pal/unix/sync/mod.rs', 'target_os = "freebsd",',
            'all(target_os = "freebsd", not(target_vendor = "scei")),')
    replace(library / 'std/src/sys/fs/unix.rs', 'd_ino: (*entry_ptr).d_fileno,',
            'd_ino: (*entry_ptr).d_fileno as u64,')


def bootstrap():
    pin = runpy.run_path(str(ROOT / 'scripts/bootstrap-rust.py'))
    version = subprocess.check_output(['rustc', '--version'], text=True)
    if not version.startswith('rustc ' + pin['VERSION'] + ' '):
        raise RuntimeError('Native Rust compiler/source version mismatch')
    marker = SYSROOT / '.source-sha256'
    if SYSROOT.is_symlink():
        raise RuntimeError('Native Rust sysroot must not alias old SDK inputs')
    if not marker.exists():
        if SYSROOT.exists():
            raise RuntimeError('Incomplete native Rust export; inspect before retrying')
        archive = ROOT / '.deps/rust-src.tar.xz'
        if not archive.exists():
            cached = (ROOT / '.deps/rust-sysroot').resolve().parent / 'rust-src.tar.xz'
            if cached.is_file():
                archive = cached  # Read-only reuse, no copy or modification.
            else:
                with urllib.request.urlopen(f'https://static.rust-lang.org/dist/rust-src-{pin["VERSION"]}.tar.xz', timeout=60) as response:
                    archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != pin['SHA256']:
            raise RuntimeError('Pinned native Rust source archive SHA-256 mismatch')
        SYSROOT.mkdir(parents=True)
        with tarfile.open(archive) as source:
            for member in source:
                parts = Path(member.name).parts
                if len(parts) > 2 and parts[1:3] == ('rust-src', 'lib'):
                    if '..' in parts or Path(member.name).is_absolute():
                        raise RuntimeError('Unsafe Rust source archive entry')
                    member.name = str(Path(*parts[2:]))
                    source.extract(member, SYSROOT, filter='data')
        marker.write_text(pin['SHA256'] + '\n')
    elif marker.read_text().strip() != pin['SHA256']:
        raise RuntimeError('Native Rust source pin changed')
    host = subprocess.check_output(['rustc', '-vV'], text=True).split('host: ', 1)[1].splitlines()[0]
    system = Path(subprocess.check_output(['rustc', '--print', 'sysroot'], text=True).strip())
    library = SYSROOT / 'lib/rustlib' / host
    if not library.exists():
        library.symlink_to(system / 'lib/rustlib' / host, target_is_directory=True)
    source = SYSROOT / 'lib/rustlib/src/rust/library'
    patch_libc(source / 'vendor/libc-0.2.189')
    patch_std(source)
    patch_native_std_io(source)
    return source


if __name__ == '__main__':
    print(bootstrap())
