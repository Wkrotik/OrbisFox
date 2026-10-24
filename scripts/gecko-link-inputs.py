# SPDX-License-Identifier: MIT
"""Read genuine SDK-neutral Gecko link inputs without writing an object tree.

The caller owns CRT/runtime/media selection and final-ELF verification. A host
DSO response is an object inventory, never a license to ship that desktop DSO.
"""
from pathlib import Path
import shlex

RUST_TARGETS = {'x86_64-orbis-freebsd', 'x86_64-scei-ps4'}
NSS_STATIC_COMPONENTS = ('pk11wrap_pk11wrap_static', 'softoken_softokn_static', 'freebl_freebl_static')
NSS_DESKTOP_LISTS = {'libsoftokn3_so.list', 'libfreebl3_so.list', 'libfreeblpriv3_so.list'}


def confined_file(path, engine):
    path = Path(path).resolve()
    if not path.is_file() or not path.is_relative_to(engine):
        raise ValueError('Missing or out-of-lane Gecko object: ' + str(path))
    return path


def response_objects(path, engine):
    """Validate every response token and resolved path, including symlinks."""
    engine = Path(engine).resolve()
    path = confined_file(path, engine)
    result = []
    for token in shlex.split(path.read_text()):
        if token in ('--whole-archive', '--no-whole-archive'):
            continue
        if not token.endswith(('.o', '.a')):
            raise ValueError('Unsupported Gecko response input: ' + token)
        result.append(confined_file(path.parent / token, engine))
    return result


def collect_engine_inputs(engine, rust_target):
    """Return real direct/lazy inputs; never choose or silently mix SDKs."""
    if not isinstance(rust_target, str) or rust_target not in RUST_TARGETS:
        raise ValueError('Unsupported engine Rust target: ' + str(rust_target))
    engine = Path(engine).resolve()
    xul = response_objects(engine / 'toolkit/library/build/libxul_so.list', engine)
    host = response_objects(engine / 'js/xpconnect/shell/xpcshell.list', engine)
    xul += [item for item in host if item.name != 'xpcshell.o' and item not in xul]
    nss = response_objects(engine / 'security/nss/lib/nss/nss_nss3/libnss3_so.list', engine)
    for component in NSS_STATIC_COMPONENTS:
        if not any(component in item.parts for item in nss):
            raise RuntimeError('Missing upstream static NSS closure: ' + component)
    if any(item.name == 'loader.o' for item in nss):
        raise RuntimeError('Static NSS closure still contains its desktop freebl DLL loader')
    lists = sorted((engine / 'config/external').glob('**/*_so.list'))
    lists += sorted((engine / 'security/nss/lib').glob('**/*_so.list'))
    codecs = [engine / relative for relative in ('media/ffvpx/libavcodec/libmozavcodec_so.list',
                                                'media/ffvpx/libavutil/libmozavutil_so.list')]
    for path in codecs:
        if not path.is_file():
            raise RuntimeError('Missing actual pinned static FFVPX object list: ' + str(path))
        lists.append(path)
    support = []
    for index, path in enumerate(lists):
        if path.name not in NSS_DESKTOP_LISTS:
            support.append({'index': index, 'response': path,
                            'objects': response_objects(path, engine)})
    nspr = {}
    for name in ('pr', 'libc', 'ds'):
        paths = sorted((engine / 'config/external/nspr' / name).glob('*.o'))
        if not paths:
            raise RuntimeError('Missing NSPR native objects: ' + name)
        nspr[name] = [confined_file(path, engine) for path in paths]
    archives = [engine / relative for relative in (
        'third_party/angle/translator_gn/libtranslator_gn.a',
        'third_party/angle/angle_common_gn/libangle_common_gn.a',
        'third_party/angle/angle_common_shader_state_gn/libangle_common_shader_state_gn.a',
        'third_party/angle/preprocessor_gn/libpreprocessor_gn.a',
        'js/src/build/libjs_static.a', 'build/pure_virtual/libpure_virtual.a',
        rust_target + '/release/libgkrust.a')]
    return {'direct': xul, 'static_nss': nss, 'codec_responses': codecs, 'support': support, 'nspr': nspr,
            'archives': [confined_file(path, engine) for path in archives]}
