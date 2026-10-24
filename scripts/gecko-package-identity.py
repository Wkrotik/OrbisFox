# SPDX-License-Identifier: MIT
"""Fixed allowlisted package identities; reports cannot select arbitrary paths."""
def package_directories(sdk='openorbis'):
    if sdk not in ('openorbis', 'homebrew'):
        raise ValueError('Unknown package SDK')
    return ('build/gecko-app-homebrew', 'dist/gecko-homebrew') if sdk == 'homebrew' else ('build/gecko-app', 'dist/gecko')


def package_identity(mesa=False, sdk='openorbis'):
    package_directories(sdk)
    if sdk == 'homebrew':
        if mesa:
            raise ValueError('Native SDK Mesa packaging is not implemented')
        return {'title': 'OrbisFox SDK Test', 'title_id': 'ORHB00001',
                'content_id': 'IV0000-ORHB00001_00-ORBISFOXPROBE000',
                'package_name': 'OrbisFox-Homebrew.pkg',
                'profile': '/data/orbisfox/homebrew-profile'}
    title_id = 'ORME00001' if mesa else 'ORBF00001'
    return {'title': 'OrbisFox Mesa Test' if mesa else 'OrbisFox',
            'title_id': title_id,
            'content_id': f'IV0000-{title_id}_00-ORBISFOXPROBE000',
            'package_name': 'OrbisFox-Mesa.pkg' if mesa else 'OrbisFox.pkg',
            'profile': '/data/orbisfox/mesa-profile' if mesa else '/data/orbisfox/gecko-profile'}


def report_identity(report):
    mesa = report.get('experimental_mesa', False)
    if type(mesa) is not bool:
        raise ValueError('Invalid experimental package mode')
    sdk = report.get('sdk', 'openorbis')
    _, dist = package_directories(sdk)
    expected = package_identity(mesa, sdk)
    if report.get('package_identity', expected) != expected:
        raise ValueError('Package identity differs from fixed build flavor')
    if report.get('package', dist + '/' + expected['package_name']) != dist + '/' + expected['package_name']:
        raise ValueError('Package path differs from fixed build flavor')
    return expected
