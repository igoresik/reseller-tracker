# Logistics Tracker

**A free Windows app for clothing resellers on Vinted, Depop and eBay.** Log what you list, see what you really keep from an offer after platform fees, and track your parcels, all in one window. Your data stays on your PC.

[![Download](https://img.shields.io/github/v/release/igoresik/reseller-tracker?label=download&color=2A4B9B)](https://github.com/igoresik/reseller-tracker/releases/latest)
[![License: MIT](https://img.shields.io/github/license/igoresik/reseller-tracker)](LICENSE)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-1B2338)
![Built with Python and Streamlit](https://img.shields.io/badge/built%20with-Python%20%2B%20Streamlit-1B2338)

![Profit tab: what you keep from a buyer's offer, drawn as a receipt](docs/profit.png)

## What it does

- **Inventory:** every listing with what you paid, the asking price and the margin, across Vinted, Depop and eBay.
- **Profit:** type the buyer's offer and the shipping you pay, and a receipt shows the platform fee and what you keep. Each platform's fees can be edited.
- **Shipping:** each sale from "to pack" to "delivered", with carrier and tracking number. With a free Ship24 key it checks tracking and keeps the parcel's history.
- **eBay:** connect your account to see your active listings, Best Offers and recent orders. Read-only, nothing is changed on eBay.
- **Private:** everything is saved in a SQLite file on your computer. On Windows, the API keys you save are encrypted with your Windows account.

| Inventory | Shipping |
|---|---|
| ![Inventory tab: live listings with what you paid, the asking price and the margin](docs/inventory.png) | ![Shipping tab: parcels with their progress and tracking history](docs/shipping.png) |

The screenshots use made-up listings.

## Download (Windows)

1. Get `LogisticsTracker.exe` from the repository's **Releases** page.
2. Double-click it. The app opens in its own window after a few seconds. Closing the window stops it.

Good to know:

- Windows may show "Windows protected your PC" because the file is not signed. Choose **More info > Run anyway**.
- It needs Microsoft Edge or Google Chrome installed; the window is drawn by one of them.
- Your data is kept in `%APPDATA%\LogisticsTracker\tracker.db`, so replacing the exe with a newer one keeps it.

## Run from source

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\streamlit run app.py
```

`tracker.db` is created on first run from `schema.sql`.

To build the exe yourself: `powershell -ExecutionPolicy Bypass -File build.ps1`. The result is `dist\LogisticsTracker.exe`.

## Layout

| File | What it does |
|---|---|
| `app.py` | Streamlit UI: Inventory, Profit, Shipping, eBay and Settings tabs |
| `db.py` | SQLite connection and queries |
| `finance.py` | Net profit and margin calculation |
| `launcher.py` | Start-up of the exe: runs the app and opens its window |
| `build.ps1` | Builds the exe with PyInstaller |
| `ship24.py` | Tracking lookup through the Ship24 API |
| `ebay.py` | eBay sign-in, active listings, Best Offers and orders |
| `vault.py` | Encrypts saved keys with Windows DPAPI |
| `schema.sql` | Tables and starting platform fees |
| `.streamlit/config.toml` | Colours and fonts |
| `style.css` | Look of the profit receipt and the parcel progress bar |
| `scripts/live_check.py` | Runs the real Ship24 and eBay calls once, to check the parsing |
| `tests/` | Unit tests (the API tests use fake responses) |

## Flow

1. Add a listing in **Inventory**.
2. In **Profit**, enter the buyer's offer and the shipping you pay. The receipt shows the platform fee, taken from the listing's platform, and what you keep.
3. **Mark sold** moves the listing out of the active list and opens a shipment.
4. Update the shipment's status, carrier and tracking number in **Shipping**.

The seeded platform fees are only starting values. Set your real ones under **Inventory > Platform fees**.

## Connecting your accounts

Everyone uses their own keys. They are typed into the **Settings** tab and saved in `tracker.db` on your computer. Never put a key in the code.

How the app protects them:

- On Windows the saved keys are encrypted with your Windows account (DPAPI). A copy of `tracker.db` on another PC or account cannot read them. On other systems they are plain text.
- Saved keys are never shown again in the page. To change one, type a new one.
- The app only answers to this computer (`127.0.0.1`) and ignores requests that reach it through another site's domain.

Still keep `tracker.db` to yourself: your listings in it are not encrypted, and a program running under your own Windows account can decrypt the keys.

### Ship24 (tracking)

1. Create an account at ship24.com and copy your API key.
2. Paste it in **Settings** and save.
3. In **Shipping**, give a shipment a tracking number, then press **Check tracking**. The status and the latest event are saved; the full event list is shown below.

Each press is one request to Ship24 and counts against your plan.

### eBay

1. Join the eBay Developers Program (free) at developer.ebay.com and create a **Production** keyset.
2. Under **User Tokens > Get a Token from eBay via Your Application**, add an eBay Redirect URL. Set "Your auth accepted URL" to any https page and tick OAuth. The name it gives you is the RuName.
3. Paste the App ID, Cert ID and RuName in **Settings** and save.
4. Press **Sign in to eBay and agree**. Copy the full address of the page you land on (it contains `code=`), paste it back within 5 minutes and press **Connect**.
5. The **eBay** tab now loads your active listings, Best Offers and recent orders. It is read-only: nothing is changed on eBay.

The sign-in lasts about 18 months, then step 4 is needed again.

Vinted and Depop have no API open to the public, so those listings are entered by hand.

## Data

- Money is stored as whole cents (`INTEGER`) and fee rates as basis points (12.8% = 1280), so no amount goes through floating point. Fees round half up to the cent.
- Each sale keeps the fee it was made with, so changing a platform's rates only affects later sales. Sales from before this was added use the rates set when you first update.
- Every tracking event Ship24 reports is saved in `shipment_events`, so a parcel's history survives a restart. Checking again only adds events not seen before.
- A database from v0.1 (euros stored as `REAL`) is converted on first start, all or nothing. The old file is kept next to it as `tracker.before-cents.db`.

## Checking against the real APIs

The unit tests use fake responses. To check the parsing against the real services, save your keys in the app first, then:

```
.venv\Scripts\python scripts\live_check.py ship24 <tracking number>
.venv\Scripts\python scripts\live_check.py ebay
```

It prints the shape of the raw reply (field names and types only) and what the app made of it. Keys are never printed. Add `--exe` to use the keys saved by the exe.

## Tests

```
.venv\Scripts\python -m unittest discover tests
```
