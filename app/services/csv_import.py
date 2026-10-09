import csv
import io

REQUIRED_COLUMNS = {"name", "email"}


class CSVError(ValueError):
    pass


def _decode(raw: bytes) -> str:
    # utf-8-sig strips the BOM Excel adds; plain "Save as CSV" in Excel on
    # Windows writes cp1252 instead, so fall back to that.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            raise CSVError("could not read file, please save it as UTF-8 CSV")


def parse_recipients_csv(raw: bytes) -> list[dict]:
    """Turn an uploaded CSV into the same list of dicts the JSON endpoint takes.

    Only checks the file's shape (encoding, header). Row contents go through
    the normal per-recipient validation, so the rules stay in one place.
    """
    reader = csv.DictReader(io.StringIO(_decode(raw)))
    if not reader.fieldnames:
        raise CSVError("CSV file is empty")

    # match headers case-insensitively: "Name", " EMAIL " etc. are fine
    columns = {h.strip().lower(): h for h in reader.fieldnames if h}
    missing = REQUIRED_COLUMNS - columns.keys()
    if missing:
        raise CSVError(f"CSV is missing column(s): {', '.join(sorted(missing))}")

    recipients = []
    for row in reader:
        values = {key: row.get(columns[key]) for key in REQUIRED_COLUMNS}
        # spreadsheets often export trailing ",," lines - skip those
        if not any((v or "").strip() for v in values.values()):
            continue
        recipients.append(values)
    return recipients
