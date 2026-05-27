"""
src/llm.py
----------
F-06 · Gemini API Integration
F-07 · RAG-Based Schema Injection

Project Insight: Agentic Conversational BI 

Provides two public functions:

    get_llm_response(prompt, system_prompt) -> str
        Thin wrapper around the Gemini API.  Handles HTTP errors, rate limits,
        and empty responses.  Never propagates unhandled exceptions — all error
        paths raise LLMError with an informative message.

    load_schema_dict() -> str
        Reads docs/schema_data_dictionary.md and returns its full text.
        Called by nl2sql.py to inject the schema as the first block of every
        system prompt (F-07 RAG injection).

Design notes
------------
- API key loaded exclusively from .env via python-dotenv (AC1, F-06).
- MODEL constant is the single point of truth for model version (AC3, F-06).
- Schema injection is file-based: updating the .md requires zero code changes
  (AC3, F-07 / ADR-028).
- Token count of the schema is logged once at module import, not per call
  (AC2, F-07).  Token estimate uses a simple whitespace split; Gemini's actual
  tokeniser would give a tighter count but the approximation is conservative
  enough to confirm the schema is safely within the 1M-token context window.

SDK note (ADR-027)
------------------
google-generativeai (0.x) is deprecated as of 2025.  This module uses the
replacement SDK: google-genai (pip install google-genai).  The new SDK
exposes google.genai.Client with a synchronous generate_content() method
on client.models, which is used here.
"""

import os
import logging
import time
import random

from dotenv import load_dotenv

# ── google-genai SDK (replacement for deprecated google-generativeai) ─────────
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError as exc:
    raise ImportError(
        "google-genai package not found. Install with: pip install google-genai"
    ) from exc

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

# Single config constant for model version — never hardcode inline (F-06 AC3).
# ADR-027: gemini-2.5-flash selected (available on Google AI Studio free tier).
# Fallback model is gemini-1.5-flash (documented in ADR-027).
MODEL = "gemini-2.5-flash"  # primary model (already defined)
MODEL_FALLBACK = "gemini-2.5-pro"  # fallback on sustained 503s

_MAX_RETRIES = 5  # attempts per model
_BASE_BACKOFF = 1.0  # seconds — doubles each attempt
_JITTER_FRACTION = 0.3  # ±30 % randomisation
_TRANSIENT_SIGNALS = ("503", "unavailable", "overloaded", "try again")

# Path resolution: this file is src/llm.py — schema dict is ../docs/...
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DICT_PATH = os.path.join(BASE_DIR, "..", "docs", "schema_data_dictionary.md")

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CUSTOM EXCEPTION
# ──────────────────────────────────────────────────────────────────────────────


class LLMError(Exception):
    """
    Raised for all Gemini API failures: HTTP errors, rate limits (429),
    empty or unparseable responses, and missing API key.

    Callers (nl2sql.py, executor.py) catch LLMError explicitly and convert
    it to a structured error dict — no unhandled exceptions propagate (F-06 AC4).
    """


# ──────────────────────────────────────────────────────────────────────────────
# SCHEMA LOADER  (F-07)
# ──────────────────────────────────────────────────────────────────────────────


def load_schema_dict() -> str:
    """
    Read and return the full text of docs/schema_data_dictionary.md.

    The returned string is injected as the first block of every Gemini system
    prompt by generate_sql() in nl2sql.py (F-07 RAG injection).

    Raises
    ------
    FileNotFoundError
        If schema_data_dictionary.md is missing.  Run scripts/preprocess.py
        (which writes the file) or confirm docs/ path is correct.

    Notes
    -----
    - File-based injection: schema updates require only a document edit,
      no code change (F-07 AC3 / ADR-028).
    - Token count logged once here to confirm the schema fits within
      Gemini's context window (F-07 AC2).  Conservative estimate uses
      whitespace-split word count × 1.3 tokens/word.
    """
    abs_path = os.path.abspath(SCHEMA_DICT_PATH)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(
            f"Schema data dictionary not found at: {abs_path}\n"
            "Confirm docs/schema_data_dictionary.md exists."
        )

    with open(abs_path, encoding="utf-8") as fh:
        schema_text = fh.read()

    # Conservative token estimate: word_count × 1.3 (Gemini tokeniser averages
    # ~1.3 tokens/word for technical prose with code snippets).
    word_count = len(schema_text.split())
    token_est = int(word_count * 1.3)
    context_limit = 1_000_000  # Gemini 2.5 Flash context window

    logger.info(
        "Schema dict loaded: %d chars, ~%d words, ~%d estimated tokens "
        "(context limit: %d — %.1f%% used)",
        len(schema_text),
        word_count,
        token_est,
        context_limit,
        token_est / context_limit * 100,
    )

    if token_est > context_limit:
        raise LLMError(
            f"Schema dict estimated token count ({token_est:,}) exceeds "
            f"Gemini context limit ({context_limit:,}). Reduce schema size."
        )

    return schema_text


# ──────────────────────────────────────────────────────────────────────────────
# GEMINI CLIENT  (F-06)
# ──────────────────────────────────────────────────────────────────────────────


def _call_model(client, model: str, prompt: str, system_prompt: str):
    """Single blocking call to one model. Returns raw response."""
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
        ),
    )


def _is_transient(msg: str) -> bool:
    return any(s in msg.lower() for s in _TRANSIENT_SIGNALS)


def _is_rate_limit(msg: str) -> bool:
    msg_l = msg.lower()
    return "429" in msg or "rate limit" in msg_l or "quota" in msg_l


def _get_client() -> genai.Client:
    """
    Instantiate and return a Gemini client using the API key from .env.

    Called lazily inside get_llm_response() so that importing this module
    does not require a .env file at import time — tests can monkey-patch
    before the first call.

    Raises
    ------
    LLMError
        If GEMINI_API_KEY is absent from environment after loading .env.
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise LLMError(
            "GEMINI_API_KEY not found in environment. "
            "Add it to your .env file: GEMINI_API_KEY=<your_key>"
        )
    return genai.Client(api_key=api_key)


def _parse_response_text(response) -> str:
    """
    Extract plain text from a Gemini API response object.

    Handles both the simple .text shortcut and the content-block structure
    returned by some model configurations (F-06 AC2).

    Parameters
    ----------
    response : google.genai GenerateContentResponse

    Returns
    -------
    str
        Parsed text.  Never returns an empty string — raises LLMError instead.

    Raises
    ------
    LLMError
        If no text can be extracted from the response.
    """
    # Simple path: response.text is populated directly.
    try:
        text = response.text
        if text and text.strip():
            return text.strip()
    except (AttributeError, ValueError):
        pass

    # Content-block path: iterate candidates → content → parts.
    try:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text and part.text.strip():
                    return part.text.strip()
    except (AttributeError, TypeError):
        pass

    raise LLMError(
        f"Gemini returned an empty or unparseable response. Raw response: {response!r}"
    )


def get_llm_response(prompt: str, system_prompt: str) -> str:
    """
    Send a prompt to Gemini and return the parsed text response.

    Retry strategy
    ─────────────
    Primary model (gemini-2.5-flash): up to _MAX_RETRIES attempts.
    Each transient-503 retry sleeps:
        delay = base * 2^(attempt-1)  ×  uniform(1 - jitter, 1 + jitter)
        e.g. attempt 1 → ~1 s, 2 → ~2 s, 3 → ~4 s, 4 → ~8 s  (±30 %)
    If the primary model exhausts all retries on transient errors, one
    attempt is made on MODEL_FALLBACK before raising LLMError.

    Rate-limit (429) and non-transient errors fail immediately on both
    models — retrying won't help.

    Returns
    ───────
    str  — clean parsed text from the model.

    Raises
    ──────
    LLMError — on rate limit, exhausted retries, empty response, or any
               non-transient API failure.
    """
    client = _get_client()

    def _attempt_with_retries(model: str) -> str:
        """Try one model up to _MAX_RETRIES times. Returns text or raises."""
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = _call_model(client, model, prompt, system_prompt)

                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    cached = getattr(
                        response.usage_metadata, "cached_content_token_count", 0
                    )
                    if cached:
                        logger.info(
                            "Cache hit: %d tokens served from implicit cache", cached
                        )

                return _parse_response_text(response)

            except Exception as exc:
                msg = str(exc)
                last_exc = exc

                # Rate limit — never retry
                if _is_rate_limit(msg):
                    raise LLMError(
                        f"Gemini rate limit exceeded (429). "
                        f"Wait before retrying. Original error: {msg}"
                    ) from exc

                # Transient 503 — retry with exponential backoff + jitter
                if _is_transient(msg) and attempt < _MAX_RETRIES:
                    base_delay = _BASE_BACKOFF * (2 ** (attempt - 1))
                    jitter = base_delay * _JITTER_FRACTION
                    delay = base_delay + random.uniform(-jitter, jitter)
                    delay = max(0.5, delay)  # floor at 0.5 s
                    logger.warning(
                        "get_llm_response | transient 503 on %s attempt %d/%d "
                        "— retrying in %.1fs",
                        model,
                        attempt,
                        _MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                # Non-transient error — fail immediately
                raise LLMError(f"Gemini API call failed: {msg}") from exc

        # Exhausted all retries on transient errors
        raise LLMError(
            f"{model} unavailable after {_MAX_RETRIES} attempts. Last error: {last_exc}"
        ) from last_exc

    # ── Primary model ─────────────────────────────────────────────────────────
    try:
        return _attempt_with_retries(MODEL)

    except LLMError as primary_err:
        msg = str(primary_err)

        # Only attempt fallback on sustained transient failures, not rate limits
        if not _is_transient(msg.lower()) and "unavailable after" not in msg:
            raise

        logger.warning(
            "get_llm_response | %s exhausted — falling back to %s",
            MODEL,
            MODEL_FALLBACK,
        )

        try:
            result = _attempt_with_retries(MODEL_FALLBACK)
            logger.info("get_llm_response | fallback to %s succeeded", MODEL_FALLBACK)
            return result

        except LLMError as fallback_err:
            # Both models failed — raise with combined context
            raise LLMError(
                f"Both {MODEL} and {MODEL_FALLBACK} unavailable. "
                f"Primary: {primary_err}. Fallback: {fallback_err}"
            ) from fallback_err
