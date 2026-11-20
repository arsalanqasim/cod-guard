"""Exercise and time each exhibition step through the real Streamlit dashboard."""
import json
import os
from pathlib import Path
from time import perf_counter, sleep
from unittest.mock import patch

from run_demo import ROOT, demo_session
from streamlit.testing.v1 import AppTest
import service


def dashboard():
    return AppTest.from_file(str(ROOT / "frontend/dashboard.py"), default_timeout=120)


def run():
    timings = {}

    def measure(label, action):
        start = perf_counter()
        action()
        timings[label] = round(perf_counter() - start, 3)
        print(f"{label}: {timings[label]:.3f}s", flush=True)

    with demo_session() as env, patch.dict(os.environ, env), \
         patch.object(service, "STATE_PATH", Path(env["COD_GUARD_DATA_DIR"]) / "state.json"), \
         patch.object(service, "MODEL_PATH", Path(env["COD_GUARD_MODEL_PATH"])):
        app = dashboard()
        measure("Cold dashboard startup", lambda: app.run())
        orders, scores, total = service.order_page()
        assert total == 80 and not app.exception
        advisory_keys = {"prepaid_offer", "courier_recommendation", "address_quality"}
        assert not any(advisory_keys & assessment.keys() for assessment in scores)
        red = next(score["order_id"] for score in scores if score["zone"] == "RED")
        green = next(score["order_id"] for score in scores if score["zone"] == "GREEN")
        order = {row["order_id"]: row for row in orders}
        measure("RED queue filter and explanation",
                lambda: (app.multiselect[0].set_value(["RED"]).run(),
                         app.selectbox(key="detail_order").set_value(red).run()))

        def reply(oid, text, decision, review=False):
            app.selectbox(key="verify_order").set_value(oid).run()
            app.chat_input(key=f"reply_{oid}").set_value(text).run()
            assessment = service.assess_order(order[oid])
            assert not app.exception and assessment["decision"] == decision
            assert assessment["needs_review"] == review

        measure("Roman Urdu confirmation", lambda: reply(red, "Ji theek hai, bhej dein", "SHIP"))
        measure("Urdu-script denial", lambda: reply(green, "جی نہیں", "HOLD_CANCEL"))
        measure("Unclear preserves the denial", lambda: reply(green, "Kal bataunga", "HOLD_CANCEL", True))

        def fallback():
            import verification
            with patch.object(verification, "transcribe_voice_note",
                              return_value={"ok": False, "reason": "Rehearsal: voice unavailable"}):
                app.radio(key="voice_source").set_value("Bundled Urdu sample").run()
                app.button(key="transcribe_voice").click().run()
                assert any("voice unavailable" in message.value for message in app.error)
            reply(green, "جی نہیں", "HOLD_CANCEL")

        measure("Unavailable voice to typed fallback", fallback)

        def voice():
            revision = service.verification_revision("demo", green)
            app.button(key="transcribe_voice").click().run()
            result = app.session_state["voice_result"]["result"]
            assert result["ok"] and result["text"]
            assert verification_intent(result) == "UNCLEAR"
            assert service.verification_revision("demo", green) == revision

        measure("Cached real Urdu sample (optional)", voice)

        def metrics():
            app.run()
            labels = {item.label: item.value for item in app.metric}
            assert labels["False-positive rate"] == "16.5%"
            assert labels["False-negative rate"] == "59.2%"

        measure("Show baseline metrics", metrics)
        before = service.latest_evaluation()

        def outcome():
            app.selectbox(key="outcome_order").set_value(green).run()
            app.radio(key="outcome_value").set_value("refused").run()
            app.button(key="save_outcome").click().run()
            assert service.learning_status()["pending"] == 1

        measure("Save outcome", outcome)

        def retrain():
            app.button(key="retrain").click().run()
            deadline = perf_counter() + 90
            while perf_counter() < deadline and service.learning_status()["pending"]:
                sleep(0.25)
                app.run()
            after = service.latest_evaluation()
            assert not app.exception and after["version"] > before["version"]
            assert after["split"]["feedback"] == 1
            assert after["split"]["test"] == before["split"]["test"]
            assert service.learning_status()["pending"] == 0

        measure("Retrain and verify published version", retrain)
        old_state = service.STATE_PATH.with_suffix(".sqlite3")
        assert old_state.is_file()

    def reset():
        assert not old_state.exists()
        with demo_session() as env, patch.dict(os.environ, env), \
             patch.object(service, "STATE_PATH", Path(env["COD_GUARD_DATA_DIR"]) / "state.json"), \
             patch.object(service, "MODEL_PATH", Path(env["COD_GUARD_MODEL_PATH"])):
            assert not dashboard().run().exception
            assert service.order_page()[2] == 80
            assert service.conversation(green) == []
            assert service.learning_status()["recorded"] == 0
            assert service.latest_evaluation()["model_id"] == before["model_id"]

    measure("Fresh-session reset", reset)
    print(json.dumps(timings))


def verification_intent(result):
    from verification import parse_reply
    return "UNCLEAR" if result.get("warning") else parse_reply(result["text"])


if __name__ == "__main__":
    run()
