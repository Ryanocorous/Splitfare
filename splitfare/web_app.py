from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .core import (
    INDEX_WINDOW_OPTIONS,
    RAILCARD_OPTIONS,
    SOURCE_BRFARES,
    SOURCE_DEMO,
    SOURCE_LABELS,
    SOURCE_OFFICIAL,
    SplitFareError,
    build_options,
    result_to_dict,
    run_search,
)

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="SplitFare UK")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def form_context(request: Request, error: str = "", result: dict | None = None) -> dict:
    """This prepares shared data for the HTML pages."""

    return {
        "request": request,
        "error": error,
        "result": result,
        "sources": [
            {"value": SOURCE_OFFICIAL, "label": SOURCE_LABELS[SOURCE_OFFICIAL]},
            {"value": SOURCE_BRFARES, "label": SOURCE_LABELS[SOURCE_BRFARES]},
            {"value": SOURCE_DEMO, "label": SOURCE_LABELS[SOURCE_DEMO]},
        ],
        "railcards": RAILCARD_OPTIONS,
        "index_windows": INDEX_WINDOW_OPTIONS,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """This shows the browser GUI form."""

    return templates.TemplateResponse("index.html", form_context(request))


@app.post("/search", response_class=HTMLResponse)
def search(
    request: Request,
    source: str = Form(...),
    origin: str = Form(...),
    destination: str = Form(...),
    travel_date: str = Form(...),
    start_time: str = Form(...),
    calling_points: str = Form(default=""),
    railcard: str = Form(default=""),
    index_minutes: int = Form(default=5),
    custom_index_minutes: str = Form(default=""),
    adults: int = Form(default=1),
    children: int = Form(default=0),
):
    """This runs the split search from the browser form."""

    try:
        custom_value = int(custom_index_minutes) if custom_index_minutes.strip() else None
        options = build_options(
            source=source,
            origin=origin,
            destination=destination,
            travel_date=travel_date,
            start_time=start_time,
            calling_points=calling_points,
            railcard=railcard,
            index_minutes=index_minutes,
            custom_index_minutes=custom_value,
            adults=adults,
            children=children,
        )
        result = result_to_dict(run_search(options))
    except (SplitFareError, ValueError) as exc:
        return templates.TemplateResponse("index.html", form_context(request, error=str(exc)))

    return templates.TemplateResponse("results.html", form_context(request, result=result))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("splitfare.web_app:app", host="127.0.0.1", port=8010, reload=True)
