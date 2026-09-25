# Comment Absorber — Real-Time Facebook Comment Collector & Web Studio

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0%2B-green.svg)](https://palletsprojects.com/p/flask/)
[![Selenium](https://img.shields.io/badge/selenium-4.20%2B-orange.svg)](https://www.selenium.dev/)
[![Tests](https://img.shields.io/badge/tests-46%20passed-brightgreen.svg)]()
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Comment Absorber** is a real-time Facebook comment collection and analysis studio. It absorbs comments from any Facebook post, reel, or video directly into a live web dashboard and exports them into cleanly formatted Excel (`.xlsx`) and CSV spreadsheets.

---

## Key Features

- 🌐 **Real-Time Live Streaming (SSE):** Discovered comments stream directly into the browser in milliseconds with real-time throughput metrics.
- 🎯 **High-Accuracy Comment Absorption:**
  - **Automatic "All Comments" Filter Switching:** Automatically detects and switches Facebook's hidden "Most relevant" (*"Pinakaugnay"*) dropdown to "All comments" so no comments are filtered out.
  - **Un-capped Nested Reply Expansion:** Batch-expands all nested reply chains (*"View 1 reply"*, *"mga tugon"*, *"View more comments"*) without click limits.
  - **Inline Text Un-truncation:** Clicks all inline *"... See more"* / *"Tingnan pa"* buttons inside comments to capture 100% complete message bodies.
  - **Smart Deduplication:** Utilizes unique Facebook comment IDs and exact timestamp-message hashing so identical short comments (e.g. multiple distinct users saying *"Interested"* or *"Mine"*) are never dropped.
- 🔑 **Zero-Lag Facebook Session Persistence:**
  - Safely maintains your Facebook login in a persistent local profile directory (`browser_profile/`).
  - Auto-detects login sessions directly via SQLite database checks in under 0.001 seconds without opening unnecessary browser windows.
  - Automatically notifies the web dashboard when login is complete and refocuses the application.
- 🖥️ **High-Visibility Modern UI:**
  - High-contrast, large-format search bar with instant client-side filtering by author or keyword.
  - Clean responsive typography across desktop, laptop, tablet, and mobile displays.
  - Real-time KPI counters: Total Comments, Ingestion Speed (/sec), Elapsed Timer, and Unique Commenters.
  - Live "Currently Collected Comment" spotlight panel.
- 📊 **Compliant Excel & CSV Exports:**
  - Generates spreadsheets strictly adhering to the standard three-column layout:
    - **User**
    - **Comment**
    - **Date** (`YYYY-MM-DD HH:MM:SS`)
  - Features frozen headers, auto-fit column widths, text wrapping, and alternating row styling.
- 📋 **Universal Client-Side Paste Mode:**
  - Allows manual pasting of copied Facebook comments for instant offline parsing and Excel generation without requiring a browser driver.

---

## Deployment & Usage Options

### Option A: 🌐 100% Public Website (GitHub Pages — No PC Server Needed!)
You can use Comment Absorber directly in your mobile phone or desktop browser anywhere in the world:
👉 **[Open Live Web App](https://markanthonyalgones03.github.io)**

- **No installation or local PC server required**: Runs directly in Safari, Chrome, Edge, and Android/iOS.
- **Direct Meta Graph API Support**: Enter your Meta access token in Settings for direct 24/7 cloud extraction.
- **Instant Excel Spreadsheet Exports**: Download `.xlsx` spreadsheets (with commenter names or without commenter names) directly to your device.
- **Demo Mode**: Test real-time streaming, sorting, and Excel exports anytime with one click.

---

### Option B: ☁️ Free 24/7 Cloud Scraper Deployment (Render.com)
To run the automated headless browser scraper 24/7 in the cloud without keeping your personal computer turned on:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

1. Log in to **[Render.com](https://render.com)** (100% free account).
2. Click **New +** -> **Web Service** -> Connect your GitHub repository `fb_comment_absorber_V1`.
3. Render automatically reads `render.yaml` and deploys your 24/7 cloud server with a permanent HTTPS URL (e.g. `https://fb-comment-absorber.onrender.com`).
4. In your GitHub Pages settings, paste your permanent Render URL once—it stays online 24/7 forever!

---

### Option C: 💻 Local Desktop Studio (PC / Laptop)
For running completely offline or using your local personal Facebook login session:

```bash
git clone https://github.com/markanthonyalgones03/fb_comment_absorber_V1.git
cd fb_comment_absorber_V1
pip install -r requirements.txt
python run_web.py
```
*Or simply double-click `START_WEB_VERSION.bat`.*

Navigate to: `http://localhost:5000`

---

## How to Collect Comments

1. **Log in to Facebook (First Time Only):**
   - Click the **Log In to Facebook** button in the header or prompt banner.
   - Enter your Facebook credentials in the browser window.
   - Once logged in, Comment Absorber automatically saves your session to `browser_profile/` and closes the login popup.
2. **Paste Post URL:**
   - Paste any Facebook post, reel, or video link into the top URL bar:
     - Post: `https://www.facebook.com/page/posts/123456789/`
     - Reel: `https://www.facebook.com/reel/123456789/`
     - Share link: `https://www.facebook.com/share/p/123456789/`
3. **Start Collection:**
   - Click **Start Collecting Real Comments**.
   - Watch the comments stream into the dashboard live!
4. **Export Data:**
   - Click **Export Excel (.xlsx)** or **Export CSV** to download the finalized spreadsheet.

---

## Privacy & Security

> [!IMPORTANT]
> **Your Facebook credentials and session cookies are 100% private and NEVER leave your computer.**
> - All session data is stored exclusively in your local `browser_profile/` folder on your machine.
> - `browser_profile/` is strictly registered in [.gitignore](file:///.gitignore) and is never tracked, committed, or pushed to GitHub.
> - The application communicates only with Facebook directly via your local browser.

---

## Project Structure

```
Comment Absorber/
│
├── web/                           # Web Studio Application
│   ├── app_web.py                 # Flask Server & SSE Streaming API
│   ├── web_collector.py           # Real Browser Facebook Collector & DOM Extractor
│   ├── templates/                 # UI Templates
│   │   └── index.html             # Responsive Dashboard Interface
│   ├── static/                    # Icons and Static Web Assets
│   └── test_web.py                # Web Engine Unit Tests
│
├── app/                           # Core Desktop Engine & Utilities
│   ├── api_client.py              # Meta Graph API Client
│   ├── collector.py               # Background Collection Engine
│   ├── exporter.py                # Excel (.xlsx) & CSV Generator
│   ├── url_parser.py              # Facebook URL Format Parser
│   └── gui.py                     # Desktop GUI (Tkinter)
│
├── tests/                         # Full Automated Test Suite (47 Tests)
│   ├── test_api_client.py
│   ├── test_collector.py
│   ├── test_exporter.py
│   └── test_url_parser.py
│
├── requirements.txt               # Project Python Dependencies
├── .gitignore                     # Git Exclusion Rules (Protects Credentials)
├── run_web.py                     # Web Studio Entry Point
├── run.py                         # Desktop App Entry Point
└── START_WEB_VERSION.bat          # One-Click Windows Launcher
```

---

## Universal Dual-Engine Architecture

Comment Absorber is a **cloud-hosted public comment absorption web application**:

1. **Public Post Engine (No Login Required):**
   - Extracts public comments from any Facebook Post, Reel, Video, or Page.
   - Powered by the server-side Apify Actor API (`apify/facebook-comments-scraper`).
   - Visitors can simply paste any public post or reel link and click **Absorb Comments**.

2. **Official Meta Graph API (Optional Facebook Login):**
   - For users who want to query their own personal posts or managed Facebook Pages via official Meta OAuth 2.0.
   - Per-user session isolation: tokens stored exclusively in private server-side session memory.

### Environment Variables for Render.com:
| Variable | Required? | Description |
| :--- | :---: | :--- |
| `APIFY_API_TOKEN` | **Recommended** | Free API token from [apify.com](https://apify.com) ($5 free monthly credit). Enables public post/reel absorption without Facebook login. |
| `META_APP_ID` | Optional | Your Meta App ID from [developers.facebook.com](https://developers.facebook.com) (for Facebook Login). |
| `META_APP_SECRET` | Optional | Your Meta App Secret (App Settings ➔ Basic). |
| `META_REDIRECT_URI` | Optional | e.g. `https://fb-comment-absorber-v1.onrender.com/auth/facebook/callback` |
| `SESSION_SECRET` | Auto-Generated | Random secret key for signing session cookies |
| `PORT` | Pre-configured | `10000` |

---

## Running Automated Tests

Run the full automated test suite (54 tests):
```bash
python -m pytest
```

All 54 test cases across URL parsing, multi-user session isolation, public post engine routing, OAuth state handling, Excel formatting, and API error handling pass with 100% compliance.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
