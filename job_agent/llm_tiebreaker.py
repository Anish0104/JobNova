import json
import os

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = (
    "You choose which link is a company's real job-listings page. "
    "You will receive a JSON array of candidates, each with \"text\" and \"url\". "
    "Reply with ONLY the single best url, verbatim, and nothing else."
)


def pick_careers_link(candidates: list[dict[str, str]]) -> str | None:
    """Ask Groq to pick the most likely job-listings URL from a short shortlist.

    Returns None (never raises) if no API key is configured or the call fails,
    so callers can fall back to their own heuristic.
    """
    if not candidates:
        return None

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(candidates)},
            ],
            temperature=0,
            max_tokens=200,
        )
        answer = (response.choices[0].message.content or "").strip()
    except Exception:
        return None

    urls = {candidate["url"] for candidate in candidates}
    if answer in urls:
        return answer
    for url in urls:
        if url in answer:
            return url
    return None
