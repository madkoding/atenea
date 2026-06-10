#!/usr/bin/env python3
"""Packaging setup for Atenea."""
from setuptools import setup, find_packages

extras_require = {
    "sglang": ["sglang[all]"],
    "vllm": ["vllm"],
    "diffusers": ["diffusers"],
    "stt": ["faster-whisper"],
    "tts": ["TTS"],
    "ddg": ["duckduckgo-search"],
    "pdf-forms": ["PyMuPDF"],
    "docs": ["markitdown[docx,pptx,xlsx,xls]==0.1.5"],
    "rembg": ["rembg[gpu]"],
    "hf-transfer": ["hf_transfer"],
    "playwright": ["playwright"],
    "onnxruntime-gpu": ["onnxruntime-gpu"],
    "hdbscan": ["hdbscan"],
}
extras_require["all"] = sorted({
    dep for deps in extras_require.values() for dep in deps
})

setup(
    name="atenea",
    version="0.1.0",
    description="Atenea — AI personal assistant",
    license="GNU General Public License v3 or later (GPLv3+)",
    classifiers=[
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
    ],
    packages=find_packages(exclude=["tests", "scripts", "data", "docs"]),
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=[
        "fastapi",
        "uvicorn",
        "python-multipart",
        "python-dotenv",
        "httpx",
        "pydantic>=2.0",
        "pydantic-settings>=2.0",
        "SQLAlchemy",
        "pypdf",
        "beautifulsoup4",
        "charset-normalizer",
        "numpy",
        "chromadb-client",
        "fastembed",
        "youtube-transcript-api",
        "markdown",
        "nh3",
        "icalendar",
        "python-dateutil",
        "caldav",
        "cryptography",
        "bcrypt",
        "mcp",
        "pyotp",
        "qrcode[pil]",
        "croniter",
        "dogpile.cache",
    ],
    extras_require=extras_require,
)
