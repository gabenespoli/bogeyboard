import getpass
import sys
from pathlib import Path

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

TOKEN_STORE = Path("~/.garminconnect").expanduser()


def _prompt_mfa() -> str:
    return input("Enter MFA code: ").strip()


def get_client(token_store: Path = TOKEN_STORE) -> Garmin:
    """Return a logged-in Garmin client, using cached tokens when possible."""
    if token_store.exists():
        try:
            client = Garmin()
            client.login(tokenstore=str(token_store))
            return client
        except (GarminConnectAuthenticationError, FileNotFoundError) as e:
            print(f"Cached tokens invalid ({e.__class__.__name__}), logging in fresh...")
        except GarminConnectConnectionError as e:
            sys.exit(f"Connection error while using cached tokens: {e}")

    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    try:
        client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
        client.login(tokenstore=str(token_store))
    except GarminConnectAuthenticationError as e:
        sys.exit(f"Authentication failed: {e}")
    except GarminConnectConnectionError as e:
        sys.exit(f"Connection error: {e}")

    print(f"Login OK — tokens cached at {token_store} (valid ~1 year)")
    return client
