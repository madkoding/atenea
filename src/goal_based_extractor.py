# src/goal_based_extractor.py
"""
Goal-based content extraction prompt inspired by Alibaba Tongyi DeepResearch.
"""

EXTRACTOR_SYSTEM = """Extract relevant information from a webpage for a given research goal.

Goal: {goal}

Task guidelines:
1. Locate the specific sections directly related to the goal within the provided webpage content.
2. Identify and extract the most relevant information; output full original context where possible, up to three or more paragraphs.
3. Organize into a concise paragraph with logical flow, judging each piece of information's contribution to the goal.

Respond in JSON with exactly these fields: "rational", "evidence", "summary".

Example:
{{
    "rational": "This section discusses X which directly relates to the goal of understanding Y",
    "evidence": "Full quotes and context from the page...",
    "summary": "Concise summary of how this information answers the goal"
}}
"""


# --- Spanish fork helper (Fase 4) -----------------------------------------
# Same JSON-key constraint as deep_research: keys stay in English, prose
# values are localized. The consumer (deep_research.py) wraps the prompt via
# _localize() before sending; this module-level helper is provided for any
# direct caller that wants the same behavior without depending on deep_research.

_ES_EXTRACTOR_DIRECTIVE = (
    "Idioma de respuesta: el usuario ha elegido espa\xf1ol como idioma de la "
    "interfaz. Escribe los valores de los campos \"rational\" y \"summary\" "
    "en espa\xf1ol neutro (tuteo, sin voseo ni regionalismos). IMPORTANTE: "
    "mant\xe9n en ingl\xe9s las claves JSON (\"rational\", \"evidence\", "
    "\"summary\") exactamente como se muestra, para que el c\xf3digo del "
    "backend pueda parsearlos.\n\n"
)


def _localize(prompt: str, ui_language) -> str:
    """Prepend a Spanish directive when ui_language=='es'."""
    if not ui_language or not isinstance(ui_language, str):
        return prompt
    if ui_language.strip().lower() != "es":
        return prompt
    return _ES_EXTRACTOR_DIRECTIVE + prompt

