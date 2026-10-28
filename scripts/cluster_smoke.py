"""Record rollout readiness separately from measured load and scored answers."""

import json
import os
import time
from datetime import datetime, timezone

import httpx


def smoke(
    base, context, api_key, audio, journal, stage, *, max_wait=90, interval=5, transport=None
):
    started = time.monotonic()
    transient = {404, 429, 502, 503, 504}
    attempt = 0
    while True:
        attempt += 1
        observation = {
            "stage": stage,
            "attempt": attempt,
            "at": datetime.now(timezone.utc).isoformat(),
            "checks": {},
            "statuses": {},
        }
        fatal = False
        try:
            remaining = max_wait - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("Rollout readiness deadline reached")
            with httpx.Client(
                verify=context, timeout=min(20, remaining), trust_env=False, transport=transport
            ) as client:

                def post(path, **kwargs):
                    remaining = max_wait - (time.monotonic() - started)
                    if remaining <= 0:
                        raise TimeoutError("Rollout readiness deadline reached")
                    return client.post(base + path, timeout=min(20, remaining), **kwargs)

                payload = {"messages": [{"role": "user", "content": "Say hello."}], "max_tokens": 8}
                unauthorized = post("/v1/chat/completions", json=payload)
                observation["statuses"]["unauthorized"] = unauthorized.status_code
                observation["checks"]["unauthorized_401"] = unauthorized.status_code == 401
                # A serving 200 without authentication is a real failure, not a
                # rollout condition that may be hidden by a later successful try.
                if unauthorized.status_code not in {401, 404, 502, 503, 504}:
                    fatal = True
                elif unauthorized.status_code == 401:
                    headers = {"Authorization": "Bearer " + api_key}
                    chat = post("/v1/chat/completions", headers=headers, json=payload)
                    observation["statuses"]["chat"] = chat.status_code
                    observation["checks"]["chat_200"] = chat.status_code == 200 and bool(
                        chat.json().get("choices")
                    )
                    speech = post(
                        "/transcribe",
                        headers={**headers, "Content-Type": "audio/wav"},
                        content=audio,
                    )
                    observation["statuses"]["speech"] = speech.status_code
                    observation["checks"]["transcription_200"] = (
                        speech.status_code == 200 and isinstance(speech.json().get("text"), str)
                    )
                    fatal = any(
                        code != 200 and code not in transient
                        for code in (chat.status_code, speech.status_code)
                    )
                    fatal = fatal or any(
                        observation["statuses"].get(name) == 200
                        and not observation["checks"].get(check)
                        for name, check in [("chat", "chat_200"), ("speech", "transcription_200")]
                    )
        except httpx.TransportError as error:
            observation["transport_error_type"] = type(error).__name__
        except (ValueError, TimeoutError) as error:
            observation["contract_error_type"] = type(error).__name__
            fatal = True
        observation["elapsed_seconds"] = time.monotonic() - started
        # No response bodies, authorization headers or credentials enter this journal.
        with journal.open("a") as stream:
            stream.write(json.dumps(observation) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if len(observation["checks"]) == 3 and all(observation["checks"].values()):
            return observation["checks"]
        if fatal:
            raise RuntimeError(
                "Serving contract/authentication probe failed; inspect saved status journal"
            )
        if time.monotonic() - started + interval >= max_wait:
            raise TimeoutError(
                "Serving did not recover within the bounded rollout readiness window"
            )
        time.sleep(interval)
