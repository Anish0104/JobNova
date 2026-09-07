import json
import os
import sys

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = (
    "You choose which link is a company's real job-listings page. "
    "You will receive a JSON array of candidates, each with \"text\" and \"url\". "
    "Reply with ONLY the single best url, verbatim, and nothing else."
)


def pick_careers_link(candidates: list[dict[str, str]]) -> str | None:
    """Ask Groq to pick the most likely job-listings URL from a short shortlist.

    Returns None (never raises) if no API key is configured or the call fails,
    so callers can fall back to their own heuristic — but every such case is
    also printed to stderr, so a silent fallback doesn't look identical to
    "the tiebreaker wasn't needed" in harness/log output.
    """
    if not candidates:
        return None

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("[llm_tiebreaker] GROQ_API_KEY not set — skipping, falling back to heuristic", file=sys.stderr)
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
    except Exception as error:
        print(f"[llm_tiebreaker] Groq call failed ({error!r}) — falling back to heuristic", file=sys.stderr)
        return None

    urls = {candidate["url"] for candidate in candidates}
    if answer in urls:
        return answer
    for url in urls:
        if url in answer:
            return url

    print(f"[llm_tiebreaker] Groq answer {answer!r} matched none of the candidate URLs — falling back to heuristic", file=sys.stderr)
    return None
