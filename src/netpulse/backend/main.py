import sqlite3
import os
import secrets

from fastapi import FastAPI, Query, Request, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from backend import storage
from backend.models import Measurement, MeasurementCreate, MeasurementList

app = FastAPI(title="NetPulse", version="0.1.0", description="Limited pilot internet-quality observations. Consenting device collectors upload bounded genuine observations.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def authorize(authorization: str | None = Header(default=None)):
    token = os.environ.get("NETPULSE_UPLOAD_TOKEN")
    if token and not secrets.compare_digest(authorization or "", "Bearer " + token):
        raise HTTPException(401, "A valid NetPulse bearer token is required")


@app.post("/measurements", response_model=Measurement, status_code=201, dependencies=[Depends(authorize)])
def create_measurement(payload: MeasurementCreate):
    return storage.create_measurement(payload)


@app.get("/measurements", response_model=MeasurementList, dependencies=[Depends(authorize)])
def get_measurements(limit: int = Query(default=500, ge=1, le=5000), offset: int = Query(default=0, ge=0)):
    return storage.list_measurements(limit, offset)


@app.exception_handler(sqlite3.Error)
async def storage_error(request: Request, exc: sqlite3.Error):
    return JSONResponse(status_code=503, content={"detail": "Measurement storage is unavailable. Check the configured database path and permissions."})


@app.exception_handler(OSError)
async def filesystem_error(request: Request, exc: OSError):
    return JSONResponse(status_code=503, content={"detail": "Measurement storage path is unavailable. Check its permissions."})


@app.exception_handler(storage.DuplicateObservation)
async def duplicate_observation(request: Request, exc: storage.DuplicateObservation):
    return JSONResponse(status_code=409, content={"detail": str(exc)})
