"""One-time setup: claim SimpleFIN access token from a setup token.

Usage:
    python scripts/setup_simplefin.py

You'll be prompted to paste your Setup Token from https://beta-bridge.simplefin.org.
The script will claim it and output the credentials to add to .env.
"""

import base64
import sys
from pathlib import Path

import requests


def main():
    print("SimpleFIN Setup")
    print("=" * 40)
    print()
    print("1. Go to https://beta-bridge.simplefin.org")
    print("2. Sign up and link your bank accounts")
    print("3. Under 'Apps' → 'New Connection', create a Setup Token")
    print()

    setup_token = input("Paste your Setup Token here: ").strip()
    if not setup_token:
        print("No token provided. Exiting.")
        sys.exit(1)

    # Step 1: Base64-decode the setup token to get the claim URL
    try:
        claim_url = base64.b64decode(setup_token).decode("utf-8")
    except Exception as e:
        print(f"Error decoding token: {e}")
        print("Make sure you copied the full Setup Token.")
        sys.exit(1)

    print(f"\nClaim URL: {claim_url}")
    print("Claiming access token...")

    # Step 2: POST to the claim URL to get the Access URL
    try:
        response = requests.post(claim_url, timeout=30)
        response.raise_for_status()
        access_url = response.text.strip()
    except requests.RequestException as e:
        print(f"Error claiming token: {e}")
        print("The setup token may have already been claimed (they're single-use).")
        sys.exit(1)

    # Step 3: Parse the Access URL to extract credentials
    # Format: https://<username>:<password>@beta-bridge.simplefin.org/simplefin
    try:
        from urllib.parse import urlparse

        parsed = urlparse(access_url)
        username = parsed.username
        password = parsed.password
        base_url = f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
    except Exception as e:
        print(f"Error parsing access URL: {e}")
        print(f"Raw access URL: {access_url}")
        sys.exit(1)

    print("\nSuccess! Add these to your .env file:\n")
    print(f"SIMPLEFIN_USERNAME={username}")
    print(f"SIMPLEFIN_PASSWORD={password}")
    print(f"SIMPLEFIN_BASE_URL={base_url}")

    # Offer to write to .env
    env_path = Path(__file__).parent.parent / ".env"
    write = input(f"\nWrite to {env_path}? (y/n): ").strip().lower()
    if write == "y":
        lines = [
            f"SIMPLEFIN_USERNAME={username}\n",
            f"SIMPLEFIN_PASSWORD={password}\n",
            f"SIMPLEFIN_BASE_URL={base_url}\n",
        ]
        with open(env_path, "a") as f:
            f.write("\n# SimpleFIN credentials (auto-generated)\n")
            f.writelines(lines)
        print(f"Credentials written to {env_path}")
    else:
        print("Skipped writing .env. Copy the values above manually.")


if __name__ == "__main__":
    main()
