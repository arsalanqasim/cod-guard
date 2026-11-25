"""Keep observed shipment charges and hypothetical benchmark results separate."""

import service
from public_benchmark import benchmark_markdown
from records import DEMO_TENANT, connect
from storage import state_snapshot


def seller_report(tenant_id, evaluation):
    estimated = None
    if evaluation:
        try:
            benchmark_markdown(evaluation)
            estimated = evaluation["baselines"]["ship_everything"]["total_cost"] - evaluation["chosen"]["total_cost"]
        except (KeyError, OSError, ValueError):
            evaluation = None
    observations = []
    if tenant_id != DEMO_TENANT:
        with connect(service.STATE_PATH, tenant_id=tenant_id) as db:
            db.execute("BEGIN")
            outcomes = state_snapshot(db, tenant_id, messages=False)["outcomes"]
            observations = [row for row in db.execute("""SELECT order_id, outcome, billed_fee_paisa
                FROM courier_outcome_evidence WHERE tenant_id=?""", (tenant_id,))
                            if outcomes.get(row["order_id"]) == row["outcome"]]
    billed = [row for row in observations if row["billed_fee_paisa"] is not None]
    failed_billed = [row for row in billed if row["outcome"] != "delivered"]
    return {
        "estimated": {"source": "SYNTHETIC locked benchmark vs ship-everything, assumed error costs",
                      "model_id": evaluation["model_id"] if evaluation else None,
                      "benchmark_cost_difference_pkr": estimated, "seller_savings_pkr": None},
        "measured": {"source": "Courier outcomes and seller-supplied statement charges, observational only",
                     "outcomes": {outcome: sum(row["outcome"] == outcome for row in observations)
                                  for outcome in service.OUTCOMES},
                     "shipments_with_billed_fee": len(billed),
                     "billed_fee_total_paisa": sum(row["billed_fee_paisa"] for row in billed) if billed else None,
                     "failed_shipments_with_billed_fee": len(failed_billed),
                     "failed_shipment_billed_fee_paisa": sum(row["billed_fee_paisa"] for row in failed_billed)
                     if failed_billed else None,
                     "seller_savings_pkr": None,
                     "limitation": "There is no verified comparison for what would have happened without COD-Guard."},
    }
