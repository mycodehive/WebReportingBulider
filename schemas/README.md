# WRPX 1.0.0 interchange

A `.wrpx` file is a ZIP with `manifest.json`, `project.json`, report definitions
in `reports/report_N.json`, and optional raster images in `assets/UUID.ext`.
JSON serialization uses UTF-8, sorted object keys, compact separators, and finite
numbers. ZIP exports are deterministic and use stored members.

The JSON Schemas describe the structural interchange contract. The Python
`validate_definition` and `import_project` validators are authoritative and also
check semantic references, unique IDs, page bounds, supported scopes, parameter
constraints, asset references and integrity. The schemas deliberately do not
claim to encode these cross-object semantic constraints.

Project packages include no connection credentials, physical table/column
bindings, execution data or executable code. Users explicitly configure local
bindings after import. SHA-256 manifests detect accidental modification; they
are not signatures and do not establish publisher identity. Always validate
untrusted imports even when all hashes match.

Supported alpha layout: fixed pages or one-dataset flow pages, one band of each
kind, one group level, page headers/footers, indivisible repeated Detail bands,
explicit page breaks, first/single/row/group/aggregate fields, raster images and
plain escaped text. Long text growth uses conservative character measurement.
An indivisible band taller than the page body is rejected rather than clipped
silently. Nested groups, subreports, joins, arbitrary HTML/JavaScript, SVG,
external image URLs and table/chart/crosstab elements are rejected.

`pdf_bytes` uses the exact paginated preview HTML with server Chromium. It needs
the optional `pdf` dependencies and installed Chromium. The same source is used
for preview and PDF; cross-browser printing/font rasterization equality is not
guaranteed.
