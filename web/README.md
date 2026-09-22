# ⚡ Comment Absorber Web

> **High-Performance Real-Time Facebook Comments Extractor & Exporter**  
> Stream live comments from any Facebook post, reel, or video directly into a clean, modern web dashboard. Export structured spreadsheets with one click.

---

## 🌟 Key Features

- **🚀 Blazing Fast Ingestion**: In-browser V8 JavaScript batch extraction ingests 30–100+ comments per second with sub-second latency.
- **📱 Fully Responsive Design**: Seamlessly adapts to any screen size—from ultra-wide desktop monitors to any brand of smartphone (Apple iPhone, Samsung Galaxy, Google Pixel, Xiaomi, OnePlus).
- **🔴 Real-Time Live Feed**: Server-Sent Events (SSE) stream comments directly to your browser as they are absorbed from Facebook.
- **✨ Spotlight Card**: Dedicated live card displaying the latest absorbed comment in real time.
- **📊 Live KPI Dashboard**: Live metrics tracking Total Comments, Ingestion Speed (`/sec`), Elapsed Duration, and Unique Commenters.
- **🔄 "Collect Another Comment"**: Instant reset button that clears previous comments and focuses the URL bar for pasting a new link.
- **🏷️ Collection Status System**:
  - 🔵 **`Ongoing`**: Real-time extraction actively running.
  - 🟢 **`Done`**: Collection finished successfully.
  - 🟡 **`Stopped`**: Collection stopped by user.
  - ⚪ **`Ready`**: Idle and ready for a new post link.
- **🔐 Automatic Facebook Login Prompt**: Detects if an active Facebook session is required and guides the user to log in safely in an authenticated browser window.
- **📥 Excel & CSV Exports**: Instant download of formatted `.xlsx` and `.csv` files containing structured `User`, `Comment`, and `Date` columns.
- **🔍 Instant Live Search**: Filter through hundreds of comments instantly by user name or keyword.

---

## 📋 Prerequisites

1. **Python 3.9+** installed on your system.
2. **Google Chrome** (or Microsoft Edge) installed.

---

## 🚀 Quick Start Guide

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/comment-absorber.git
cd comment-absorber
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Start the Web Application
```bash
python app_web.py
```

### 4. Open in Your Browser
Open your browser and navigate to:
```
http://127.0.0.1:5000
```

---

## 📱 Accessing from Mobile Phones

You can access and operate Comment Absorber directly from your mobile phone:

### Method A: Same Local Wi-Fi Network
1. Run `python app_web.py` on your computer.
2. Note your local IP address shown in the terminal (e.g. `http://192.168.1.100:5000`).
3. Open Safari, Chrome, or Samsung Internet on your phone and navigate to that address.

### Method B: Free Public Link (Cloudflare Tunnel / Ngrok)
To allow access from anywhere in the world:
```bash
# Using Cloudflare Tunnel
cloudflared tunnel --url http://127.0.0.1:5000

# Or using Ngrok
ngrok http 5000
```
Share the generated HTTPS URL with anyone—they can collect and view comments on any smartphone!

---

## 💡 How to Use

1. **Check Facebook Login**:
   - The top header will display `Facebook: Logged In ✓`.
   - If not logged in, click **Log In to Facebook** in the prompt banner to sign in once.
2. **Paste Post Link**:
   - Copy any Facebook post, reel, or video link (e.g., `https://www.facebook.com/reel/123456789/`).
   - Paste it into the top input bar.
3. **Start Collecting**:
   - Click **Start Collecting Real Comments**.
   - Watch comments stream into the dashboard live!
4. **Export**:
   - Click **Export Excel (.xlsx)** or **Export CSV** to save your report.
5. **Collect Next Post**:
   - Click **Collect Another Comment** to immediately clear and paste another link.

---

## 🗂️ Project Structure

```
comment-absorber/
├── app_web.py              # Flask Web Server & SSE Streaming API
├── web_collector.py        # Optimized Facebook Scraper & Exporter Engine
├── test_web.py             # Automated Unit & Integration Test Suite
├── requirements.txt        # Python Dependencies
├── .gitignore              # Git Ignore Configuration
├── README.md               # Documentation & Setup Guide
├── templates/
│   └── index.html          # Clean, Responsive Single-Page Dashboard
└── static/
    ├── css/
    │   └── style.css       # Modern High-Contrast Responsive CSS
    └── js/
        └── app.js          # Reactive Client Logic & SSE Connection
```

---

## 🧪 Running Automated Tests

Run the included automated verification suite:
```bash
python -m unittest -v test_web.py
```

---

## 📤 Publishing to GitHub

```bash
# Initialize git repository
git init

# Add all project files
git add .

# Commit changes
git commit -m "Initial release: Comment Absorber Web"

# Link to your GitHub repository
git branch -M main
git remote add origin https://github.com/your-username/comment-absorber.git

# Push to GitHub
git push -u origin main
```

---

## ⚖️ Disclaimer

This tool is designed for research, educational, and business productivity workflows. Ensure compliance with Facebook's Terms of Service and data privacy regulations when collecting public comments.
