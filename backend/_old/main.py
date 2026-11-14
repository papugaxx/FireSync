from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import db
from config import FRONTEND_URLS, MAX_LIMIT

app = FastAPI(title="FireSync API`S")





app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_URLS,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/tables")
def tables():
    return db.get_tables()


@app.get("/data/{table}")
def data(table: str, request: Request, limit: int = 1000, offset: int = 0):
    filters = {k: v for k,v in request.query_params.items() if k not in ("limit", "offset")}
    limit = max(1, min(limit, MAX_LIMIT))

    rows, total = db.get_row(table, filters, limit, max(offset, 0))

    return {
        "table": table,
        "total": total,   
        "limit": limit,
        "offset": offset,
        "rows": rows,      
    }