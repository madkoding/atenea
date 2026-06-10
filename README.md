# Atenea

See [docs/README.md](docs/README.md) for full documentation.

## Uso del script `./atenea`

El script unificado maneja setup y lanzamiento con detección automática de GPU.

```bash
./atenea setup                  # primer setup: crea .env, venv, instala deps
./atenea up                     # inicia con Docker (auto-detecta GPU)
./atenea up --native            # ejecuta directo en el host (sin Docker)
./atenea up --nvidia            # forza modo NVIDIA
./atenea up --amd               # forza modo AMD ROCm
./atenea up --cpu               # forza modo CPU
./atenea up --build             # rebuild imagen antes de iniciar
./atenea logs                   # sigue los logs del contenedor
./atenea down                   # detiene contenedores
./atenea shell                  # shell dentro del contenedor
./atenea exec <comando>         # ejecuta comando en el contenedor
./atenea ps                     # lista contenedores
./atenea help                   # muestra todos los comandos

# verificacion rapida del setup/contenedor GPU
scripts/verify-gpu-setup.sh         # auto
scripts/verify-gpu-setup.sh --nvidia
scripts/verify-gpu-setup.sh --amd
scripts/verify-gpu-setup.sh --cpu
```

Auto-detección: `nvidia-smi` → NVIDIA, `/dev/kfd` → AMD, sino CPU.
Para fijar modo: `export GPU_MODE=nvidia` en `.env`.

## Backend local de inferencia

`app_setup.py` y `./atenea setup` ya no fuerzan `llama.cpp`.

- Primero detectan si ya hay un backend local funcionando (OpenAI-compatible u Ollama).
- Si no detectan uno, ofrecen elegir entre: `ollama`, `llama.cpp`, `vllm`, `hf-local` o `skip`.
- En modo no interactivo puedes controlar el comportamiento por variables de entorno.

```bash
# omitir configuracion de backend local durante setup
ATENEA_INFERENCE_SETUP=skip .venv/bin/python app_setup.py

# forzar eleccion en modo no interactivo
ATENEA_INFERENCE_SETUP=auto ATENEA_INFERENCE_BACKEND=ollama .venv/bin/python app_setup.py
ATENEA_INFERENCE_SETUP=auto ATENEA_INFERENCE_BACKEND=llamacpp .venv/bin/python app_setup.py
ATENEA_INFERENCE_SETUP=auto ATENEA_INFERENCE_BACKEND=vllm .venv/bin/python app_setup.py
ATENEA_INFERENCE_SETUP=auto ATENEA_INFERENCE_BACKEND=hf-local .venv/bin/python app_setup.py
```

For `hf-local`, setup also tries to start a lightweight local OpenAI-compatible
endpoint on `http://127.0.0.1:8010/v1` using `scripts/hf_local_openai_server.py`.
Override with:

```bash
ATENEA_HF_LOCAL_MODEL=sshleifer/tiny-gpt2
ATENEA_HF_LOCAL_HOST=127.0.0.1
ATENEA_HF_LOCAL_PORT=8010
```

Arranque rapido despues de instalar:

```bash
# Ollama
ollama serve
ollama pull llama3.2:3b

# vLLM (Linux + NVIDIA CUDA)
vllm serve Qwen/Qwen2.5-1.5B-Instruct
```
