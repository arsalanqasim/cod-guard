"""Bounded operator upload and read-only courier lookup."""

import csv

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

import courier_outcomes as courier
import service
from operators import Operator, write_operator
from records import DEMO_TENANT


router = APIRouter(prefix="/integrations/couriers")


def _shadow(operator):
    if operator.tenant_id == DEMO_TENANT:
        raise HTTPException(403, "Courier evidence requires a separate shadow tenant")


@router.post("/outcomes/import")
def import_outcomes(file: UploadFile = File(...), operator: Operator = Depends(write_operator)):
    _shadow(operator)
    contents = file.file.read(1024 * 1024 + 1)
    if not contents or len(contents) > 1024 * 1024:
        raise HTTPException(422, "Courier CSV must be nonempty and at most 1 MiB")
    try:
        return courier.store(operator.tenant_id, operator.actor, courier.parse_csv(contents), "operator-csv")
    except courier.OutcomeConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, "Courier order not found") from None
    except (csv.Error, UnicodeError):
        raise HTTPException(422, "Invalid UTF-8 courier CSV") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


class Tracking(BaseModel):
    tracking_number: str = Field(pattern=r"^[0-9]{5,32}$")


@router.post("/tcs/orders/{order_id}/refresh")
def refresh_tcs(order_id: str, body: Tracking, operator: Operator = Depends(write_operator)):
    _shadow(operator)
    try:
        order = service.get_order(order_id, operator.tenant_id)
        if order["data_source"].casefold() == "synthetic":
            raise KeyError(order_id)
        token = courier.tcs_token(operator.tenant_id)
        outcome = courier.tcs_status(body.tracking_number, token)
        if outcome is None:
            return {"terminal": False, "labels_added": 0}
        row = (order_id, "tcs", body.tracking_number, outcome, None)
        return {"terminal": True, **courier.store(operator.tenant_id, operator.actor, [row], "tcs-tracking")}
    except KeyError:
        raise HTTPException(404, "Courier order not found") from None
    except courier.OutcomeConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except courier.CourierUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
