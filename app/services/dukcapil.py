"""Identity validation adapter contract. No official endpoint is invoked here."""
import os

class IdentityValidationAdapter:
    def check(self,identity):raise NotImplementedError

class MockIdentityAdapter(IdentityValidationAdapter):
    def check(self,identity):
        return {'mode':'mock','status':'passed','identity_demo_passed':True,
            'identity_verified':False,'source_available':True,'simulated':True,
            'source':'demo_local_only','message':'Dukcapil dianggap lolos untuk simulasi demo. API resmi tidak dipanggil.'}

class OfficialIdentityAdapter(IdentityValidationAdapter):
    def check(self,identity):
        return {'mode':'unavailable','status':'pending','identity_verified':False,'source_available':False,
            'source':'official_adapter_required','message':'Kontrak/adapter validasi identitas berwenang belum tersedia. Persetujuan dan penerbitan produksi ditahan.'}

class DukcapilService:
    def __init__(self,adapter=None):
        self.adapter=adapter or (MockIdentityAdapter() if os.getenv('MOCK_ID_MODE','demo')=='demo' else OfficialIdentityAdapter())
    def check(self,identity):return self.adapter.check(identity)
