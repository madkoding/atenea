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
```

Auto-detección: `nvidia-smi` → NVIDIA, `/dev/kfd` → AMD, sino CPU.
Para fijar modo: `export GPU_MODE=nvidia` en `.env`.
