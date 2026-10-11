class DukcapilService:
    """The only intentionally simulated adapter. Never asserts real matching."""
    def check(self, identity):
        return {'mode': 'mock', 'status': 'not_verified', 'identity_verified': False,
                'message': 'API Dukcapil tidak dipanggil. Identitas belum dikonfirmasi oleh sumber resmi.'}
