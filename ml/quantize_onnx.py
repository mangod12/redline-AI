"""Quantize ONNX models to INT8 for edge deployment.

Usage:
    python ml/quantize_onnx.py --model intent
    python ml/quantize_onnx.py --model emotion
    python ml/quantize_onnx.py --model both --output-dir ml/
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("quantize_onnx")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_OUTPUT_DIR = _SCRIPT_DIR

_INTENT_ONNX = _SCRIPT_DIR / "intent_model.onnx"
_EMOTION_ONNX = _SCRIPT_DIR / "emotion_model.onnx"

_INTENT_INT8_NAME = "intent_model_int8.onnx"
_EMOTION_INT8_NAME = "emotion_model_int8.onnx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_size_mb(path: Path) -> float:
    """Return file size in megabytes."""
    return path.stat().st_size / (1024 * 1024)


def _print_size_stats(original: Path, quantized: Path) -> None:
    """Print a comparison table of original vs quantized model sizes."""
    orig_mb = _file_size_mb(original)
    quant_mb = _file_size_mb(quantized)
    reduction_pct = (1.0 - quant_mb / orig_mb) * 100 if orig_mb > 0 else 0.0

    log.info("=" * 60)
    log.info("Size comparison for %s", original.name)
    log.info("  Original  : %.2f MB  (%s)", orig_mb, original)
    log.info("  Quantized : %.2f MB  (%s)", quant_mb, quantized)
    log.info("  Reduction : %.1f%%", reduction_pct)
    log.info(
        "  Expected speedup: 1.5x-3x on CPU (varies by hardware/model)"
    )
    log.info("=" * 60)


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------

def quantize_model(source: Path, dest: Path) -> Path:
    """Apply dynamic INT8 quantization to an ONNX model.

    Returns the path to the quantized model.
    Raises FileNotFoundError if *source* does not exist.
    """
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic
    except ImportError:
        log.error(
            "onnxruntime.quantization is not installed. "
            "Install with: pip install onnxruntime"
        )
        raise

    if not source.exists():
        raise FileNotFoundError(f"Source model not found: {source}")

    dest.parent.mkdir(parents=True, exist_ok=True)

    log.info("Quantizing %s -> %s (INT8 dynamic)", source, dest)
    start = time.perf_counter()

    quantize_dynamic(
        model_input=str(source),
        model_output=str(dest),
        weight_type=QuantType.QInt8,
    )

    elapsed = time.perf_counter() - start
    log.info("Quantization completed in %.2f s", elapsed)

    _print_size_stats(source, dest)
    return dest


# ---------------------------------------------------------------------------
# Validation via dummy inference
# ---------------------------------------------------------------------------

def _validate_intent(model_path: Path) -> None:
    """Run a dummy inference on the quantized intent model."""
    import onnxruntime as ort

    log.info("Validating quantized intent model: %s", model_path)
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        str(model_path),
        sess_options=opts,
        providers=["CPUExecutionProvider"],
    )

    input_names = {inp.name for inp in session.get_inputs()}
    # Build dummy inputs matching DistilBERT expected shapes
    batch, seq_len = 1, 16
    dummy_input_ids = np.ones((batch, seq_len), dtype=np.int64)
    dummy_attention_mask = np.ones((batch, seq_len), dtype=np.int64)

    feeds: dict[str, np.ndarray] = {
        "input_ids": dummy_input_ids,
        "attention_mask": dummy_attention_mask,
    }
    if "token_type_ids" in input_names:
        feeds["token_type_ids"] = np.zeros((batch, seq_len), dtype=np.int64)

    start = time.perf_counter()
    outputs = session.run(None, feeds)
    elapsed_ms = (time.perf_counter() - start) * 1000

    logits = outputs[0]
    log.info(
        "  Intent validation OK — output shape: %s, latency: %.1f ms",
        logits.shape,
        elapsed_ms,
    )


def _validate_emotion(model_path: Path) -> None:
    """Run a dummy inference on the quantized emotion model."""
    import onnxruntime as ort

    log.info("Validating quantized emotion model: %s", model_path)
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        str(model_path),
        sess_options=opts,
        providers=["CPUExecutionProvider"],
    )

    # Emotion model expects MFCC input: (batch, channel, mfcc_bands, time_steps)
    dummy_mfcc = np.random.randn(1, 1, 40, 94).astype(np.float32)
    input_name = session.get_inputs()[0].name

    start = time.perf_counter()
    outputs = session.run(None, {input_name: dummy_mfcc})
    elapsed_ms = (time.perf_counter() - start) * 1000

    logits = outputs[0]
    log.info(
        "  Emotion validation OK — output shape: %s, latency: %.1f ms",
        logits.shape,
        elapsed_ms,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantize ONNX models to INT8 for edge deployment.",
    )
    parser.add_argument(
        "--model",
        choices=["intent", "emotion", "both"],
        required=True,
        help="Which model(s) to quantize.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_DEFAULT_OUTPUT_DIR),
        help="Directory for quantized model output (default: ml/).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    targets: list[str] = (
        ["intent", "emotion"] if args.model == "both" else [args.model]
    )

    success_count = 0
    fail_count = 0

    for target in targets:
        if target == "intent":
            source = _INTENT_ONNX
            dest = output_dir / _INTENT_INT8_NAME
            validator = _validate_intent
        else:
            source = _EMOTION_ONNX
            dest = output_dir / _EMOTION_INT8_NAME
            validator = _validate_emotion

        try:
            quantize_model(source, dest)
            validator(dest)
            success_count += 1
        except FileNotFoundError:
            log.warning(
                "Skipping %s — source model not found at %s", target, source
            )
            fail_count += 1
        except Exception:
            log.exception("Failed to quantize/validate %s model", target)
            fail_count += 1

    log.info(
        "Done. %d succeeded, %d failed out of %d target(s).",
        success_count,
        fail_count,
        len(targets),
    )
    return 1 if fail_count > 0 and success_count == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
