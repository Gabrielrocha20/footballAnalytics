from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, collectors, database, neural_model, prediction_history
from .auth import (
    COOKIE_NAME,
    authentication_configured,
    cookie_secure,
    require_access,
    verify_token,
)
from .config import FRONTEND_DIST, SOURCES
from .jobs import jobs


@asynccontextmanager
async def lifespan(_: FastAPI):
    if neural_model.auto_train_enabled():
        jobs.submit("model:auto-startup", neural_model.train_stale_models)
    yield
    jobs.shutdown()


app = FastAPI(
    title="TradeFot API",
    version="1.3.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SyncPayload(BaseModel):
    source: Literal["onefootball", "sofascore", "football_data"]
    scope: Literal["incremental", "all"] = "incremental"


class MinutesPayload(BaseModel):
    source: Literal["onefootball", "sofascore"]
    match_ids: list[int] = Field(min_length=1, max_length=30)


class LoginPayload(BaseModel):
    token: str = Field(min_length=16, max_length=512)


class OfferedOdd(BaseModel):
    market: Literal[
        "match_odds",
        "btts",
        "total_goals",
        "exact_score",
        "clean_sheet",
        "team_to_score",
    ]
    selection: str = Field(min_length=2, max_length=30)
    odds: float = Field(gt=1, le=1000)


class ValuePayload(BaseModel):
    offers: list[OfferedOdd] = Field(min_length=1, max_length=30)


class ModelTrainPayload(BaseModel):
    source: Literal["onefootball", "sofascore", "football_data"]
    force: bool = False


def _data_call(callback):
    try:
        return callback()
    except database.DataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tradefot"}


@app.get("/api/auth/status")
def auth_status():
    return {
        "configured": authentication_configured(),
        "methods": ["cookie", "bearer", "x-access-token"],
    }


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response):
    if not authentication_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autenticação ainda não foi configurada no servidor",
        )
    if not verify_token(payload.token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de acesso inválido",
        )
    response.set_cookie(
        key=COOKIE_NAME,
        value=payload.token,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path="/",
    )
    return {"authenticated": True, "token_type": "bearer"}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="strict",
    )
    return {"authenticated": False}


@app.get("/api/auth/me", dependencies=[Depends(require_access)])
def current_user():
    return {"authenticated": True, "role": "owner"}


@app.get("/api/sources", dependencies=[Depends(require_access)])
def sources():
    return [_data_call(lambda key=key: database.source_summary(key)) for key in SOURCES]


@app.get("/api/leagues", dependencies=[Depends(require_access)])
def leagues(
    source: str = Query("onefootball"),
    search: str = Query("", max_length=100),
):
    return _data_call(lambda: database.list_leagues(source, search))


@app.get("/api/matches/upcoming", dependencies=[Depends(require_access)])
def upcoming_matches(
    source: str = Query("onefootball"),
    league_id: str | None = None,
    search: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
):
    return _data_call(
        lambda: database.list_upcoming(source, league_id, search, page, page_size)
    )


@app.get("/api/leagues/{league_id}", dependencies=[Depends(require_access)])
def league_detail(
    league_id: str,
    source: str = Query("onefootball"),
    season: int | None = None,
):
    return _data_call(lambda: database.league_overview(source, league_id, season))


@app.get("/api/matches/{match_id}/analysis", dependencies=[Depends(require_access)])
def match_analysis(match_id: int, source: str = Query("onefootball")):
    result = _data_call(lambda: analytics.match_analysis(source, match_id))
    try:
        prediction_history.save_source_analysis(source, result)
    except Exception:
        # O histórico de auditoria não deve impedir a exibição da análise.
        pass
    return result


@app.get("/api/performance", dependencies=[Depends(require_access)])
def analysis_performance(
    source: str = Query("onefootball"),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(30, ge=1, le=100),
):
    return _data_call(lambda: prediction_history.performance(source, days, limit))


@app.post("/api/matches/{match_id}/value", dependencies=[Depends(require_access)])
def match_value(
    match_id: int,
    payload: ValuePayload,
    source: str = Query("onefootball"),
):
    offers = [item.model_dump() for item in payload.offers]
    return _data_call(lambda: analytics.value_analysis(source, match_id, offers))


@app.get("/api/matches/{match_id}/prediction", dependencies=[Depends(require_access)])
def neural_prediction(match_id: int, source: str = Query("onefootball")):
    return _data_call(lambda: neural_model.predict(source, match_id))


@app.get("/api/models/status", dependencies=[Depends(require_access)])
def model_status(source: str | None = Query(None)):
    if source is not None:
        return _data_call(lambda: neural_model.status(source))
    return [_data_call(lambda key=key: neural_model.status(key)) for key in SOURCES]


@app.post("/api/models/train", status_code=202, dependencies=[Depends(require_access)])
def train_model(payload: ModelTrainPayload):
    database.source_config(payload.source)
    return jobs.submit(
        f"model:train:{payload.source}",
        lambda progress: neural_model.train(payload.source, progress, force=payload.force),
    )


@app.post("/api/sync", status_code=202, dependencies=[Depends(require_access)])
def start_sync(payload: SyncPayload):
    return jobs.submit(
        f"sync:{payload.source}:{payload.scope}",
        lambda progress: collectors.sync_and_train(payload.source, payload.scope, progress),
    )


@app.post("/api/minutes", status_code=202, dependencies=[Depends(require_access)])
def start_minutes(payload: MinutesPayload):
    return jobs.submit(
        f"minutes:{payload.source}",
        lambda progress: collectors.collect_minutes(
            payload.source, payload.match_ids, progress
        ),
    )


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_access)])
def job_status(job_id: str):
    try:
        return jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada") from exc


if (FRONTEND_DIST / "assets").exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Rota não encontrada"}, status_code=404)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {
            "message": "Frontend ainda não compilado",
            "build": "cd frontend && npm install && npm run build",
            "docs": "/api/docs",
        }
    )
