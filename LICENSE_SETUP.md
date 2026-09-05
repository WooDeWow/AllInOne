# License setup for sellers (Google Sheets + Apps Script)

AllInOne uses a lightweight “check back” license gate:

- Customers enter a key in the **License** tab.
- The app calls **your Apps Script Web App URL** (HTTPS) with the key (+ a non-PII machine fingerprint hash).
- Your script looks up a **private Google Sheet** and returns JSON like  
  `{ "valid": true, "email": "...", "expires": "2027-01-01" or null, "status": "active" }`.

This is **not bank-grade DRM**. A determined pirate can patch a local Python app. Sheets + Apps Script is free, private enough for most indie sales, and easy to revoke keys.

---

## Your license sheet

**Spreadsheet ID (already created):**

`1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0`

Open it (owner / editor only — keep the sheet **private**):

https://docs.google.com/spreadsheets/d/1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0/edit

> **Important:** Do **not** put that `/edit` spreadsheet URL into the app as `license_url`.  
> The sheet must stay private. The app must call only the **Apps Script Web App** URL you deploy below.  
> Sharing the editable sheet link would expose customer emails and keys.

### Columns (row 1 headers)

| LicenseKey | CustomerEmail | Status | Expires | Notes | Created |
|------------|---------------|--------|---------|-------|---------|
| AIO-XXXX-XXXX-XXXX | buyer@example.com | active | 2027-01-01 | Gumroad #123 | 2026-09-05 |

- **Status:** `active` or `revoked` (anything else → treat as invalid).
- **Expires:** `YYYY-MM-DD` or leave blank / `null` for no expiry.

---

## 1) Attach Apps Script to the sheet (recommended)

1. Open the sheet above.
2. **Extensions → Apps Script**.
3. Delete any stub code; paste the script in the section below.
4. Save the project (e.g. name it `AllInOne License API`).

Because the script is **container-bound** to this spreadsheet, `SpreadsheetApp.getActiveSpreadsheet()` works.  
(If you ever move to a standalone script, switch to `openById('1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0')` — both are shown in the source.)

## 2) Deploy as Web App

1. In Apps Script: **Deploy → New deployment**.
2. Type: **Web app**.
3. Description: e.g. `AllInOne license v1`.
4. **Execute as:** Me (your Google account).
5. **Who has access:** Anyone  
   (The sheet stays private; only your script runs as you and returns a tiny JSON payload.)
6. Deploy → authorize when prompted → **copy the Web App URL**  
   (looks like `https://script.google.com/macros/s/XXXXXXXX/exec`).

That Web App URL is what goes in `config.json` as `license_url` — **not** the spreadsheet `/edit` link.

## 3) Point AllInOne at the Web App

```bash
cp config.example.json config.json
# edit config.json → set "license_url" to your Web App URL
```

Or set env (overrides file):

```bash
export ALLINONE_LICENSE_URL='https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec'
```

`config.json` is gitignored — never commit a live deployment URL if you prefer to keep it out of the repo. `config.example.json` ships with a placeholder only.

## 4) Issue keys

Add a row:

- `LicenseKey`: e.g. `AIO-7K2M-9QWP-4XRH` (random; avoid sequential).
- `CustomerEmail`: buyer email.
- `Status`: `active`.
- `Expires`: optional date, or blank.
- `Notes` / `Created`: optional.

Email the key to the customer. They paste it into AllInOne → License → Activate.

## 5) Revoke

Set **Status** to `revoked`. The next online re-check (about every 24h) will fail; offline grace is at most 7 days after the last successful check.

---

## Apps Script source (paste into the sheet’s script editor)

```javascript
/**
 * AllInOne license lookup — container-bound to the seller's Google Sheet.
 * Deploy as Web App: Execute as Me, Who has access: Anyone.
 *
 * Sheet ID (reference): 1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0
 * Prefer getActiveSpreadsheet() when this script is bound via Extensions → Apps Script.
 */

var SHEET_ID = '1-ucqexWNSVjXSivPqnosI2BNRSaIjwndVj8dVIFnmS0';
var HEADER_ROW = 1;

function doGet(e) {
  return handle_(e);
}

function doPost(e) {
  return handle_(e);
}

function handle_(e) {
  try {
    var params = (e && e.parameter) ? e.parameter : {};
    // Also accept JSON body on POST
    if (e && e.postData && e.postData.contents) {
      try {
        var body = JSON.parse(e.postData.contents);
        if (body && typeof body === 'object') {
          for (var k in body) {
            if (params[k] === undefined) params[k] = body[k];
          }
        }
      } catch (ignore) {}
    }

    var key = String(params.key || params.license || params.licenseKey || '').trim();
    if (!key) {
      return json_({ valid: false, email: null, expires: null, status: 'missing_key' });
    }

    var ss;
    try {
      ss = SpreadsheetApp.getActiveSpreadsheet();
    } catch (errActive) {
      ss = null;
    }
    if (!ss) {
      ss = SpreadsheetApp.openById(SHEET_ID);
    }

    var sheet = ss.getSheets()[0];
    var values = sheet.getDataRange().getValues();
    if (!values || values.length < 2) {
      return json_({ valid: false, email: null, expires: null, status: 'empty' });
    }

    var headers = values[0].map(function (h) {
      return String(h || '').trim().toLowerCase();
    });
    var colKey = indexOfHeader_(headers, ['licensekey', 'license_key', 'key']);
    var colEmail = indexOfHeader_(headers, ['customeremail', 'email', 'customer_email']);
    var colStatus = indexOfHeader_(headers, ['status']);
    var colExpires = indexOfHeader_(headers, ['expires', 'expiry', 'expiration']);

    if (colKey < 0) {
      return json_({ valid: false, email: null, expires: null, status: 'bad_headers' });
    }

    var keyLower = key.toLowerCase();
    for (var r = 1; r < values.length; r++) {
      var row = values[r];
      var rowKey = String(row[colKey] || '').trim();
      if (!rowKey || rowKey.toLowerCase() !== keyLower) continue;

      var status = colStatus >= 0 ? String(row[colStatus] || '').trim().toLowerCase() : 'active';
      if (!status) status = 'active';
      var email = colEmail >= 0 ? String(row[colEmail] || '').trim() : '';
      var expires = colExpires >= 0 ? normalizeExpires_(row[colExpires]) : null;

      if (status === 'revoked') {
        return json_({ valid: false, email: email || null, expires: expires, status: 'revoked' });
      }
      if (status !== 'active') {
        return json_({ valid: false, email: email || null, expires: expires, status: status });
      }
      if (expires && isExpired_(expires)) {
        return json_({ valid: false, email: email || null, expires: expires, status: 'expired' });
      }
      return json_({ valid: true, email: email || null, expires: expires, status: 'active' });
    }

    return json_({ valid: false, email: null, expires: null, status: 'not_found' });
  } catch (err) {
    return json_({ valid: false, email: null, expires: null, status: 'error', error: String(err) });
  }
}

function indexOfHeader_(headers, names) {
  for (var i = 0; i < names.length; i++) {
    var idx = headers.indexOf(names[i]);
    if (idx >= 0) return idx;
  }
  return -1;
}

function normalizeExpires_(value) {
  if (value === null || value === undefined || value === '') return null;
  if (Object.prototype.toString.call(value) === '[object Date]' && !isNaN(value.getTime())) {
    return Utilities.formatDate(value, Session.getScriptTimeZone() || 'UTC', 'yyyy-MM-dd');
  }
  var s = String(value).trim();
  if (!s || s.toLowerCase() === 'null' || s.toLowerCase() === 'never') return null;
  // Already YYYY-MM-DD or ISO-ish
  return s.length >= 10 ? s.substring(0, 10) : s;
}

function isExpired_(expiresStr) {
  try {
    var d = new Date(String(expiresStr).substring(0, 10) + 'T23:59:59Z');
    return d.getTime() < Date.now();
  } catch (e) {
    return false;
  }
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Manual test in the script editor */
function testLookup() {
  var fake = { parameter: { key: 'AIO-TEST-KEY-HERE' } };
  Logger.log(handle_(fake).getContent());
}
```

---

## App-side policy (what customers see)

| State | Access |
|-------|--------|
| **Trial** | Full features for **7 days from first run** **or** **10 uses** (whichever ends first). Stored in `~/.allinone/license.json`. |
| **Licensed** | Full access. Online re-check ~every 24h. Offline grace **7 days** after last successful validation. |
| **Locked** | Compress + Convert disabled until a valid key is activated. |
| **Dev** | `ALLINONE_DEV_UNLOCK=1` bypasses the gate — **for development only**, never production builds. |

---

## Honest caveats

- Not bank-grade DRM; local apps can be patched.
- Apps Script has quotas / rate limits — fine for indie volume; cache checks client-side (already done every 24h).
- Keep the **sheet private**. Only the Web App URL is public-facing.
- After editing the script, create a **New deployment** (or “Manage deployments → Edit → New version”) so customers hit the updated code.
- Never commit real customer keys or a production Web App URL you want to keep out of git (`config.json` is ignored).

## Quick “how you sell”

1. Buyer pays (Gumroad, Stripe, PayPal, …).
2. You add one row to the sheet with a new `AIO-…` key and their email, `Status=active`.
3. You email them the key (+ link to download AllInOne).
4. They activate in the License tab. To refund/ban: set `revoked`.
