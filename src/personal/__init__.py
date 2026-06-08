"""Personal documents (RAG-backed local folder ingestion)."""
from src.personal.docs import *  # noqa: F401,F403
from src.personal.docs import (  # noqa: F401
    PersonalDocsConfig,
    PersonalDocsManager,
    extract_pdf_text,
    extract_office_text,
    read_text_file,
    split_chunks,
    tokenize,
    load_personal_index,
    retrieve_personal_keyword,
    retrieve_personal,
)
