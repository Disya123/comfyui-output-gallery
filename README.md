# ComfyUI Output Gallery

A gallery/viewer extension for [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
that indexes every image in ComfyUI's `output/` directory and lets you browse
them with their **positive/negative prompt**, **resolution**, **generation
parameters**, **full-text search**, **tags** and **favorites**.

Generated images are indexed incrementally into a local SQLite database with an
FTS5 full-text index, so browsing and searching stay fast even with thousands
of files.

## Features

- **Browse** all generated images (PNG/JPEG/WebP) from `output/` in an infinite-
  scroll grid, with on-the-fly cached thumbnails.
- **Read prompts**: positive/negative prompts are extracted directly from the
  ComfyUI graph stored in each image's `prompt`/`workflow` PNG text chunk
  (resolving KSampler → CLIPTextEncode links). A1111-style `parameters` text is
  supported as a fallback.
- **Parameters**: seed, steps, CFG, sampler, scheduler, denoise and model name
  are surfaced as pills.
- **Search** the positive/negative prompt text with SQLite FTS5.
- **Tags**: add/remove arbitrary tags on any image and filter the gallery by tag.
- **Favorites**: star images and filter to favorites only.
- **Incremental indexing**: a background scan compares file mtimes against the
  cache and only re-extracts changed files; deleted files are pruned. A manual
  "Refresh" button forces a reindex.
- **Raw JSON**: the original `prompt`/`workflow` JSON is always available in a
  collapsible panel for debugging.

## Installation

Drop the `comfyui-output-gallery` folder into ComfyUI's
`custom_nodes/` directory and restart ComfyUI. Dependencies (`Pillow`,
`piexif`, `jinja2`, `platformdirs`) are listed in `pyproject.toml`; install
them into ComfyUI's Python environment if your ComfyUI build does not provide
them:

```bash
pip install -r <path-to-comfyui>/custom_nodes/comfyui-output-gallery/pyproject.toml
```

(or `pip install Pillow piexif jinja2 platformdirs`.)

A new **Output Gallery** button appears in ComfyUI's action bar (modern
frontend) or top menu (legacy). Clicking it opens the gallery page in a new tab.

## How it works

```
custom_nodes/comfyui-output-gallery/
├── __init__.py                  # ComfyUI entry point: WEB_DIRECTORY + add_routes()
├── pyproject.toml               # deps + [tool.comfy] registry metadata + pytest cfg
├── ogallery/                    # server-side Python package
│   ├── server.py                # add_routes(): static mounts, /gallery page, on_startup
│   ├── config.py                # output_dir (folder_paths), data/templates/static paths
│   ├── settings_paths.py        # portable vs user-config data dir (DB/thumbs live here)
│   ├── db.py                    # SQLite schema + FTS5 triggers + CRUD
│   ├── graph_parser.py          # KSampler/CLIPTextEncode link resolution → prompt text
│   ├── metadata_extractor.py    # PIL .info["prompt"/"workflow"], .size, A1111 fallback
│   ├── indexer.py               # incremental scan_once() with mtime cache + pruning
│   ├── thumbnails.py            # on-the-fly WEBP thumbnails with disk cache
│   └── routes/gallery_routes.py # /api/gallery/* handlers
├── templates/gallery.html       # Jinja2 shell that loads the SPA bundle
├── static/                      # gallery.js + gallery.css (vanilla ES modules, no build)
├── web/comfyui/menu_extension.js# action-bar button → window.open('/gallery')
└── tests/                       # pytest: graph parser + indexer integration
```

### Data storage

By default the SQLite index (`gallery.sqlite`) and the `thumbs/` cache live in
the platform user-config dir (`%LOCALAPPDATA%/ComfyUI-Output-Gallery` on
Windows, `~/.config/ComfyUI-Output-Gallery` on Linux). To keep everything
portable (e.g. on a USB ComfyUI install), create a `settings.json` next to the
extension with:

```json
{ "use_portable_settings": true }
```

and the data will be written into `comfyui-output-gallery/data/` instead.

### API

All endpoints live under `/api/gallery`:

| Method | Path         | Purpose                                            |
|--------|--------------|----------------------------------------------------|
| GET    | `/images`    | Paginated, filtered, sorted image list             |
| GET    | `/image`     | Full image record (incl. raw prompt/workflow JSON) |
| POST   | `/favorite`  | Toggle favorite                                    |
| GET    | `/tags`      | List all tags with counts                          |
| POST   | `/tag`       | Add a tag to an image                              |
| POST   | `/untag`     | Remove a tag from an image                         |
| POST   | `/reindex`   | Trigger an incremental scan                        |
| GET    | `/stats`     | Index stats (total images, favorites, last scan)   |
| GET    | `/thumb`     | Generate/serve a cached thumbnail (redirects)      |

Images themselves are served directly from ComfyUI's output dir via the
`/gallery_static/` mount; thumbnails via `/gallery_thumbs/`.

## Development

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install Pillow piexif jinja2 platformdirs pytest aiohttp
.venv/Scripts/python.exe -m pytest tests/ -q
```

The test suite writes real PNGs with embedded `prompt`/`parameters` chunks into
a temp `output/` dir, stubs the ComfyUI runtime modules (`server`,
`folder_paths`, `nodes`), and verifies extraction, indexing, search, mtime
caching, pruning and subdirectory scanning end-to-end.

## License

MIT
