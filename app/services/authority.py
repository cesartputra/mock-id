"""Requester authority is distinct from a face match or a self-declaration."""

import os


class RequesterAuthorityAdapter:
    def check(self, owner_id, identity, attested):
        raise NotImplementedError


class AuthorityService(RequesterAuthorityAdapter):
    def check(self, owner_id, identity, attested):
        if os.getenv("MOCK_ID_MODE", "demo") == "demo":
            return {
                "verified": bool(attested),
                "scope": "synthetic_only",
                "basis": "Authenticated account requests own demo information; self-declaration and local capture only.",
            }
        return {
            "verified": False,
            "scope": "production",
            "basis": "Approved requester-to-subject binding from the host application is required; no production authority adapter configured.",
        }
