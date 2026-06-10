#!/usr/bin/env python3
"""Minimal local OpenAI-compatible server backed by Transformers.

Intended as a lightweight local fallback for Atenea setup.
"""

from __future__ import annotations

import argparse
from typing import Any

import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    max_tokens: int | None = 256
    temperature: float | None = 0.7
    stream: bool | None = False


def _pick_device(requested: str) -> str:
    if requested in ("cpu", "cuda"):
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


def _messages_to_prompt(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.role.strip().lower()
        content = msg.content.strip()
        if not content:
            continue
        parts.append(f"{role}: {content}")
    parts.append("assistant:")
    return "\n".join(parts)


def create_app(model_id: str, device: str) -> FastAPI:
    app = FastAPI(title="Atenea HF Local OpenAI API", version="0.1")

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(model_id)
    model.to(device)
    model.eval()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "backend": "hf-local", "model": model_id}

    @app.get("/v1/models")
    def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "owned_by": "local",
                }
            ],
        }

    @app.post("/v1/chat/completions")
    def chat_completions(payload: ChatCompletionRequest) -> dict[str, Any]:
        prompt = _messages_to_prompt(payload.messages)
        max_new_tokens = int(payload.max_tokens or 256)
        temperature = float(payload.temperature or 0.7)

        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        do_sample = temperature > 0

        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=max(0.0, temperature),
                do_sample=do_sample,
                pad_token_id=tokenizer.eos_token_id,
            )

        generated = output[0][inputs["input_ids"].shape[1] :]
        text = tokenizer.decode(generated, skip_special_tokens=True).strip()

        model_name = payload.model or model_id
        return {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local Transformers OpenAI-compatible server")
    parser.add_argument("--model", default="sshleifer/tiny-gpt2")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    args = parser.parse_args()

    device = _pick_device(args.device)
    app = create_app(args.model, device)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
