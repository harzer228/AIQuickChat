# AI Quick Chat

**[🇷🇺 Русский](README.md)** | **[🇬🇧 English](README.en.md)**

[![CI](https://github.com/harzer228/AIQuickChat/actions/workflows/ci.yml/badge.svg)](https://github.com/harzer228/AIQuickChat/actions/workflows/ci.yml)

A fast **desktop AI assistant for Windows**. Summon it with a global hotkey
(`Ctrl+Space` by default) on top of any application — browser, game, editor,
Explorer. Ask a question, paste an image from the clipboard (`Ctrl+V`) or
attach a file, and get an answer from DeepSeek (via the OpenAI-compatible
RouterAI endpoint) with image analysis through Cloudflare Vision. It can also
**dictate messages by voice locally** (Speech-to-Text on Vosk — audio never
leaves your machine).

```
        Ctrl + Space
             ↓
      ┌─────────────┐
      │   AI Chat   │   ← minimal floating window
      │  Message... │
      └─────────────┘
             │
             ▼
         DeepSeek
             │
             ▼
           Answer
```

```
  Ctrl + V (image)
        ↓
   Image Preview
        ↓
  Cloudflare Vision  ──→ image description
        ↓
      DeepSeek        ──→ final answer
```

## Features

- **Global hotkey** (default `Ctrl+Space`) via the WinAPI `RegisterHotKey` —
  works in any application; pressing it again hides the window. The option
  "Open a new tab on the hotkey" (on by default) creates a fresh tab on every
  summon. A separate **Speech-to-Text shortcut** (default `Ctrl+Shift+Space`)
  opens the chat and starts voice dictation immediately.
- **Speech-to-Text (Vosk)**: fully local speech recognition in a background
  thread — your voice never leaves the computer. The mic button next to the
  send button starts/stops dictation and recognized text lands in the input
  field. Automatic silence stop (1.5 s by default), microphone selection, Vosk
  model path and on/off switch are configured in Settings.
- **Frameless window**: translucent, rounded, always on top.
- **Streaming answers** — text appears progressively; during generation the
  send button turns into a real **Stop** button that actually cancels the
  request while keeping the partial text.
- **Web Search**: a toggle in the chat searches the web for up-to-date
  information, feeds the cleaned context to DeepSeek and shows clickable
  sources in the answer. Providers: Tavily / SearXNG / Serper / Brave **and
  "Local (no API)"** — a keyless local engine (`local_websearch/` module,
  DuckDuckGo → SearXNG → Wikipedia cascade + full-text page fetching).
- **AI Memory**: store personal info or your own prompt in Settings — the
  assistant considers it in every reply (toggleable with a checkbox).
- **Message context menu** (right-click): Copy (a working button), Edit your
  last message (the AI re-answers the edited version), Delete your own message
  (the AI reply is kept) or an AI reply.
- **Paste images** via `Ctrl+V` or the attach button (PNG/JPG/JPEG/WEBP/BMP)
  with a preview and a remove button. Sent pictures are shown in the chat as
  thumbnails.
- **Vision pipeline**: image → Cloudflare Vision
  (`@cf/meta/llama-3.2-11b-vision-instruct`) → description → DeepSeek →
  answer. DeepSeek never receives the image itself. The Meta model license is
  accepted automatically on first use (a `prompt: "agree"` request) — no
  manual action needed.
- **Chat tabs**: `+` creates a new tab, each tab has its own history; tabs are
  closed with the red cross inside the tab and are restored when "Remember
  chat history" is enabled.
- **Attach text files** (`.txt .py .js .html .css .json .md .csv .log`) with a
  size limit.
- **Settings** with connection tests (`Test Connection`) for every API.
- **API keys are stored** in the Windows Credential Manager (with an obfuscated
  fallback copy in config.json).
- **Conversation memory** — the context is kept until the chat is closed.
- **Start with Windows**, **remember chat history**, **close to tray** (the
  window always minimizes to tray — the app keeps running in the background).
- **Hotkeys up to 4 keys** (e.g. `Ctrl+Alt+Shift+Q`).
- **Dark/Light/System theme** + 8 ready palettes (Nord, Dracula, Solarized,
  Rosé Pine, Catppuccin, Tokyo Night, Everforest, Gruvbox) with color swatches
  in Settings; adjustable window opacity.
- **Localization**: English / Русский (detected from Windows by default).
- **Animations**: smooth window open/close (opacity + scale), message
  appearance, Send↔Stop transitions, chat tab and settings page switching.

---

## 1. Install Python

Download and install **Python 3.11+** (3.12/3.13 recommended) from
https://www.python.org/downloads/

Make sure to check **"Add Python to PATH"** during installation.

Verify:

```bash
python --version
```

## 2. Virtual environment

```bash
cd AIQuickChat
python -m venv .venv
```

Activate it (Windows PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

(If PowerShell blocks scripts — run `Set-ExecutionPolicy -ScopeCurrentUser
RemoteSigned` once, or activate from `cmd` with `.\.venv\Scripts\activate.bat`.)

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

Dependencies: `PySide6`, `httpx`, `Pillow`, `pytablericons` (UI icons),
`vosk` + `sounddevice` + `numpy` (local speech recognition). Everything
installs automatically on Python 3.11–3.13. If the `pygame` build (a
`pytablericons` dependency) fails on Python 3.14, install it without
dependencies: `pip install --no-deps pytablericons`.

## 4. Run

```bash
python main.py
```

On first launch the chat window appears in the center of the screen. Toggle it
with `Ctrl+Space`. While the app is running there is a tray icon with a menu
(Show/Hide, New chat, Settings, Exit).

## 5. Where to put the RouterAI API key

Open **Settings** (the `⚙` button in the top-right corner of the chat window,
or the tray menu) → **AI Providers**:

- **API URL** — default `https://routerai.ru/api/v1`
- **API Key** — your RouterAI key
- **Model** — default `deepseek/deepseek-v4-flash-0731`

Press **Test Connection** to verify.

## 6. Cloudflare Account ID

**Settings** → **Vision AI** → the **Cloudflare Account ID** field.

The Account ID is on the Workers & Pages page of the Cloudflare dashboard
(right column, "Account ID").

## 7. Cloudflare API Token

**Settings** → **Vision AI** → the **Cloudflare API Token** field.

Create the token in Cloudflare Dashboard → **My Profile** → **API Tokens** →
**Create Token**. Working with Workers AI models requires the **Workers AI:
Run** permission; a global API key in the `key:...` format also works.

The Vision model (default `@cf/meta/llama-3.2-11b-vision-instruct`) can be
replaced with any other Cloudflare Vision model.

## 8. How the Vision pipeline works

1. The user pastes/attaches an image (a preview appears).
2. On send the image is **base64-encoded** and sent to Cloudflare Workers AI:
   `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}`
   with the body `{"image": "<base64>", "prompt": "..."}`.
3. Cloudflare returns a detailed **text description** of the image.
4. The description (together with the user's question) is passed to
   **DeepSeek** as a plain text message.
5. DeepSeek produces the final answer.

Plain text chat (without an image) does **not** call Cloudflare — no extra
requests are made.

The Cloudflare client code is isolated in `api/vision.py` and easy to swap.

## 8.1. Web Search

In **Settings** → **Web Search**:

- **Enable Web Search** — search on by default (there is also a toggle next to
  the chat input field).
- **Provider** — `Tavily`, `SearXNG`, `Serper (Google)`, `Brave Search`, or
  `Local (no API)`.
- **Search API URL** — the search service endpoint (auto-filled when you pick
  a provider).
- **Search API Key** — stored in the Windows Credential Manager like the other
  keys.
- **Maximum results** (1–20) and **Search timeout** (5–120 s).
- The **Test Connection** button performs a real minimal request and shows
  `✓ Connected successfully` or the actual error reason. The secret key is
  never shown in full — only as `API key: tvly-****abcd`.

### Tavily

The integration uses the current official Tavily API format:
`POST https://api.tavily.com/search` with the `Authorization: Bearer <API key>`
header (the legacy `api_key` body field is NOT used — it caused `HTTP 403`).
API errors are diagnosed from the real response text (`detail.error`); codes:
`401` — auth, `403` — access/limits, `429` — rate limit, `432`/`433` —
plan/PayGo limits, `5xx` — server error.

### Local (no API)

The `local_websearch/` module searches without any API keys: a cascade of
DuckDuckGo HTML → DuckDuckGo Lite → public SearXNG instances → Wikipedia, then
the top found pages are downloaded and their readable text is appended to the
snippets. The module is fully removable — delete the folder and the "Local"
option disappears from Settings.

How a search-enabled request flows:

```text
User
  ↓
DeepSeek decides whether fresh information is needed
  ↓
Web Search (a real HTTP search)
  ↓
Clean results → structured context
  ↓
DeepSeek → answer
  ↓
Clickable Sources are shown with the answer
```

Only real search results are used; on error or empty results the app shows a
message (with the real reason and a masked key) and continues the plain chat
without crashing.

## 9. Changing the hotkey

**Settings** → **Hotkey** → **Change** → press the desired combination (e.g.
`Alt+Space`, `Ctrl+Alt+Q`, `F8`, `Ctrl+Alt+Shift+Q`) → press **Enter** to
confirm → **Save**.

The same section has the **Speech-to-Text shortcut** — a separate global key
that opens the chat and immediately starts dictation (default
`Ctrl+Shift+Space`).

The app checks for conflicts (a combination already taken by the system) and
rejects invalid values (e.g. a single key without modifiers).

## 9.1. Speech-to-Text (dictation)

Speech recognition is fully **local** (Vosk) — audio is never uploaded.

### Setup

1. **Settings** → **Speech-to-Text** → enable **Enable Speech-to-Text**.
2. Download a Vosk model (e.g. `vosk-model-small-ru-0.22` or
   `vosk-model-small-en-us-0.15`) from https://alphacephei.com/vosk/models and
   unpack it anywhere. The app does **not** download the model itself.
3. Point the **Browse...** field to the model folder.
4. Optionally pick a specific **Microphone** from the real Windows devices and
   set the **Silence timeout** (default 1.5 s — recording stops automatically
   when you fall silent).
5. Press **Save**.

### Usage

- The 🎤 mic button **next to the send button** starts/stops dictation.
- While recording, the button becomes a square stop button and a
  `Listening...` status is shown below.
- Recognized text appears in the input field automatically. Send it with the
  usual send button (Enter).
- Dictation also works through the global **Speech-to-Text shortcut** (see
  above) — the window opens and recording starts immediately.
- If the selected microphone disappears from the system, the app
  automatically falls back to the default microphone and warns you in the
  chat.

## 10. Building the `.exe`

The repository ships a ready spec file with all the options (onefile, no
console, icon, bundled `locales/` and Tabler icons):

```bash
pip install pyinstaller
pyinstaller AIQuickChat.spec --noconfirm
```

The binary appears in `dist\AIQuickChat.exe`.

> Note: antivirus may flag a onefile PyInstaller build on first run — a known
> false positive. Add an exclusion or build with `--onedir`.

## 11. Development and tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest            # all tests (offscreen Qt, no network or microphone)
pytest --cov      # with a coverage report
ruff check .      # linter
```

Tests live in `tests/` and are fully offline: the local-search parsers run on
HTML fixtures, the GUI runs under `QT_QPA_PLATFORM=offscreen` with an isolated
`%APPDATA%`. CI (GitHub Actions, `.github/workflows/ci.yml`) runs the linter
and the tests on Python 3.11/3.12 on every push/PR.

Pre-commit hooks (optional): `pre-commit install` (see
`.pre-commit-config.yaml` — ruff, trailing whitespace, format checks).

## Project structure

```
AIQuickChat/
├── main.py                  # entry point, tray, global hotkey
├── config.py                # constants, paths, defaults
├── api/
│   ├── deepseek.py          # DeepSeek / RouterAI client (streaming)
│   ├── vision.py            # Cloudflare Workers AI Vision client
│   ├── web_search.py        # web search (Tavily/SearXNG/Serper/Brave/Local) + context
│   └── errors.py            # shared API error class
├── local_websearch/         # keyless local search (removable module)
│   ├── backends.py          #   DuckDuckGo HTML/Lite, SearXNG, Wikipedia
│   ├── fetcher.py           #   page fetching + text extraction
│   └── engine.py            #   source cascade + cache
├── stt/
│   └── engine.py            # local speech recognition (Vosk + sounddevice)
├── ui/
│   ├── chat_window.py       # main floating chat window
│   ├── settings_window.py   # settings window (General / API / Speech-to-Text)
│   ├── icons.py             # unified Tabler Icons helper (create_icon / IconButton)
│   └── widgets.py           # themes (10 palettes), bubbles, markdown, animations
├── utils/
│   ├── config_manager.py    # settings storage + Credential Manager
│   ├── hotkey.py            # global hotkey (RegisterHotKey)
│   └── i18n.py              # localization (t / set_language / detect_system_language)
├── locales/
│   ├── en.json              # English UI strings
│   └── ru.json              # Russian UI strings
├── tests/                   # pytest tests (offline, offscreen Qt)
├── .github/                 # CI (GitHub Actions) + Dependabot
├── AIQuickChat.spec         # PyInstaller spec (onefile, with locales)
├── requirements.txt         # runtime dependencies
├── requirements-dev.txt     # dev/CI dependencies (pytest, ruff, pyinstaller...)
├── LICENSE                  # MIT
└── README.md
```

## Application settings

- **Theme**: Dark / Light / System + 8 palettes.
- **Window opacity**: 60–100%.
- **Show animations**: smooth window appearance.
- **Start with Windows**: autostart via the registry
  (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`) — no admin rights.
- **Remember chat history**: conversations are restored on the next launch.
- **Open a new tab on the hotkey**: every summon opens a fresh tab.
- **Close to tray**: the cross hides the window to tray (otherwise exits).
- **AI Memory**: personal info / custom prompt applied to every answer.
- **Speech-to-Text**: enable/disable recognition, microphone picker, silence
  timeout (0.5–5.0 s), local Vosk model path with a folder picker.

## Security

- Keys are **never hardcoded**: they live in the Windows Credential Manager.
- Data is sent **only** to the APIs you configure yourself (RouterAI /
  OpenAI-compatible and Cloudflare AI).
- No telemetry, ads or hidden network requests.
- The local search (`local_websearch/`) only queries free public search sites
  and Wikipedia; delete the folder and the "Local" option vanishes from
  Settings.

## License

The project is distributed under the [MIT license](LICENSE).
