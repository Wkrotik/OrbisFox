#!/usr/bin/env python3
"""Adapt the audited OpenOrbis ABI differences in a private vendored libc crate."""
import hashlib
import json
import re
from pathlib import Path
import sys


def patch_layout(root):
    # libc 0.2.189 removed the old FreeBSD-version environment override.
    # Force the audited baseline only for our vendor, including build-std.
    updates = {
        'build.rs': ('let which_freebsd = if let Ok(version)',
                     'let which_freebsd = if env::var("CARGO_CFG_TARGET_VENDOR").as_deref() == Ok("orbis") { 11 } else if let Ok(version)'),
        'src/unix/bsd/freebsdlike/freebsd/freebsd11/b64.rs':
            ('        pub st_lspare: i32,', '        #[cfg(not(target_vendor = "orbis"))]\n        pub st_lspare: i32,'),
        'src/unix/bsd/freebsdlike/freebsd/mod.rs':
            ('pub type blksize_t = i32;', '#[cfg(not(target_vendor = "orbis"))]\npub type blksize_t = i32;\n#[cfg(target_vendor = "orbis")]\npub type blksize_t = u32;'),
    }
    # SDK libc translates POSIX clock IDs; these are not kernel BSD IDs.
    clockfile = 'src/unix/bsd/freebsdlike/mod.rs'
    for name, oldvalue, newvalue in [('MONOTONIC', 4, 1), ('THREAD_CPUTIME_ID', 14, 3), ('PROCESS_CPUTIME_ID', 15, 2)]:
        old = f'pub const CLOCK_{name}: crate::clockid_t = {oldvalue};'
        new = f'#[cfg(not(target_vendor = "orbis"))]\n{old}\n#[cfg(target_vendor = "orbis")]\npub const CLOCK_{name}: crate::clockid_t = {newvalue};'
        file = root / clockfile
        text = file.read_text()
        if new not in text:
            if text.count(old) != 1:
                raise RuntimeError(f'Unexpected clock constant: {name}')
            file.write_text(text.replace(old, new))
    text = (root / clockfile).read_text()
    old = '    pub fn pthread_setname_np(thread: crate::pthread_t, name: *const c_char) -> c_int;'
    new = '    #[cfg_attr(target_vendor = "orbis", link_name = "pthread_set_name_np")]\n' + old
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Unexpected pthread name setter')
        (root / clockfile).write_text(text.replace(old, new))
    errno_file = root / 'src/unix/bsd/freebsdlike/freebsd/mod.rs'
    text = errno_file.read_text()
    old = '    pub fn __error() -> *mut c_int;'
    new = '    #[cfg_attr(target_vendor = "orbis", link_name = "__errno_location")]\n' + old
    if new not in text:
        if text.count(old) != 1:
            raise RuntimeError('Unexpected errno accessor')
        errno_file.write_text(text.replace(old, new))
    checksum = root / '.cargo-checksum.json'
    hashes = json.loads(checksum.read_text()) if checksum.exists() else None
    for relative, (old, new) in updates.items():
        file = root / relative
        text = file.read_text()
        if new in text:
            continue
        if text.count(old) != 1:
            raise RuntimeError(f'Unexpected libc layout declaration: {relative}')
        file.write_text(text.replace(old, new))
        if hashes is not None:
            hashes['files'][relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    for file in (root / 'src/unix').rglob('*.rs'):
        text = file.read_text()
        pattern = r'#\[cfg_attr\(([^\]]*?),\s*link_name = "([^"\n]+@FBSD_[^"\n]+)"\s*\)\]'
        def unversion(match):
            condition, symbol = match.groups()
            if 'target_vendor = "orbis"' in condition:
                return match.group(0)
            return f'#[cfg_attr(all(not(target_vendor = "orbis"), {condition}), link_name = "{symbol}")]'
        new = re.sub(pattern, unversion, text)
        if new != text:
            file.write_text(new)
            if hashes is not None:
                hashes['files'][str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
    if hashes is not None:
        for relative in (clockfile, 'src/unix/bsd/freebsdlike/freebsd/mod.rs'):
            hashes['files'][relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        updated_checksum = json.dumps(hashes, sort_keys=True)
        if checksum.read_text() != updated_checksum:
            checksum.write_text(updated_checksum)


def patch(root):
    patch_layout(root)
    path = root / 'src/unix/bsd/freebsdlike/mod.rs'
    text = path.read_text()
    if 'ORBisFox OpenOrbis ABI' in text:
        # Migrate the earlier SDK-matching declarations: firmware attributes
        # are eight-byte handles, not four-byte musl words (0.10 klog evidence).
        updated = text
        for name, count in (('pthread_mutexattr_t', 1), ('pthread_condattr_t', 1), ('pthread_rwlockattr_t', 2)):
            old = f'pub struct {name} {{ pub storage: [u32; {count}] }}'
            new = f'pub struct {name} {{ pub storage: [u64; 1] }}'
            if old in updated:
                updated = updated.replace(old, new)
            elif new not in updated:
                raise RuntimeError('Unexpected patched pthread attribute: ' + name)
        if updated != text:
            path.write_text(updated)
            checksum = root / '.cargo-checksum.json'
            if checksum.exists():
                data = json.loads(checksum.read_text())
                data['files'][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
                checksum.write_text(json.dumps(data, sort_keys=True))
        return
    aliases = {'mode_t': ('u16', 'u32'), 'pthread_key_t': ('c_int', 'c_uint')}
    storage = {'pthread_attr_t': (7, 'u64'), 'pthread_mutex_t': (5, 'u64'),
               'pthread_cond_t': (6, 'u64'), 'pthread_rwlock_t': (7, 'u64'),
               'pthread_mutexattr_t': (1, 'u64'), 'pthread_condattr_t': (1, 'u64'),
               'pthread_rwlockattr_t': (1, 'u64')}
    for name, (old, new) in aliases.items():
        original = f'pub type {name} = {old};'
        if text.count(original) != 1:
            raise RuntimeError(f'Unexpected libc declaration: {name}')
        text = text.replace(original, f'#[cfg(not(target_vendor = "orbis"))]\n{original}\n'
                            f'#[cfg(target_vendor = "orbis")]\npub type {name} = {new};')
    for name, (count, scalar) in storage.items():
        original = f'pub type {name} = *mut c_void;'
        if text.count(original) != 1:
            raise RuntimeError(f'Unexpected libc declaration: {name}')
        text = text.replace(original, f'#[cfg(not(target_vendor = "orbis"))]\n{original}\n'
                            f'#[cfg(target_vendor = "orbis")]\n#[repr(C)]\n#[derive(Clone, Copy)]\n'
                            f'pub struct {name} {{ pub storage: [{scalar}; {count}] }}')
    for kind in ('MUTEX', 'COND', 'RWLOCK'):
        name = 'pthread_' + kind.lower() + '_t'
        count, _ = storage[name]
        original = f'pub const PTHREAD_{kind}_INITIALIZER: {name} = ptr::null_mut();'
        if text.count(original) != 1:
            raise RuntimeError(f'Unexpected initializer: {kind}')
        text = text.replace(original, f'#[cfg(not(target_vendor = "orbis"))]\n{original}\n'
                            f'#[cfg(target_vendor = "orbis")]\npub const PTHREAD_{kind}_INITIALIZER: {name} = {name} {{ storage: [0; {count}] }};')
    path.write_text('// ORBisFox OpenOrbis ABI: vendor-gated; stock FreeBSD remains unchanged.\n' + text)
    # Cargo directory sources validate every file against this manifest. This
    # intentional local patch changes its file hash; retain the source archive
    # pin and patch script as the reproducible record of the transformation.
    checksum = root / '.cargo-checksum.json'
    if checksum.exists():
        data = json.loads(checksum.read_text())
        data['files'][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        checksum.write_text(json.dumps(data, sort_keys=True))
    print('Applied vendor-gated OpenOrbis libc storage/scalar adaptation:', root)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
