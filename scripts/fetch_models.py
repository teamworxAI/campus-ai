"""Download embedding and reranker model weights once into the local models directory.

This is the only step that needs the network. Afterwards the embed service
runs with networking disabled and reads weights from MODELS_DIR. Fetches
every embedder backend and the default reranker; pass `--reranker
qwen3-reranker-4b` on the team's inference box for the larger one.

    docker compose run --rm fetch-models
"""

from __future__ import annotations

import argparse

from huggingface_hub import snapshot_download

from campus_ai.core.embed import BACKENDS
from campus_ai.core.embed.embedder import model_path
from campus_ai.core.embed.reranker import DEFAULT_RERANKER, RERANKERS

# sentence-transformers and transformers read safetensors; skip duplicate weight formats.
SKIP = ["onnx/*", "openvino/*", "*.onnx", "pytorch_model.bin", "*.h5", "*.msgpack"]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reranker", action="append", choices=list(RERANKERS), help="reranker(s) to fetch")
    args = parser.parse_args(argv)
    models = {name: make().model_id for name, make in BACKENDS.items()}
    models |= {name: RERANKERS[name] for name in args.reranker or [DEFAULT_RERANKER]}
    for name, model_id in models.items():
        path = model_path(model_id)
        print(f"{name}: {model_id} -> {path}")
        snapshot_download(model_id, local_dir=path, ignore_patterns=SKIP)


if __name__ == "__main__":
    main()
