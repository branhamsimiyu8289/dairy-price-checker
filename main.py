import asyncio, json, math, os, secrets, sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    raise RuntimeError("Set the ADMIN_PASSWORD environment variable before starting the app")

BASE = Path(__file__).parent
DB = BASE / "dairy.db"
app = FastAPI(title="Dairy Price Checker")
tokens: set[str] = set()
subscribers: list[asyncio.Queue] = []


@contextmanager
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()


with db() as c:
    c.executescript("""
    create table if not exists farmers(id integer primary key, name text unique collate nocase not null);
    create table if not exists settings(key text primary key, value text);
    create table if not exists entries(id integer primary key, farmer_name text not null,
        litres real not null, price real not null, total real not null, day text not null,
        created text not null);
    insert or ignore into settings values('price','0'),('updated','');
    """)
    if not c.execute("select 1 from farmers").fetchone():
        c.executemany("insert into farmers(name) values(?)",
                      [(n,) for n in ["Wanjiru Kamau", "Otieno Odhiambo", "Chebet Kiprop", "Mwangi Njoroge"]])


def get_price():
    with db() as c:
        s = dict(c.execute("select key, value from settings").fetchall())
    return {"price": float(s["price"]), "updated": s["updated"]}


def admin(authorization: str = Header("")):
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() != "bearer" or credential not in tokens:
        raise HTTPException(401, "Admin login required")


class Login(BaseModel):
    password: str

class PriceIn(BaseModel):
    price: float = Field(gt=0, le=10000)

class EntryIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    litres: float = Field(gt=0, le=10000)


@app.get("/api/price")
def price():
    return get_price()


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE / "index.html")


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return FileResponse(BASE / "manifest.json", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(BASE / "sw.js", media_type="application/javascript")


@app.get("/api/farmers")
def farmers():
    with db() as c:
        return [r["name"] for r in c.execute("select name from farmers order by name")]


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    subscribers.append(q)

    async def gen():
        try:
            yield f"data: {json.dumps(get_price())}\n\n"
            while True:
                try:
                    yield f"data: {await asyncio.wait_for(q.get(), 20)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/entries")
def add_entry(e: EntryIn):
    p = get_price()["price"]
    if p <= 0:
        raise HTTPException(409, "Today’s price has not been set yet")
    name = " ".join(e.name.split())
    if len(name) < 2:
        raise HTTPException(422, "Name must contain at least two non-space characters")
    total = round(e.litres * p, 2)
    now = datetime.now()
    with db() as c:
        c.execute("insert or ignore into farmers(name) values(?)", (name,))
        c.execute("insert into entries(farmer_name,litres,price,total,day,created) values(?,?,?,?,?,?)",
                  (name, e.litres, p, total, now.date().isoformat(), now.isoformat(timespec="seconds")))
    return {"name": name, "litres": e.litres, "price": p, "total": total}


@app.post("/api/admin/login")
def login(b: Login):
    if not secrets.compare_digest(b.password, ADMIN_PASSWORD):
        raise HTTPException(401, "Wrong password")
    t = secrets.token_urlsafe(32)
    tokens.add(t)
    return {"token": t}


@app.post("/api/admin/price", dependencies=[Depends(admin)])
def set_price(b: PriceIn):
    if not math.isfinite(b.price):
        raise HTTPException(422, "Price must be a finite number")
    with db() as c:
        c.execute("update settings set value=? where key='price'", (str(b.price),))
        c.execute("update settings set value=? where key='updated'", (datetime.now().isoformat(timespec="minutes"),))
    p = get_price()
    for q in subscribers:
        q.put_nowait(json.dumps(p))
    return p


@app.get("/api/admin/entries", dependencies=[Depends(admin)])
def entries(day: str = ""):
    day = day or date.today().isoformat()
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(422, "Day must be an ISO date (YYYY-MM-DD)")
    with db() as c:
        rows = [dict(r) for r in c.execute("select * from entries where day=? order by id desc", (day,))]
    return {"day": day, "entries": rows,
            "farmers": len({r["farmer_name"].lower() for r in rows}),
            "litres": round(sum(r["litres"] for r in rows), 2),
            "total": round(sum(r["total"] for r in rows), 2)}


@app.delete("/api/admin/entries/{entry_id}", dependencies=[Depends(admin)])
def delete_entry(entry_id: int):
    with db() as c:
        c.execute("delete from entries where id=?", (entry_id,))
    return {"ok": True}
