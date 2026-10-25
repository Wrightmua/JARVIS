"""Gmail + Google Calendar. Only registered once you've authorised with:

    .venv\\Scripts\\python -m jarvis.tools.google

which needs data/google_credentials.json (an OAuth "Desktop app" client — see README).
JARVIS can read mail and create drafts; it never sends email itself."""
import base64
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from ..config import DATA_DIR
from . import integer, string, tool

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/gmail.compose",
          "https://www.googleapis.com/auth/calendar.readonly"]
CREDENTIALS = DATA_DIR / "google_credentials.json"
TOKEN = DATA_DIR / "google_token.json"


def _service(api: str, version: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())
    return build(api, version, credentials=creds, cache_discovery=False)


def check_email(query: str = "is:unread in:inbox", max_results: int = 5) -> str:
    gmail = _service("gmail", "v1")
    ids = gmail.users().messages().list(userId="me", q=query, maxResults=min(int(max_results), 15)).execute()
    out = []
    for m in ids.get("messages", []):
        msg = gmail.users().messages().get(userId="me", id=m["id"], format="metadata",
                                           metadataHeaders=["From", "Subject", "Date"]).execute()
        h = {x["name"]: x["value"] for x in msg["payload"]["headers"]}
        out.append(f"- From {h.get('From', '?')} | {h.get('Subject', '(no subject)')} | {msg.get('snippet', '')[:150]}")
    return "\n".join(out) or "No matching emails."


def draft_email(to: str, subject: str, body: str) -> str:
    msg = MIMEText(body)
    msg["to"], msg["subject"] = to, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    _service("gmail", "v1").users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return f"Draft to {to} saved in Gmail Drafts (not sent)."


def calendar(days: int = 1) -> str:
    now = datetime.now(timezone.utc)
    events = _service("calendar", "v3").events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=(now + timedelta(days=int(days))).isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=20).execute().get("items", [])
    out = []
    for e in events:
        start = e["start"].get("dateTime", e["start"].get("date"))
        when = datetime.fromisoformat(start).strftime("%a %d %b %I:%M %p") if "T" in start else f"{start} (all day)"
        out.append(f"- {when}: {e.get('summary', '(untitled)')}")
    return "\n".join(out) or "Nothing on the calendar."


if TOKEN.exists():
    tool("List Gmail messages (unread inbox by default). query uses Gmail search syntax.",
         {"query": string("Gmail search, e.g. 'is:unread', 'from:bob'"),
          "max_results": integer("How many, default 5")}, required=[])(check_email)
    tool("Create a Gmail DRAFT (never sends). The user reviews and sends it themselves.",
         {"to": string("Recipient email"), "subject": string("Subject"), "body": string("Plain text body")},
         confirm=lambda a: f"Create Gmail draft to {a.get('to')} — \"{a.get('subject')}\"\n\n{a.get('body', '')}")(draft_email)
    tool("Upcoming Google Calendar events.", {"days": integer("How many days ahead, default 1")},
         required=[])(calendar)


if __name__ == "__main__":
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CREDENTIALS.exists():
        raise SystemExit(f"Put your OAuth client file at {CREDENTIALS} first (see README).")
    creds = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES).run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    print("Google connected. Restart JARVIS.")
