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

`app_setup.py` / `./atenea setup` ya no instala manejadores de modelos.
Todo se maneja desde el Cookbook → Dependencies tab (Ollama como contenedor Docker,
llama.cpp/vLLM/SGLang como paquetes pip, etc.).

Arranque rapido despues de instalar:

```bash
# Ollama
ollama serve
ollama pull llama3.2:3b

# vLLM (Linux + NVIDIA CUDA)
vllm serve Qwen/Qwen2.5-1.5B-Instruct
```
