import json
import os
from datetime import datetime, timezone

CASES_DIR = "database/cases"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _case_path(case_name: str) -> str:
    filename = case_name.strip().replace(" ", "_").lower()
    return os.path.join(CASES_DIR, f"{filename}.json")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _touch(case: dict) -> dict:
    """Update the updated_at field."""
    case["updated_at"] = _now()
    return case


# ─── Public interface ─────────────────────────────────────────────────────────

def create_case(case_name: str) -> dict:
    """Create and persist a new case. Returns the case dict."""
    os.makedirs(CASES_DIR, exist_ok=True)

    now = _now()
    case_data = {
        "case_name":     case_name,
        "created_at":   now,
        "updated_at":   now,
        "wallets":      [],
        "notes":        [],
        "tags":         [],
        "risk_findings": [],
    }

    with open(_case_path(case_name), "w") as f:
        json.dump(case_data, f, indent=4)

    return case_data


def load_case(case_name: str) -> dict | None:
    """Return the case dict or None if it doesn't exist."""
    path = _case_path(case_name)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def save_case(case_name: str, data: dict) -> None:
    """Persist a case dict to disk."""
    _touch(data)
    with open(_case_path(case_name), "w") as f:
        json.dump(data, f, indent=4)


def list_cases() -> list[dict]:
    """
    Return a summary list of all cases:
      [ { case_name, created_at, updated_at, wallet_count, note_count } ]
    Sorted newest-first by updated_at.
    """
    if not os.path.isdir(CASES_DIR):
        return []

    summaries: list[dict] = []
    for filename in os.listdir(CASES_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(CASES_DIR, filename)
        try:
            with open(path, "r") as f:
                case = json.load(f)
            summaries.append({
                "case_name":    case.get("case_name", filename[:-5]),
                "created_at":  case.get("created_at"),
                "updated_at":  case.get("updated_at"),
                "wallet_count": len(case.get("wallets", [])),
                "note_count":   len(case.get("notes", [])),
            })
        except (json.JSONDecodeError, OSError):
            continue

    summaries.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return summaries


def add_wallet_to_case(case_name: str, wallet: str) -> bool:
    """
    Add a wallet address to a case (no duplicates).
    Returns False if the case doesn't exist.
    """
    case = load_case(case_name)
    if not case:
        return False

    if wallet not in case["wallets"]:
        case["wallets"].append(wallet)

    save_case(case_name, case)
    return True


def add_note_to_case(case_name: str, text: str) -> bool:
    """
    Append a timestamped note to a case.
    Returns False if the case doesn't exist.
    """
    case = load_case(case_name)
    if not case:
        return False

    case["notes"].append({
        "text":       text.strip(),
        "created_at": _now(),
    })

    save_case(case_name, case)
    return True


def delete_case(case_name: str) -> bool:
    """
    Delete a case file from disk.
    Returns False if it didn't exist.
    """
    path = _case_path(case_name)
    if not os.path.exists(path):
        return False
    os.remove(path)
    return True
