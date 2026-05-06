# MonsterMail-Sorter
Advanced email intelligence sorter built for MX fingerprinting, SMTP validation, provider detection, and bulk email classification.

t.me/officialmonsterz

# MONSTERMAIL SORTER v3.3

Advanced Email Provider Sorter using:

- MX Record Intelligence
- DNS Resolution
- SMTP Verification
- Multi-threaded Processing
- Provider Fingerprinting

Built by officialmonsterz

---

# Features

- Bulk email processing
- High-speed threading
- MX record extraction
- Google DNS fallback support
- SMTP handshake verification
- Provider classification
- Live terminal dashboard
- DNS debug mode
- CSV export
- TXT provider sorting
- Office365 detection
- Google Workspace detection
- Yahoo/Outlook/iCloud/Zoho support
- Custom MX classification

---

# Supported Providers

- Google Workspace
- Office365
- Yahoo
- Outlook / Hotmail
- ProtonMail
- Tutanota
- iCloud
- Zoho
- Rackspace
- GoDaddy
- Mimecast
- Proofpoint
- AWS SES
- Custom MX Domains

---

# Installation

## Clone Repository

```bash
git clone https://github.com/YOURNAME/MonsterMail-Sorter.git
cd MonsterMail-Sorter
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Usage

Run the tool:

```bash
python monstermail.py
```

---

# Input Format

Create a `.txt` file containing emails:

```txt
example@gmail.com
admin@company.com
test@yahoo.com
```

---

# Output

The tool generates:

```txt
google_workspace.txt
office365.txt
hotmail.txt
custom_mx.txt
inactive.txt
REPORT.txt
full_results.csv
```

---

# SMTP Verification

SMTP verification is OFF by default because:

- Many ISPs block port 25
- Some mail servers reject verification attempts
- DNS classification is faster and more reliable

You can enable SMTP verification inside settings.

---

# DNS Resolution

MonsterMail uses:

- Google DNS
- Cloudflare DNS
- Socket fallback resolution
- nslookup fallback support

This improves MX detection reliability on Windows systems.

---

# Screenshots

Add screenshots here later.

---

# Disclaimer

This tool is for:

- Email infrastructure analysis
- Mail server research
- Educational purposes
- System administration

Users are responsible for complying with all local laws and regulations.

---

# Author

officialmonsterz

GitHub:
https://github.com/officialmonsterz
