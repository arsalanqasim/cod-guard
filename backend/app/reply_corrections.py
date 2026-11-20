"""Tenant-scoped operator labels linked to retained reply bodies."""
import re
import unicodedata

from records import audit, now, write

LABELS = ("CONFIRM", "DENY", "UNCLEAR", "MODIFICATION")
_ROMAN_URDU = frozenset(
    "haan han nahi nahin nai nhi ji jee bhej bhejna dein karna karain karo mat kal bataunga "
    "mera meri apna aap theek hai hain mein main poora pura sirf baad pehle shukriya agar".split()
)


class CorrectionConflict(ValueError):
    pass


def guess_language(text):
    letters = [char for char in text if char.isalpha()]
    if any("ARABIC" in unicodedata.name(char, "") for char in letters):
        return "ur"
    if set(re.findall(r"[a-z]+", text.casefold())) & _ROMAN_URDU:
        return "roman_ur"
    return "en" if any("LATIN" in unicodedata.name(char, "") for char in letters) else "other"


def record(db, tenant_id, actor, message, label, revision):
    language = guess_language(message["text"])
    row = db.execute("""INSERT INTO reply_corrections
        (tenant_id,message_id,label,language,decision_revision,at,actor)
        VALUES (?,?,?,?,?,?,?) RETURNING id""",
                     (tenant_id, message["id"], label, language, revision, now(), actor)).fetchone()
    correction_id = row["id"]
    audit(db, tenant_id, actor, "reply_corrected", order_id=message["order_id"],
          reference=str(correction_id))
    return correction_id


def export_page(path, tenant_id, actor, *, after=0, limit=500):
    with write(path) as db:
        rows = db.execute("""SELECT c.id, c.schema_version, c.message_id, m.text, c.label,

            c.language, m.intent AS original_label, c.at
            FROM reply_corrections c JOIN messages m ON m.id=c.message_id AND m.tenant_id=c.tenant_id
            WHERE c.tenant_id=? AND c.id>? AND m.text IS NOT NULL
            ORDER BY c.id LIMIT ?""", (tenant_id, after, limit)).fetchall()
        audit(db, tenant_id, actor, "reply_corrections_export", reference=str(len(rows)))
        return [dict(row) for row in rows]
