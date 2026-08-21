from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


COOKIE_NAME = "tradefot_session"
TOKEN_BYTES = 48
bearer_scheme = HTTPBearer(auto_error=False)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def configured_digest() -> str | None:
    configured_hash = os.getenv("TRADEFOT_ACCESS_TOKEN_HASH", "").strip().casefold()
    if configured_hash:
        if not re.fullmatch(r"[0-9a-f]{64}", configured_hash):
            raise RuntimeError("TRADEFOT_ACCESS_TOKEN_HASH precisa ser um SHA-256 válido")
        return configured_hash
    raw_token = (
        os.getenv("TRADEFOT_ACCESS_TOKEN", "").strip()
        or os.getenv("TRADEFOT_ADMIN_TOKEN", "").strip()
    )
    return token_digest(raw_token) if raw_token else None


def authentication_configured() -> bool:
    try:
        return configured_digest() is not None
    except RuntimeError:
        return False


def verify_token(token: str | None) -> bool:
    expected = configured_digest()
    if expected is None or not token:
        return False
    return hmac.compare_digest(token_digest(token.strip()), expected)


def presented_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    x_access_token: str | None,
    x_admin_token: str | None,
) -> str | None:
    if credentials and credentials.scheme.casefold() == "bearer":
        return credentials.credentials
    return (
        x_access_token
        or x_admin_token
        or request.cookies.get(COOKIE_NAME)
    )


def require_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_access_token: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    try:
        expected = configured_digest()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Autenticação não configurada. Defina TRADEFOT_ACCESS_TOKEN_HASH "
                "ou TRADEFOT_ACCESS_TOKEN no ambiente."
            ),
        )
    token = presented_token(request, credentials, x_access_token, x_admin_token)
    if not verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso ausente ou inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )


def cookie_secure() -> bool:
    return os.getenv("TRADEFOT_COOKIE_SECURE", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "sim",
    }


def generate_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    return token, token_digest(token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera um token de acesso do TradeFot")
    parser.add_argument("generate", nargs="?", default="generate")
    args = parser.parse_args()
    if args.generate != "generate":
        parser.error("Comando disponível: generate")
    token, digest = generate_token()
    print("TOKEN (guarde em um gerenciador de senhas):")
    print(token)
    print("\nAdicione esta linha ao .env da VPS:")
    print(f"TRADEFOT_ACCESS_TOKEN_HASH={digest}")
    print("\nO token não pode ser recuperado a partir do hash. Guarde-o antes de fechar.")


if __name__ == "__main__":
    main()
