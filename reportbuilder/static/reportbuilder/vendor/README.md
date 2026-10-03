# Board editor dependencies

The board editor uses locally served Summernote **0.9.1 Lite** and jQuery **3.7.1**.
Bootstrap and runtime CDN requests are not required. MIT license notices are
included beside each dependency.

- Summernote distribution: https://registry.npmjs.org/summernote/-/summernote-0.9.1.tgz
- Summernote source: https://github.com/summernote/summernote/tree/v0.9.1
- jQuery distribution: https://github.com/jquery/jquery-dist/tree/3.7.1

The Summernote JS, CSS, Korean translation and icon fonts are copied unchanged
from the official npm distribution. When upgrading, update all files together,
review upstream security changes, run board editor/browser tests, and verify
`collectstatic` and the built wheel. This is a version pin, not a claim that the
editor is free of all vulnerabilities.

Picture, Video and Code View are enabled. Uploaded raster images are limited to
64 KiB; larger images can use HTTPS URLs. Video embeds are limited to YouTube
and Vimeo. Paste stays plain text and drag/drop stays disabled. Code View uses
DOMPurify before preview and submit, with server-side Bleach and media validation
on both save and display. Browser filtering does not replace the server boundary.

DOMPurify **3.4.16** is locally served under its Apache-2.0 license (included).
Source: https://github.com/cure53/DOMPurify/tree/3.4.16
Distribution: https://registry.npmjs.org/dompurify/-/dompurify-3.4.16.tgz
The npm SHA-512 integrity was checked. Only the final source-map reference was
removed because the debug map is not shipped; runtime code and notices are preserved.
