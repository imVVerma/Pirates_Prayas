"""
xray_adapter.py — M3: pretrained TB chest X-ray screening model -> the
"xray" block of case-schema.json (M0). No training. No UI changes.

=======================================================================
AUDIT FINDINGS — VERIFIED AGAINST THE REAL tb_model.h5 (2026-09-20)
=======================================================================
Loading: the old tb_xray_model.py used
    AutoModelForImageClassification.from_pretrained("Owos/tb-classifier")
This cannot work: the checkpoint is a Keras/TensorFlow HDF5 file
(`tb_model.h5`), not a `transformers`-format checkpoint, and the repo's
config.json declares "architectures": ["InceptinV3ForImageClassification"]
-- a class that does not exist in `transformers` (typo/placeholder).
Confirmed fixed here by loading directly with Keras instead (see
LazyKerasTBModel below).

Framework compatibility (confirmed empirically): the real tb_model.h5 is
a Keras Functional model with a NESTED Functional submodel (InceptionV3
nested inside the outer classifier graph). Keras 3 (bundled with
TensorFlow>=2.16) fails to load this specific file --
`keras.models.load_model` raises "Invalid Functional model configuration
... graph ... has loops or disconnected nodes." The `tf-keras` package
(the maintained Keras-2 compatibility shim) loads it without any changes
to the file, once `TF_USE_LEGACY_KERAS=1` is set before `tensorflow` is
first imported anywhere in the process. LazyKerasTBModel sets this.

Preprocessing (VERIFIED against the real weights, not just the author's
scripts): predict.py and deployment/streamlit_deploy.py (the author's own
inference code) both manually divide the loaded image by 255 before
calling predict(). Reading the training notebook (training.ipynb, cell 17,
`base_model()`) showed the model itself is built as
    Input -> Rescaling(1/255) -> InceptionV3 -> ... -> Dense(1, sigmoid)
i.e. the 1/255 scaling is baked into the SAVED graph, applied to the raw
input -- and the real data pipeline it was trained against
(image_dataset_from_directory, no external rescale) fed it raw 0-255
values. That means the author's own deployment scripts likely
double-rescale relative to training.

This was then CONFIRMED two independent ways against the actual uploaded
tb_model.h5:
  1. scripts/inspect_h5_architecture.py opened the file's own embedded
     Keras config (h5py, no TensorFlow needed) and found a Rescaling
     layer with scale=0.00392156862745098 (=1/255) right after the
     InputLayer.
  2. scripts/verify_xray_model.py ran the real model on one known-normal
     and one known-TB-positive image (the model author's own reference
     examples) both ways:
       raw 0-255      -> normal=0.0246, TB=0.9847  (separation 0.96)
       pre-divided/255 -> normal=0.9897, TB=0.9907  (separation 0.001)
     Full report: reports/smoke_test_report_20260920T002345Z.{json,md}.

CONCLUSION: feed the model RAW 0-255 pixel values. Do NOT divide by 255
-- the model's own first layer does that. Confirmed input size (300,300)
both from predict.py and the real model's input_shape=(None,300,300,3).

Labels: config.json's id2label is {"0": "Negative", "1": "Positive"};
predict.py independently confirms classes=["Normal","Tuberculosis"] with
`classes[round(pred[0][0])]`. CONFIRMED on the real model + real labelled
images above: known-normal scored 0.025 (low), known-TB scored 0.985
(high) -- direction matches, index 1/high score = TB-positive. The
schema's real enum for `xray.model_flag` is "abnormal"/"normal" (the old
module wrongly used "positive"/"negative" -- M0's own
invalid-fixtures/02-bad-xray-flag.json exists to catch exactly that).

IMPORTANT CONFIRMED LIMITATION -- the model has low specificity: the same
verification run fed the model an all-black image, an all-white image,
and random noise (all under the CORRECT raw-0-255 preprocessing). All
three scored >0.9 -- the same range as the genuine TB-positive image
(0.9901, 0.9952, 0.9865 vs 0.9847). The model appears to default to
"abnormal" for almost anything that doesn't specifically match its
narrow training distribution of normal chest X-rays, rather than
genuinely recognizing TB-specific features. Treat model_flag="abnormal"
as low-specificity and never as anything resembling confirmation --
consistent with case-schema.json's own framing of model_confidence as an
"uncalibrated model score."

License: Hugging Face repo tagged apache-2.0 (weights); author's
training/inference code repo (github.com/owos/tb_project) carries an MIT
LICENSE file. Both permissive.

Validation status: SELF-REPORTED ONLY on a held-out split of the model's
own training dataset (binary_accuracy 0.9857, precision 0.9259, recall
0.9843). No independent/external-cohort validation. Model card states
outright it "has not undergone clinical testing." The bias-check finding
above is independent evidence reinforcing that caution.
=======================================================================
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, runtime_checkable

MODEL_REPO_ID = "Owos/tb-classifier"
MODEL_FILENAME = "tb_model.h5"
MODEL_LICENSE = "apache-2.0 (weights, Hugging Face); MIT (training code, github.com/owos/tb_project)"

# Traceable, honest identifier for case-schema.json's `xray.model_id`.
MODEL_ID_FOR_SCHEMA = "owos-tb-classifier-h5-unvalidated-v1"

INPUT_SIZE = (300, 300)  # confirmed against the real model's input_shape=(None,300,300,3)
POSITIVE_THRESHOLD = 0.5  # sigmoid decision boundary; id2label[1] = Positive/Tuberculosis

AUDIT_NOTE = (
    "Owos/tb-classifier (Keras/TensorFlow InceptionV3, transfer-learned). "
    "Self-reported eval only (binary_accuracy 0.9857, precision 0.9259, "
    "recall 0.9843) on a held-out split of its own training data; no "
    "independent or clinical validation. Verified low-specificity: "
    "all-black/all-white/random-noise inputs also score >0.9 'abnormal' "
    "in the same range as a genuine positive image (see "
    "reports/smoke_test_report_20260920T002345Z.md). Screening "
    "abnormality flag only, never a diagnosis. " + MODEL_LICENSE
)


@runtime_checkable
class KerasLikeModel(Protocol):
    """Anything with a Keras-style predict(batch) -> array method. A real
    loaded Keras model satisfies this; so does a hand-written test stub."""

    def predict(self, x, verbose: int = 0):
        ...


def preprocess_image(pil_image) -> "object":
    """Pure, network-free preprocessing matching the REAL model's
    confirmed expectation: resize to 300x300 RGB, RAW 0-255 float pixel
    values (no division by 255 -- the model's own first layer,
    Rescaling(1/255), does that internally; verified directly against
    tb_model.h5's embedded architecture and against real inference
    scores on labelled images, see module docstring)."""
    import numpy as np

    img = pil_image.convert("RGB").resize(INPUT_SIZE)
    arr = np.asarray(img, dtype="float32")  # deliberately NOT divided by 255
    return np.expand_dims(arr, axis=0)


def postprocess_score(raw_score: float, threshold: float = POSITIVE_THRESHOLD) -> Tuple[str, float]:
    """Pure mapping from the model's single sigmoid output to the schema's
    model_flag enum ("abnormal" | "normal") plus a confidence in [0, 1].
    Kept separate from any I/O so it is exhaustively unit-testable."""
    raw_score = float(raw_score)
    is_abnormal = raw_score >= threshold
    flag = "abnormal" if is_abnormal else "normal"
    confidence = raw_score if is_abnormal else (1.0 - raw_score)
    confidence = min(max(confidence, 0.0), 1.0)
    return flag, round(confidence, 4)


@dataclass
class XrayInference:
    model_flag: str
    model_confidence: float
    raw_score: float


def run_inference(model: KerasLikeModel, pil_image) -> XrayInference:
    """One forward pass. `model` is injected so this can be exercised with
    a stub in tests, or the real LazyKerasTBModel in production."""
    batch = preprocess_image(pil_image)
    raw = model.predict(batch, verbose=0)
    score = float(raw[0][0])
    flag, confidence = postprocess_score(score)
    return XrayInference(model_flag=flag, model_confidence=confidence, raw_score=score)


class LazyKerasTBModel:
    """Lazy-loading wrapper around the real Owos/tb-classifier checkpoint.
    Nothing here touches the network or imports TensorFlow at import time
    -- only on first predict() call -- so importing this module is always
    safe offline and in unit tests.

    CONFIRMED REQUIRED: TF_USE_LEGACY_KERAS=1 must be set before
    `tensorflow` is first imported anywhere in the process. Keras 3
    (TensorFlow >= 2.16, the default on Python 3.12) cannot load this
    specific file -- it raises "Invalid Functional model configuration"
    on the nested InceptionV3 submodel. The `tf-keras` package (Keras 2
    compatibility shim) loads it correctly. This was found by actually
    trying to load the real file, not assumed."""

    def __init__(self, repo_id: str = MODEL_REPO_ID, filename: str = MODEL_FILENAME, local_path: Optional[str] = None):
        self.repo_id = repo_id
        self.filename = filename
        self.local_path = local_path  # set this to skip the hub download entirely
        self._model = None

    def _lazy_load(self):
        if self._model is not None:
            return

        os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

        if self.local_path:
            weights_path = self.local_path
        else:
            from huggingface_hub import hf_hub_download

            weights_path = hf_hub_download(repo_id=self.repo_id, filename=self.filename)

        from tensorflow import keras

        self._model = keras.models.load_model(weights_path, compile=False)

    def predict(self, x, verbose: int = 0):
        self._lazy_load()
        return self._model.predict(x, verbose=verbose)


def build_xray_block(
    *,
    available: bool,
    image_ref: Optional[str] = None,
    captured_at: Optional[str] = None,
    pil_image=None,
    model: Optional[KerasLikeModel] = None,
    heatmap_ref: Optional[str] = None,
) -> dict:
    """Builds the case-schema.json "xray" object exactly: 7 keys, no more
    (the old module's `citation` key would fail `additionalProperties:
    false`; AUDIT_NOTE above is the place for that text instead).

    - available=False -> every other field must be null (M0 invariant).
    - available=True with no pil_image/model -> X-ray was captured but not
      (yet) run through the model; model_flag stays null, a valid state
      per M0's validator.
    - available=True with pil_image+model -> runs real inference and fills
      model_flag/model_confidence/model_id together.
    """
    if not available:
        return {
            "available": False,
            "image_ref": None,
            "model_flag": None,
            "model_confidence": None,
            "heatmap_ref": None,
            "model_id": None,
            "captured_at": None,
        }

    if not image_ref or not captured_at:
        raise ValueError("available X-ray requires image_ref and captured_at")

    model_flag = None
    model_confidence = None
    model_id = None
    resolved_heatmap_ref = None

    if pil_image is not None and model is not None:
        inference = run_inference(model, pil_image)
        model_flag = inference.model_flag
        model_confidence = inference.model_confidence
        model_id = MODEL_ID_FOR_SCHEMA
        resolved_heatmap_ref = heatmap_ref  # Grad-CAM (heatmap.py) is best-effort; caller supplies ref if it succeeded

    return {
        "available": True,
        "image_ref": image_ref,
        "model_flag": model_flag,
        "model_confidence": model_confidence,
        "heatmap_ref": resolved_heatmap_ref,
        "model_id": model_id,
        "captured_at": captured_at,
    }


def unavailable_xray_block() -> dict:
    """Use when no X-ray was captured for this case (X-ray is optional)."""
    return build_xray_block(available=False)

# M3 contract surface required by the included later-version tests and
# verify_xray_model.py. Kept additive to the original adapter.
def sha256_file(path):
    import hashlib
    from pathlib import Path
    p=Path(path)
    if not p.is_file():
        from provenance import EvidenceError
        raise EvidenceError('file does not exist')
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def model_image_shape(model):
    from provenance import EvidenceError
    shape=getattr(model,'input_shape',None)
    if isinstance(shape,list):
        if len(shape)!=1: raise EvidenceError('expected single input image')
        shape=shape[0]
    if not shape or len(shape)!=4 or shape[0] not in (None,1) or shape[-1]!=3:
        raise EvidenceError('unknown model input shape (expected NHWC RGB)')
    if not all(isinstance(i,int) and i>0 for i in shape[1:3]):
        raise EvidenceError('unknown image dimensions')
    return int(shape[1]),int(shape[2])


def detect_pixel_range(model):
    """Inspect single nested Rescaling(1/255), fail on ambiguity."""
    from provenance import EvidenceError
    seen=set();scales=[]
    def visit(m):
        if id(m) in seen: return
        seen.add(id(m))
        for layer in getattr(m,'layers',[]) or []:
            if type(layer).__name__=='Rescaling':
                value=float(getattr(layer,'scale',float('nan')))
                if not abs(value-1/255)<1e-7:
                    raise EvidenceError('unsupported model rescaling layer')
                scales.append(value)
            if hasattr(layer,'layers'):
                visit(layer)
    visit(model)
    if len(scales)>1:raise EvidenceError('multiple preprocessing Rescaling layers')
    return 'raw_0_255' if scales else None


def prepare_image(image_path,model,*,pixel_range='auto'):
    """Return (batch, mode); never double scale or guess preprocessing."""
    from pathlib import Path
    from provenance import EvidenceError
    from PIL import Image
    import numpy as np
    path=Path(image_path)
    if path.suffix.lower() not in ('.jpg','.jpeg','.png'):
        raise EvidenceError('use PNG/JPEG image only')
    if not path.is_file(): raise EvidenceError('image file missing')
    height,width=model_image_shape(model)
    mode=detect_pixel_range(model) if pixel_range=='auto' else pixel_range
    if mode not in ('raw_0_255','zero_one'):
        raise EvidenceError('preprocessing unknown; specify verified pixel range')
    try:
        with Image.open(path) as image:
            arr=np.asarray(image.convert('RGB').resize((width,height)),dtype=np.float32)
    except Exception as exc:
        raise EvidenceError('invalid RGB image') from exc
    if mode=='zero_one': arr/=255.0
    return np.expand_dims(arr,axis=0),mode


def infer_xray(*,model,model_sha256,image_path,image_ref,captured_at,
               label_mapping_verified=False,pixel_range='auto'):
    """M0 block with RAW sigmoid model_confidence; not calibrated probability."""
    import re
    import numpy as np
    from provenance import EvidenceError, aware_time, require_text
    require_text(image_ref,'xray.image_ref')
    aware_time(captured_at,'xray.captured_at')
    if not label_mapping_verified:
        raise EvidenceError('label mapping not independently verified')
    if not isinstance(model_sha256,str) or not re.fullmatch('[a-f0-9]{64}',model_sha256):
        raise EvidenceError('valid model_sha256 required')
    batch,mode=prepare_image(image_path,model,pixel_range=pixel_range)
    try: raw=np.asarray(model.predict(batch,verbose=0),dtype=float)
    except Exception as exc:raise EvidenceError('model prediction failed') from exc
    if raw.shape != (1,1) or not np.isfinite(raw[0,0]) or not 0<=raw[0,0]<=1:
        raise EvidenceError('expected finite sigmoid scalar in [0,1]')
    score=float(raw[0,0])
    return {'available':True,'image_ref':image_ref,
            'model_flag':'abnormal' if score>=POSITIVE_THRESHOLD else 'normal',
            'model_confidence':score,'heatmap_ref':None,
            'model_id':f'{MODEL_REPO_ID};sha256={model_sha256};input={mode};threshold={POSITIVE_THRESHOLD}',
            'captured_at':captured_at}


def load_local_h5(model_path):
    from pathlib import Path
    from provenance import EvidenceError
    path=Path(model_path)
    if not path.is_file():raise EvidenceError('model file not found; no auto-download')
    import os
    os.environ.setdefault('TF_USE_LEGACY_KERAS','1')
    from tensorflow import keras
    try:model=keras.models.load_model(str(path),compile=False)
    except Exception as exc: raise EvidenceError('unable to load real local H5') from exc
    return model,sha256_file(path)


def infer_verified_local(*,model_path,verification_report_path,image_path,image_ref,captured_at):
    import json
    from pathlib import Path
    from provenance import EvidenceError
    model,hashed=load_local_h5(model_path)
    try:report=json.loads(Path(verification_report_path).read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc: raise EvidenceError('verification report unavailable') from exc
    if hashed != report.get('model_sha256'):
        raise EvidenceError('checkpoint and verification report SHA256 differ')
    if (report.get('status')!='checkpoint_smoke_pass_only' or report.get('clinical_validation') is not False
        or report.get('label_mapping')!='class_1=TB_suggestive, class_0=normal_in_model'
        or report.get('preprocessing') not in ('raw_0_255','zero_one')):
        raise EvidenceError('verification report does not establish required smoke-test metadata')
    return infer_xray(model=model,model_sha256=hashed,image_path=image_path,
                     image_ref=image_ref,captured_at=captured_at,
                     label_mapping_verified=True,pixel_range=report['preprocessing'])
