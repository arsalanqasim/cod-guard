"""Tenant-scoped labels and advisory predictions linked to retained reply bodies."""
import json
import re
import unicodedata

from records import audit, connect, now, write

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
            c.language, m.intent AS original_label, c.at, (
                SELECT json_group_array(json_object('model', p.model, 'label', p.label, 'confidence', p.confidence))
                FROM reply_shadow_predictions p WHERE p.tenant_id=c.tenant_id AND p.message_id=c.message_id
            ) AS shadow_predictions
            FROM reply_corrections c JOIN messages m ON m.id=c.message_id AND m.tenant_id=c.tenant_id
            WHERE c.tenant_id=? AND c.id>? AND m.text IS NOT NULL
            ORDER BY c.id LIMIT ?""", (tenant_id, after, limit)).fetchall()
        audit(db, tenant_id, actor, "reply_corrections_export", reference=str(len(rows)))
        return [{**dict(row), "shadow_predictions": json.loads(row["shadow_predictions"])} for row in rows]


def run_shadow(path, tenant_id, model, predict, *, limit=500):
    """Only reply text reaches a local predictor. Its output has no decision write path."""
    with connect(path) as db:
        pending = db.execute("""SELECT id,text FROM messages m
            WHERE tenant_id=? AND source IN ('text','voice','whatsapp') AND text IS NOT NULL
            AND decision_revision IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM reply_shadow_predictions p
                WHERE p.tenant_id=m.tenant_id AND p.model=? AND p.message_id=m.id)
            ORDER BY id LIMIT ?""", (tenant_id, model, limit)).fetchall()
    predictions = []
    for row in pending:
        label, confidence = predict(row["text"])
        if label not in LABELS or not 0 <= confidence <= 1:
            raise ValueError("Expected a Round 7 label and confidence in [0, 1]")
        predictions.append((model, label, confidence, now(), tenant_id, row["id"]))
    with write(path) as db:
        saved = db.executemany("""INSERT INTO reply_shadow_predictions
            (tenant_id,message_id,model,label,confidence,at)
            SELECT tenant_id,id,?,?,?,? FROM messages WHERE tenant_id=? AND id=? AND text IS NOT NULL
            ON CONFLICT DO NOTHING""", predictions).rowcount
        if saved:
            audit(db, tenant_id, "local-shadow", "reply_shadow_predictions", reference=f"{model} {saved}")
    return saved


def shadow_agreement(path, tenant_id):
    with connect(path) as db:
        rows = db.execute("""SELECT p.model, COUNT(*) AS predicted, COUNT(c.label) AS labeled,
            SUM(CASE WHEN p.label=c.label THEN 1 ELSE 0 END) AS agreement
            FROM reply_shadow_predictions p LEFT JOIN reply_corrections c ON c.id=(
                SELECT MAX(id) FROM reply_corrections WHERE tenant_id=p.tenant_id AND message_id=p.message_id)
            WHERE p.tenant_id=? GROUP BY p.model ORDER BY p.model""", (tenant_id,)).fetchall()
    return [{**dict(row), "agreement_rate": row["agreement"] / row["labeled"] if row["labeled"] else None}
            for row in rows]
