# Atenea

See [docs/README.md](docs/README.md) for full documentation.

## Quick Start

```bash
./atenea setup   # first-time setup
./atenea up      # auto-detects GPU, starts with Docker
```

## Commands

| Command | Description |
|---------|-------------|
| `./atenea setup` | First-time setup (venv, .env, deps) |
| `./atenea up` | Start with Docker (auto GPU) |
| `./atenea up --native` | Run directly on host |
| `./atenea up --nvidia` | Force NVIDIA GPU mode |
| `./atenea logs` | Follow container logs |
| `./atenea down` | Stop containers |
| `./atenea help` | Show all commands |
