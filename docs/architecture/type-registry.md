# Type string registry

Port type strings are an open namespace with strict matching (design doc, Modules): any module may
mint a new type, but two ports only connect when their type strings are exactly equal, and a type
string names both the data kind and its wire encoding. This document is the registry of
established conventions. Reuse an existing string to interoperate; mint a new one for a genuinely
new data kind or encoding, and record it here.

| Type string | Wire encoding | Notes |
|---|---|---|
| `raster/png` | PNG file bytes | Any color mode; consumers convert as needed |
| `vector/svg` | SVG document bytes, UTF-8 | |

Reserved conventions (not yet used by any module, listed to steer future minting):

- `raster/<format>` for encoded raster file formats (`raster/bmp`, `raster/pgm`, ...).
- `raster/rgba8` for raw un-encoded RGBA buffers, once a dimensions convention is defined —
  do not mint this casually; raw buffers need width/height metadata the payload contract doesn't
  carry yet.
- `vector/<format>` for path/vector documents.
- `text/plain` is used by the test suite's fake modules only.
