"""Password hashing for admin users.

Argon2id, at the OWASP-recommended minimum rather than the library defaults.

The defaults ask for 64 MiB per hash. On a 512 MiB Cloud Run instance a burst
of concurrent logins would then compete for memory with the application
itself, which turns a login page into a way to degrade the whole service. The
OWASP minimum — 19 MiB, two iterations, one lane — measures around 35ms here:
slow enough that a stolen hash is expensive to attack, fast enough that the
endpoint is not itself a denial-of-service amplifier.

That second property only holds because the login route is rate-limited
*before* it hashes. An unauthenticated endpoint that does deliberately
expensive work is otherwise a gift; see api.login.
"""

from __future__ import annotations

import contextlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP Password Storage Cheat Sheet, Argon2id: minimum 19 MiB of memory,
# an iteration count of 2, and 1 degree of parallelism.
_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)

# The cost of a wrong password must not be distinguishable from the cost of an
# unknown email. Verifying against this constant when no user is found keeps
# the two paths on the same order of magnitude, so response time stops being
# an oracle for "does this address have an account here". Its plaintext is
# irrelevant and deliberately unguessable.
_DUMMY_HASH = _hasher.hash("not-a-real-password-3f2a9c1b7e")

MIN_LENGTH = 12
"""Length is the only rule.

Composition requirements — an uppercase, a digit, a symbol — measurably push
people toward `Bank@2026!` and a sticky note. Length is what actually costs an
attacker, and NIST SP 800-63B has recommended dropping composition rules since
2017.
"""


def hash_password(plaintext: str) -> str:
    return _hasher.hash(plaintext)


def verify_password(stored_hash: str | None, plaintext: str) -> bool:
    """True if the password matches. Never raises.

    A missing hash still performs a verification against the dummy, so a user
    who exists but has no password credential — invited and not yet activated,
    or SSO-only later — costs the same as one who does.
    """
    if stored_hash is None:
        _burn(plaintext)
        return False
    try:
        return _hasher.verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _burn(plaintext: str) -> None:
    """Spend the same work as a real verification, and discard it."""
    with contextlib.suppress(
        VerifyMismatchError, VerificationError, InvalidHashError
    ):
        _hasher.verify(_DUMMY_HASH, plaintext)


def needs_rehash(stored_hash: str) -> bool:
    """True when a hash was made with weaker parameters than we now use.

    Raising the cost later is only meaningful if existing hashes are upgraded,
    and the only moment the plaintext is available to do that is a successful
    login. Without this, a parameter increase protects new accounts and leaves
    every existing one at the old strength indefinitely.
    """
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
