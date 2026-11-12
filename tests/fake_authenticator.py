"""A software FIDO2 authenticator for tests: answers make_credential / get_assertion like Windows would (test_v120)."""
import os, hashlib, struct
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from fido2.cose import ES256
from fido2.webauthn import (AttestedCredentialData, AuthenticatorData, AttestationObject, CollectedClientData,
    RegistrationResponse, AuthenticatorAttestationResponse, AuthenticationResponse, AuthenticatorAssertionResponse,
    PublicKeyCredentialCreationOptions, PublicKeyCredentialRequestOptions, Aaguid)

class FakeKey:
    def __init__(self, origin, rp_id, verified=True):
        self.origin, self.rp_id, self.verified = origin, rp_id, verified
        self.priv = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.counter = 0

    def _flags(self):
        f = AuthenticatorData.FLAG.UP
        if self.verified:
            f |= AuthenticatorData.FLAG.UV
        return f

    def make_credential(self, options):
        o = PublicKeyCredentialCreationOptions.from_dict(options)
        cd = CollectedClientData.create(type=CollectedClientData.TYPE.CREATE, challenge=o.challenge, origin=self.origin)
        acd = AttestedCredentialData.create(Aaguid.NONE, self.cred_id, ES256.from_cryptography_key(self.priv.public_key()))
        ad = AuthenticatorData.create(hashlib.sha256(self.rp_id.encode()).digest(), self._flags() | AuthenticatorData.FLAG.AT, 0, acd)
        att = AttestationObject.create("none", ad, {})
        return RegistrationResponse(raw_id=self.cred_id, response=AuthenticatorAttestationResponse(client_data=cd, attestation_object=att))

    def get_assertion(self, options):
        o = PublicKeyCredentialRequestOptions.from_dict(options)
        cd = CollectedClientData.create(type=CollectedClientData.TYPE.GET, challenge=o.challenge, origin=self.origin)
        self.counter += 1
        ad = AuthenticatorData.create(hashlib.sha256(self.rp_id.encode()).digest(), self._flags(), self.counter)
        sig = self.priv.sign(bytes(ad) + cd.hash, ec.ECDSA(hashes.SHA256()))
        resp = AuthenticationResponse(raw_id=self.cred_id, response=AuthenticatorAssertionResponse(client_data=cd, authenticator_data=ad, signature=sig))
        class Sel:
            def get_response(self, i): return resp
        return Sel()
