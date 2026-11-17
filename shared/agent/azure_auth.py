from __future__ import annotations

import os

from agent.harness.common import HarnessError


def foundry_enabled() -> bool:
    return os.getenv("AI_PROVIDER", "").strip().lower() == "azure-foundry"


def foundry_settings() -> tuple[str, str]:
    endpoint = os.getenv("AZURE_AI_FOUNDRY_ENDPOINT", "").strip().rstrip("/")
    scope = os.getenv("AZURE_AI_FOUNDRY_TOKEN_SCOPE", "https://ai.azure.com/.default").strip()
    if not endpoint:
        raise HarnessError("Azure Foundry requires AZURE_AI_FOUNDRY_ENDPOINT")
    if not os.getenv("AZURE_TENANT_ID") or not os.getenv("AZURE_CLIENT_ID") or not os.getenv("AZURE_CLIENT_SECRET"):
        raise HarnessError("Azure Foundry service principal requires AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET")
    return endpoint, scope


def foundry_access_token() -> str:
    _, scope = foundry_settings()
    try:
        from azure.identity import ClientSecretCredential

        with ClientSecretCredential(
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
        ) as credential:
            return credential.get_token(scope).token
    except Exception as exc:
        raise HarnessError(f"Could not get Azure Foundry access token ({type(exc).__name__})") from exc


def gateway_enabled() -> bool:
    """True when an OpenAI-compatible Azure gateway (e.g. APIM) with Entra auth is configured."""
    return bool(os.getenv("AZURE_BASE_URL", "").strip()) and os.getenv("AZURE_AUTH", "").strip().lower() == "entra"


def gateway_base_url() -> str:
    return os.environ["AZURE_BASE_URL"].strip().rstrip("/")


def gateway_access_token() -> str:
    scope = os.getenv("AZURE_ENTRA_SCOPE", "").strip()
    missing = [
        name
        for name in ("AZURE_ENTRA_SCOPE", "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise HarnessError(f"Azure gateway auth requires {', '.join(missing)}")
    try:
        from azure.identity import ClientSecretCredential

        with ClientSecretCredential(
            tenant_id=os.environ["AZURE_TENANT_ID"],
            client_id=os.environ["AZURE_CLIENT_ID"],
            client_secret=os.environ["AZURE_CLIENT_SECRET"],
        ) as credential:
            return credential.get_token(scope).token
    except Exception as exc:
        raise HarnessError(f"Could not get Azure gateway access token ({type(exc).__name__})") from exc
