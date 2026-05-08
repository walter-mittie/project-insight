"""
src/llm.py
----------
F-06 · Gemini API Integration
F-07 · RAG-Based Schema Injection

AM1: Agentic Conversational BI — Manu Mohandas / TCS

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
MODEL = "gemini-2.5-flash"

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

    Parameters
    ----------
    prompt : str
        The user-turn content (natural language question).
    system_prompt : str
        The system instruction block.  For NL2SQL calls this will already
        contain the schema dict prepended by generate_sql() (F-07).

    Returns
    -------
    str
        Clean parsed text from the model.

    Raises
    ------
    LLMError
        On HTTP errors, rate limit (429), empty responses, missing API key,
        or any other API-level failure.  No unhandled exceptions propagate
        to the caller (F-06 AC4).
    """
    client = _get_client()

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
        )
    except Exception as exc:
        # Map all SDK-level exceptions to LLMError.
        # Check for rate limit signal in the exception message.
        msg = str(exc)
        if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower():
            raise LLMError(
                f"Gemini rate limit exceeded (429). "
                f"Wait before retrying. Original error: {msg}"
            ) from exc
        raise LLMError(f"Gemini API call failed: {msg}") from exc

    return _parse_response_text(response)
