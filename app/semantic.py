"""Búsqueda semántica opcional: convierte textos en vectores (embeddings) para comparar significados.

Proveedores (SABIO_EMBEDDINGS):
- auto (por defecto): Voyage AI si hay VOYAGE_API_KEY; si no, sin búsqueda semántica.
- voyage: API de Voyage AI (modelo voyage-4-lite). No usa memoria del servidor: entra en 512 MB.
- local: multilingual-e5-small en ONNX (fastembed). Ocupa unos 430 MB de memoria, así que solo
  sirve en máquinas con 1 GB o más (no en el plan gratuito de Render).
- off: solo búsqueda por palabras.

Los vectores se calculan al absorber el sitio y se guardan junto a cada fragmento.
Los embeddings ordenan y amplían la búsqueda, pero nunca autorizan por sí solos una respuesta:
medimos que "¿tienen auriculares Sony?" se parece más a los auriculares Sonix que varias preguntas
válidas, así que la decisión de responder sigue necesitando evidencia en el texto del sitio.
"""
from __future__ import annotations

import os

import numpy as np

VOYAGE_MODEL = os.environ.get("SABIO_VOYAGE_MODEL", "voyage-4-lite")
LOCAL_MODEL = "intfloat/multilingual-e5-small"
_local = None


def backend() -> str | None:
    mode = os.environ.get("SABIO_EMBEDDINGS", "auto").strip().lower()
    if mode == "off":
        return None
    if mode == "voyage" or (mode == "auto" and os.environ.get("VOYAGE_API_KEY")):
        return "voyage" if os.environ.get("VOYAGE_API_KEY") else None
    if mode == "local":
        return "local"
    return None


def model_name() -> str | None:
    b = backend()
    return {"voyage": f"voyage:{VOYAGE_MODEL}", "local": f"local:{LOCAL_MODEL}"}.get(b)


def _voyage(texts: list[str], input_type: str) -> np.ndarray:
    import httpx
    out = []
    with httpx.Client(timeout=60) as c:
        for i in range(0, len(texts), 128):
            r = c.post("https://api.voyageai.com/v1/embeddings",
                       headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
                       json={"input": texts[i:i + 128], "model": VOYAGE_MODEL, "input_type": input_type,
                             "output_dimension": 512})
            r.raise_for_status()
            out += [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    return np.array(out, dtype=np.float32)


def _local_model():
    global _local
    if _local is None:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
        name = LOCAL_MODEL + "-q"
        if name not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            TextEmbedding.add_custom_model(
                model=name, pooling=PoolingType.MEAN, normalization=True, dim=384,
                sources=ModelSource(hf="Xenova/multilingual-e5-small"), model_file="onnx/model_quantized.onnx")
        _local = TextEmbedding(name, threads=1)
    return _local


def _embed(texts: list[str], kind: str) -> np.ndarray | None:
    b = backend()
    if not b or not texts:
        return None
    try:
        if b == "voyage":
            v = _voyage(texts, kind)
        else:  # e5 necesita estos prefijos para distinguir preguntas de pasajes
            prefix = "query: " if kind == "query" else "passage: "
            v = np.array(list(_local_model().embed([prefix + t[:2000] for t in texts], batch_size=16)),
                         dtype=np.float32)
    except Exception:
        return None  # sin embeddings SABIO sigue funcionando por palabras
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)


def embed_documents(texts: list[str]) -> np.ndarray | None:
    return _embed(texts, "document")


def embed_query(text: str) -> np.ndarray | None:
    v = _embed([text], "query")
    return v[0] if v is not None else None


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes | None) -> np.ndarray | None:
    return np.frombuffer(b, dtype=np.float32) if b else None
