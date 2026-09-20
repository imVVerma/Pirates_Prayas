"""
heatmap.py — optional Grad-CAM overlay for the X-ray screening model.
"If time allows" per the original spec; never required for build_xray_block.

AUDIT NOTE: the old tb_xray_model.py used `pytorch_grad_cam` and referenced
`model.inception.Mixed_7c` as the target layer. Both assume a PyTorch
model with attribute-style submodules. The real checkpoint is a Keras/
TensorFlow model with a nested Functional InceptionV3 submodel (see
xray_adapter.py) -- `pytorch_grad_cam` cannot be pointed at a Keras model
at all, and there is no `.inception.Mixed_7c` attribute on it. This
module replaces that with a small, dependency-free (TensorFlow + numpy
only) Grad-CAM implementation that finds the model's last 4D-output
(conv-like) layer generically instead of guessing an attribute path.

Best-effort by design: any failure (unsupported layer graph, missing
TensorFlow, etc.) returns None rather than raising -- a missing heatmap
must never block filling the rest of the xray block.

NOT yet exercised against the real nested-model tb_model.h5 (the nested
InceptionV3 submodel makes locating a "last conv layer" and building a
sub-graph for Grad-CAM materially harder than a flat architecture; the
generic layer-walk below only looks at the outer graph's direct layers,
so it will most likely return None gracefully on this specific
checkpoint rather than actually produce a heatmap). Treat this as
optional/best-effort exactly as scoped, not as verified.
"""

from __future__ import annotations

import os
from typing import Optional


def _find_last_conv_layer(model):
    for layer in reversed(model.layers):
        try:
            shape = layer.output_shape
        except Exception:
            continue
        if isinstance(shape, tuple) and len(shape) == 4:
            return layer
    return None


def generate_gradcam(
    model,
    preprocessed_batch,
    pil_image,
    out_path: str,
) -> Optional[str]:
    """Runs Grad-CAM against `model`'s last conv-like layer for the batch's
    predicted class and writes an overlay PNG to out_path. Returns out_path
    on success, None on any failure (best-effort, never raises)."""
    try:
        import numpy as np
        import tensorflow as tf
        from PIL import Image

        conv_layer = _find_last_conv_layer(model)
        if conv_layer is None:
            return None

        grad_model = tf.keras.models.Model(
            inputs=model.inputs, outputs=[conv_layer.output, model.output]
        )

        with tf.GradientTape() as tape:
            conv_output, predictions = grad_model(preprocessed_batch)
            score = predictions[:, 0]

        grads = tape.gradient(score, conv_output)
        if grads is None:
            return None

        pooled_grads = tf.reduce_mean(grads, axis=(0, 1, 2))
        conv_output = conv_output[0]
        heatmap = conv_output @ pooled_grads[..., tf.newaxis]
        heatmap = tf.squeeze(heatmap)
        heatmap = tf.maximum(heatmap, 0) / (tf.math.reduce_max(heatmap) + 1e-8)
        heatmap = heatmap.numpy()

        heatmap_img = Image.fromarray(np.uint8(255 * heatmap)).resize(pil_image.size)
        heatmap_arr = np.array(heatmap_img.convert("L"))

        base = np.array(pil_image.convert("RGB"))
        overlay = base.copy()
        overlay[..., 0] = np.clip(base[..., 0].astype(int) + heatmap_arr, 0, 255)

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        Image.fromarray(overlay.astype("uint8")).save(out_path)
        return out_path
    except Exception:
        return None
