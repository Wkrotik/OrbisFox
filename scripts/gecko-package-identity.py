# SPDX-License-Identifier: MIT
"""Fixed allowlisted package identities; reports cannot select arbitrary paths."""
def package_identity(mesa=False):
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
    expected = package_identity(mesa)
    if report.get('package_identity', expected) != expected:
        raise ValueError('Package identity differs from fixed build flavor')
    if report.get('package', 'dist/gecko/' + expected['package_name']) != 'dist/gecko/' + expected['package_name']:
        raise ValueError('Package path differs from fixed build flavor')
    return expected
