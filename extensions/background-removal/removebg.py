"""Background removal on top of rembg (U^2-Net family models).

Runs inside this extension's own venv via the formshift extension worker:
plain function contract, no formshift imports (ADRs 0012/0015).

Params:
    model: rembg model name (default "u2netp", the small CPU-friendly one;
           "u2net" and "isnet-general-use" trade speed for quality).

The worker process is long-lived, so ONNX sessions are cached per model
name — the model loads once, not per run. Model weights download to
U2NET_HOME (rembg's convention) on first use.
"""

from rembg import new_session, remove

_sessions = {}


def run(inputs: dict, params: dict, draft: bool) -> dict:
    model = str(params.get("model", "u2netp"))
    if model not in _sessions:
        _sessions[model] = new_session(model)
    result = remove(inputs["image"], session=_sessions[model])
    assert isinstance(result, bytes)  # bytes in -> bytes out overload
    return {"image": ("raster/png", result)}
