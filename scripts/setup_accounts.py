"""Run interactively in the workspace terminal. Never enter secrets in chat."""

import argparse
import configparser
import getpass
import os
import sys
from pathlib import Path


def secure_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.exists():
        raise ValueError(
            "A credential file already exists; use the service's own settings to update it"
        )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("account", choices=["kaggle", "huggingface", "aws"])
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise ValueError("Use an interactive terminal so secret input is hidden")
    if args.account == "kaggle":
        token = getpass.getpass("Kaggle API token (hidden): ").strip()
        if not token:
            raise ValueError("Token is empty")
        secure_write(Path.home() / ".kaggle/access_token", token + "\n")
        print("Kaggle token saved outside the project with private permissions.")
    elif args.account == "huggingface":
        from huggingface_hub import HfApi, HfFolder

        token = getpass.getpass("Hugging Face write token (hidden): ").strip()
        identity = HfApi(token=token).whoami()
        if identity["name"].casefold() != "ineeoluwa":
            raise ValueError("The token does not belong to the intended Ineeoluwa account")
        HfFolder.save_token(token)
        print("Hugging Face connected as Ineeoluwa; token stored outside the project.")
    else:
        # Dedicated named profile; other profiles are not modified.
        key_id = getpass.getpass("AWS access key ID (hidden): ").strip()
        secret = getpass.getpass("AWS secret access key (hidden): ").strip()
        session = getpass.getpass(
            "AWS session token, if using temporary credentials (hidden; otherwise Enter): "
        ).strip()
        if not key_id or not secret:
            raise ValueError("Both AWS access fields are required")
        config = configparser.ConfigParser()
        path = Path.home() / ".aws/credentials"
        if path.exists():
            config.read(path)
        if config.has_section("afri-research"):
            raise ValueError("Dedicated afri-research profile already exists; no changes made")
        config["afri-research"] = {
            "aws_access_key_id": key_id,
            "aws_secret_access_key": secret,
        }
        if session:
            config["afri-research"]["aws_session_token"] = session
        import io

        text = io.StringIO()
        config.write(text)
        if path.exists():
            # Preserve existing profiles in a private atomic replacement outside the repo.
            temporary = path.with_name("credentials.afri-research.tmp")
            secure_write(temporary, text.getvalue())
            temporary.replace(path)
        else:
            secure_write(path, text.getvalue())
        print("AWS afri-research profile saved outside the project.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # SDK exceptions can contain URLs or account-sensitive request details.
        print(
            "Connection did not finish: " + type(error).__name__ + ". No secret is displayed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
