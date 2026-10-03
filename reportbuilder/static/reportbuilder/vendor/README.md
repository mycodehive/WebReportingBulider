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

Application configuration excludes source-code, image, video and fullscreen
buttons, inserts pasted content as plain text, disables clipboard images and drag/drop, and keeps server-side Bleach
sanitization on both save and display. Browser filtering is not a replacement
for that server boundary.
