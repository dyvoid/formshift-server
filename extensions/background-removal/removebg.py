"""Background removal on top of rembg (U^2-Net family models).

Runs inside this extension's own venv via the formshift extension runner:
plain function contract, no formshift imports (ADR 0012).

Params:
    model: rembg model name (default "u2netp", the small CPU-friendly one;
           "u2net" and "isnet-general-use" trade speed for quality).

Model weights download to U2NET_HOME (rembg's convention) on first use.
"""

from rembg import new_session, remove


def run(inputs: dict, params: dict, draft: bool) -> dict:
    model = str(params.get("model", "u2netp"))
    result = remove(inputs["image"], session=new_session(model))
    assert isinstance(result, bytes)  # bytes in -> bytes out overload
    return {"image": ("raster/png", result)}
