import importlib.util
import math
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from campus_ai.core.embed import BACKENDS, get_embedder, media, truncate

ROOT = Path(__file__).resolve().parents[1]


def load_bakeoff():
    spec = importlib.util.spec_from_file_location("embed_bakeoff", ROOT / "scripts" / "embed_bakeoff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_model(dim):
    model = mock.Mock()
    model.encode.side_effect = lambda inputs, **kwargs: np.arange(len(inputs) * dim, dtype=np.float32).reshape(
        len(inputs), dim
    ) + 1
    return model


class TruncateTests(unittest.TestCase):
    def test_keeps_prefix_and_renormalizes(self):
        vectors = np.array([[3.0, 4.0, 12.0], [0.0, 0.0, 1.0]])
        out = truncate(vectors, 2)
        np.testing.assert_allclose(out[0], [0.6, 0.8])
        np.testing.assert_allclose(out[1], [0.0, 0.0])  # zero prefix stays zero, no NaN


class EmbedderTests(unittest.TestCase):
    def test_gemma_query_prompt_and_matryoshka_dim(self):
        model = fake_model(768)
        embedder = get_embedder("embeddinggemma-2", model=model)
        out = embedder.embed(["wildfire smoke"], kind="query", dim=128)
        self.assertEqual(out.shape, (1, 128))
        np.testing.assert_allclose(np.linalg.norm(out, axis=1), 1.0, rtol=1e-6)
        model.encode.assert_called_once_with(["wildfire smoke"], convert_to_numpy=True, prompt_name="SearchQuery")

    def test_gemma_document_prompt_full_dim(self):
        model = fake_model(768)
        out = get_embedder(model=model).embed(["a", "b"])
        self.assertEqual(out.shape, (2, 768))
        self.assertEqual(model.encode.call_args.kwargs["prompt_name"], "Document")

    def test_baseline_prompts(self):
        model = fake_model(384)
        embedder = get_embedder("e5-small", model=model)
        embedder.embed(["q"], kind="query")
        self.assertEqual(model.encode.call_args.kwargs["prompt"], "query: ")
        embedder.embed(["d"])
        self.assertEqual(model.encode.call_args.kwargs["prompt"], "passage: ")

    def test_rejects_unsupported_dim_modality_and_kind(self):
        embedder = get_embedder(model=fake_model(768))
        with self.assertRaises(ValueError):
            embedder.embed(["a"], dim=100)
        with self.assertRaises(NotImplementedError):
            get_embedder("e5-small", model=fake_model(384)).embed(["img.png"], modality="image")
        with self.assertRaises(ValueError):
            embedder.embed(["a"], kind="passage")
        with self.assertRaises(ValueError):
            get_embedder("nope")

    def test_media_goes_in_bare_keyed_by_modality(self):
        model = fake_model(768)
        embedder = get_embedder(model=model)
        embedder.embed([Path("a.png")], modality="image", kind="query", dim=256)
        model.encode.assert_called_once_with([{"image": "a.png"}], convert_to_numpy=True)

        samples = np.zeros(16000, dtype=np.float32)
        with mock.patch.object(media, "load_audio", return_value=samples) as load_audio:
            embedder.embed(["a.wav"], modality="audio")
        load_audio.assert_called_once_with("a.wav")
        audio = model.encode.call_args.args[0][0]["audio"]
        self.assertEqual(audio["sampling_rate"], 16000)
        self.assertIs(audio["array"], samples)

        video = {"array": np.zeros((2, 4, 4, 3)), "video_metadata": {}}
        with mock.patch.object(media, "load_video", return_value=video):
            embedder.embed(["a.mp4"], modality="video")
        self.assertEqual(model.encode.call_args.args[0], [{"video": video}])

        decoded = {"array": samples, "sampling_rate": 16000}
        embedder.embed([decoded], modality="audio")
        self.assertEqual(model.encode.call_args.args[0], [{"audio": decoded}])

    def test_empty_input_skips_model(self):
        model = fake_model(768)
        out = get_embedder(model=model).embed([], dim=256)
        self.assertEqual(out.shape, (0, 256))
        model.encode.assert_not_called()

    def test_model_loads_lazily(self):
        embedder = get_embedder("e5-small")
        self.assertIsNone(embedder._model)
        self.assertEqual(set(BACKENDS), {"embeddinggemma-2", "e5-small"})


@unittest.skipUnless(importlib.util.find_spec("av"), "PyAV is only in the embed image")
class MediaTests(unittest.TestCase):
    def test_load_audio_resamples_to_16k(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tone.wav"
            rate = 44100
            tone = (0.5 * np.sin(2 * math.pi * 440 * np.arange(rate) / rate) * 32767).astype("<i2")
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(rate)
                out.writeframes(tone.tobytes())  # 1 s at 44.1 kHz
            samples = media.load_audio(path)
        self.assertEqual(samples.dtype, np.float32)
        self.assertAlmostEqual(len(samples), 16000, delta=200)
        self.assertAlmostEqual(float(np.abs(samples).max()), 0.5, delta=0.05)

    def test_load_video_samples_one_frame_per_second(self):
        import av

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clip.mp4"
            with av.open(str(path), "w") as out:
                stream = out.add_stream("libx264", rate=8)
                stream.width = stream.height = 64
                stream.pix_fmt = "yuv420p"
                for _ in range(24):  # 3 s at 8 fps
                    frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), dtype=np.uint8), format="rgb24")
                    for packet in stream.encode(frame):
                        out.mux(packet)
                for packet in stream.encode():
                    out.mux(packet)
            video = media.load_video(path)
        self.assertEqual(video["array"].shape, (3, 64, 64, 3))
        self.assertEqual(video["video_metadata"]["fps"], 1.0)


class BakeoffTests(unittest.TestCase):
    def test_recall_at_k(self):
        bakeoff = load_bakeoff()
        vocab = ["smoke", "salmon", "saumon", "photo"]

        def encode(inputs, **kwargs):
            # Bag-of-words vectors so the ranking is predictable.
            return np.array([[float(word in text.lower()) for word in vocab] + [0.01] for text in inputs])

        model = mock.Mock()
        model.encode.side_effect = encode
        embedder = bakeoff.get_embedder("e5-small", model=model)
        embedder.dims = (5,)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.jsonl"
            path.write_text(
                '{"id": "d1", "content": "wildfire smoke"}\n'
                '{"id": "d2", "content": "saumon and salmon rivers"}\n'
                '{"id": "d3", "modality": "image", "content": "x.png"}\n'
                "\n"
                '{"query": "smoke", "lang": "en", "relevant": ["d1"]}\n'
                '{"query": "saumon", "lang": "fr", "relevant": ["d2"]}\n'
                '{"query": "photo", "lang": "en", "relevant": ["d3"]}\n',
                encoding="utf-8",
            )
            items, queries = bakeoff.load(path)
            self.assertEqual((len(items), len(queries)), (3, 3))
            with mock.patch("builtins.print"):
                scores = bakeoff.recall_at_k(embedder, items, queries, k=1)

        # The image item is skipped (text-only backend), so "photo" never finds d3.
        self.assertEqual(scores, {"all": 2 / 3, "en": 0.5, "fr": 1.0})

    def test_sample_file_is_valid(self):
        bakeoff = load_bakeoff()
        items, queries = bakeoff.load(ROOT / "evals" / "embed" / "sample_bakeoff.jsonl")
        ids = {item["id"] for item in items}
        self.assertTrue(5 <= len(items) <= 10)
        self.assertEqual({q["lang"] for q in queries}, {"en", "fr"})
        for query in queries:
            self.assertTrue(set(query["relevant"]) <= ids)


if __name__ == "__main__":
    unittest.main()
