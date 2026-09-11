# Project-Happy-

## Skills

### `remove-ai-marks`

Vendored from [haidrrrry/claude-watermark-remover](https://github.com/haidrrrry/claude-watermark-remover)
(MIT). Lives in [`.claude/skills/remove-ai-marks/`](.claude/skills/remove-ai-marks/).

Strips machine-readable AI provenance marks: invisible Unicode (zero-width, bidi,
tag chars, exotic spaces), C2PA / Content Credentials, and EXIF/XMP/document
metadata across PNG, JPEG, WebP, AVIF, HEIC, SVG, PDF, DOCX, ODT, HTML and
Markdown. Python standard library only — no pip install, no network, no API key.
It does **not** erase visible watermarks or logos from images.

#### Use it in Claude Code

It loads automatically in any session rooted at this repo. Ask for it by intent
("strip the invisible Unicode from this draft", "remove the C2PA metadata from
this PNG") or run `/remove-ai-marks`.

#### Use it in Claude chats (claude.ai) or the Claude desktop app

Zip the skill folder and upload it under **Settings → Capabilities → Skills →
Upload skill**. The uploader rejects any skill whose `name` contains the
reserved word `claude`, which is why this is named `remove-ai-marks` rather than
upstream's `remove-claude-marks`:

```bash
cd .claude/skills && zip -r ../../remove-ai-marks.zip remove-ai-marks
```

The zip must contain the `remove-ai-marks/` folder with `SKILL.md` at its
root. Skills require the code-execution tool to be enabled in the chat, since
the cleaning scripts run in the sandbox.

#### Use it in any other repo on this machine

```bash
cp -r .claude/skills/remove-ai-marks ~/.claude/skills/
```

#### Optional system tools

`qpdf` is required for a real PDF strip; `exiftool` catches residual PDF
metadata; `c2patool` helps verify image results. All are optional — the skill
degrades gracefully and says when a result is best-effort.

#### Intended use

Content you own or are authorized to process: privacy, engineering hygiene, and
watermarking research. See
[`references/ethics.md`](.claude/skills/remove-ai-marks/references/ethics.md).
A removed mark does not mean content was never AI-assisted, and a clean strip
does not prove no provenance remains — soft-bound and SynthID-class signals can
survive.
