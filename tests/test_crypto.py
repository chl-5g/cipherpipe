#!/usr/bin/env python3
"""Crypto unit tests: E2E round-trip, key handling, event sign/verify."""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coincurve
import pytest

from backend.core.crypto import (
    e2e_encrypt, e2e_decrypt, nip44_encrypt, nip44_decrypt,
    sign_event, verify_event, to_nostr_pk, from_nostr_pk, load_or_create_key,
)


def test_encrypt_decrypt_roundtrip():
    alice, bob = coincurve.PrivateKey(), coincurve.PrivateKey()
    bob_pub = bob.public_key.format().hex()
    ct = e2e_encrypt(alice, bob_pub, "hello cipherpipe 你好")
    assert e2e_decrypt(bob, alice.public_key.format().hex(), ct) == "hello cipherpipe 你好"


def test_decrypt_with_wrong_key_fails():
    alice, bob, eve = coincurve.PrivateKey(), coincurve.PrivateKey(), coincurve.PrivateKey()
    ct = e2e_encrypt(alice, bob.public_key.format().hex(), "secret")
    with pytest.raises(Exception):
        e2e_decrypt(eve, alice.public_key.format().hex(), ct)


def test_deprecated_aliases_match():
    assert nip44_encrypt is e2e_encrypt
    assert nip44_decrypt is e2e_decrypt


def test_pubkey_conversion():
    sk = coincurve.PrivateKey()
    full = sk.public_key.format().hex()  # 66-char compressed
    nostr = to_nostr_pk(full)
    assert len(nostr) == 64
    assert from_nostr_pk(nostr) == "02" + nostr
    assert to_nostr_pk(nostr) == nostr  # idempotent


def test_from_nostr_pk_rejects_garbage():
    with pytest.raises(ValueError):
        from_nostr_pk("zz" * 32)
    with pytest.raises(ValueError):
        from_nostr_pk("ab" * 10)


def test_sign_and_verify_event():
    sk = coincurve.PrivateKey()
    ev = sign_event(sk, 4, "content", [["p", "ab" * 32]])
    assert verify_event(ev)
    ev2 = dict(ev, content="tampered")
    assert not verify_event(ev2)


def test_load_or_create_key_persists(tmp_path):
    kf = str(tmp_path / "test.key")
    sk1 = load_or_create_key(kf)
    sk2 = load_or_create_key(kf)
    assert sk1.to_hex() == sk2.to_hex()
