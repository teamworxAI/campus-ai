"""Download embedding model weights once into the local models directory.

This is the only step that needs the network. Afterwards the embed service
runs with networking disabled and reads weights from MODELS_DIR.

    docker compose run --rm fetch-models
"""

from __future__ import annotations

from huggingface_hub import snapshot_download

from campus_ai.core.embed import BACKENDS
from campus_ai.core.embed.embedder import model_path

# sentence-transformers reads safetensors; skip duplicate weight formats.
SKIP = ["onnx/*", "openvino/*", "*.onnx", "pytorch_model.bin", "*.h5", "*.msgpack"]


def main() -> None:
    for name, make in BACKENDS.items():
        model_id = make().model_id
        path = model_path(model_id)
        print(f"{name}: {model_id} -> {path}")
        snapshot_download(model_id, local_dir=path, ignore_patterns=SKIP)


if __name__ == "__main__":
    main()
