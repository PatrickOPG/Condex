"""Backend do checklist de conquistas da Steam (MVP).

Rodar:  uvicorn main:app --reload
Abrir:  http://127.0.0.1:8000
"""
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()
STEAM_KEY = os.getenv("STEAM_API_KEY", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
IDIOMA = "brazilian"  # descrições das conquistas em português

BASE = Path(__file__).parent
DB_PATH = BASE / "dados.db"
TTL_SCHEMA = 7 * 24 * 3600   # lista de conquistas quase não muda
TTL_RARIDADE = 24 * 3600     # porcentagem global muda devagar

app = FastAPI(title="Checklist de conquistas")


# ---------------------------------------------------------------- banco
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def iniciar_banco():
    with closing(db()) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache (
                chave    TEXT PRIMARY KEY,
                valor    TEXT NOT NULL,
                salvo_em REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guias (
                appid    INTEGER NOT NULL,
                api_name TEXT    NOT NULL,
                texto    TEXT    NOT NULL,
                fase     TEXT    NOT NULL DEFAULT '',
                tags     TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (appid, api_name)
            );
            """
        )
        con.commit()


iniciar_banco()


def cache_ler(chave: str, ttl: float):
    with closing(db()) as con:
        linha = con.execute(
            "SELECT valor, salvo_em FROM cache WHERE chave = ?", (chave,)
        ).fetchone()
    if linha and time.time() - linha["salvo_em"] < ttl:
        return json.loads(linha["valor"])
    return None


def cache_gravar(chave: str, valor):
    with closing(db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO cache (chave, valor, salvo_em) VALUES (?, ?, ?)",
            (chave, json.dumps(valor), time.time()),
        )
        con.commit()


# ---------------------------------------------------------------- Steam
async def steam_get(caminho: str, **params) -> httpx.Response:
    if not STEAM_KEY:
        raise HTTPException(500, "Falta configurar STEAM_API_KEY no arquivo .env")
    params["key"] = STEAM_KEY
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            return await client.get(f"https://api.steampowered.com/{caminho}", params=params)
        except httpx.HTTPError:
            raise HTTPException(502, "Não consegui falar com a Steam. Tente de novo.")


MSG_PRIVADO = (
    "O perfil está privado. Na Steam, abra Perfil > Editar perfil > "
    "Configurações de privacidade e deixe 'Detalhes do jogo' como Público."
)


async def obter_schema(appid: int) -> dict:
    chave = f"schema:{appid}:{IDIOMA}"
    dado = cache_ler(chave, TTL_SCHEMA)
    if dado:
        return dado
    r = await steam_get("ISteamUserStats/GetSchemaForGame/v2/", appid=appid, l=IDIOMA)
    if r.status_code != 200:
        raise HTTPException(404, "Jogo não encontrado na Steam.")
    jogo = r.json().get("game", {})
    lista = jogo.get("availableGameStats", {}).get("achievements", [])
    if not lista:
        raise HTTPException(404, "Este jogo não tem conquistas na Steam.")
    dado = {"nome": jogo.get("gameName", f"App {appid}"), "conquistas": lista}
    cache_gravar(chave, dado)
    return dado


async def obter_raridade(appid: int) -> dict:
    chave = f"raridade:{appid}"
    dado = cache_ler(chave, TTL_RARIDADE)
    if dado is not None:
        return dado
    r = await steam_get("ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/", gameid=appid)
    dado = {}
    if r.status_code == 200:
        lista = r.json().get("achievementpercentages", {}).get("achievements", [])
        dado = {a["name"]: float(a["percent"]) for a in lista}
        cache_gravar(chave, dado)
    return dado


async def obter_progresso(appid: int, steamid: str) -> dict:
    """Retorna {api_name: unlocktime} das conquistas já desbloqueadas."""
    r = await steam_get(
        "ISteamUserStats/GetPlayerAchievements/v1/", appid=appid, steamid=steamid, l=IDIOMA
    )
    if r.status_code == 403:
        raise HTTPException(403, MSG_PRIVADO)
    if r.status_code != 200:
        return {}  # jogo nunca jogado ou sem dados: tudo pendente
    ps = r.json().get("playerstats", {})
    if not ps.get("success", False):
        if "not public" in str(ps.get("error", "")).lower():
            raise HTTPException(403, MSG_PRIVADO)
        return {}
    return {a["apiname"]: a.get("unlocktime", 0) for a in ps.get("achievements", []) if a.get("achieved") == 1}


def obter_guias(appid: int) -> dict:
    with closing(db()) as con:
        linhas = con.execute(
            "SELECT api_name, texto, fase, tags FROM guias WHERE appid = ?", (appid,)
        ).fetchall()
    return {l["api_name"]: dict(l) for l in linhas}


# ---------------------------------------------------------------- rotas
@app.get("/api/resolver")
async def resolver(entrada: str):
    """Aceita SteamID64, nome personalizado ou link do perfil."""
    entrada = entrada.strip().rstrip("/").split("/")[-1]
    if entrada.isdigit() and len(entrada) == 17:
        return {"steamid": entrada}
    r = await steam_get("ISteamUser/ResolveVanityURL/v1/", vanityurl=entrada)
    resp = r.json().get("response", {}) if r.status_code == 200 else {}
    if resp.get("success") != 1:
        raise HTTPException(404, "Perfil não encontrado. Confira o nome ou o link.")
    return {"steamid": resp["steamid"]}


@app.get("/api/biblioteca/{steamid}")
async def biblioteca(steamid: str):
    r = await steam_get(
        "IPlayerService/GetOwnedGames/v1/",
        steamid=steamid, include_appinfo=1, include_played_free_games=1,
    )
    if r.status_code != 200:
        raise HTTPException(502, "A Steam não respondeu. Tente de novo.")
    jogos = r.json().get("response", {}).get("games")
    if jogos is None:
        raise HTTPException(403, MSG_PRIVADO)
    jogos.sort(key=lambda j: j.get("name", "").lower())
    return [
        {"appid": j["appid"], "nome": j.get("name", f"App {j['appid']}"),
         "horas": round(j.get("playtime_forever", 0) / 60, 1)}
        for j in jogos
    ]


@app.get("/api/jogo/{appid}")
async def jogo(appid: int, steamid: Optional[str] = None):
    schema = await obter_schema(appid)
    raridade = await obter_raridade(appid)
    feitas = await obter_progresso(appid, steamid) if steamid else {}
    guias = obter_guias(appid)

    conquistas = []
    for c in schema["conquistas"]:
        nome_api = c["name"]
        g = guias.get(nome_api, {})
        conquistas.append({
            "id": nome_api,
            "nome": c.get("displayName", nome_api),
            "descricao": c.get("description", ""),
            "oculta": bool(c.get("hidden", 0)),
            "icone": c.get("icon", ""),
            "raridade": raridade.get(nome_api),
            "desbloqueada": nome_api in feitas,
            "guia": g.get("texto", ""),
            "fase": g.get("fase", ""),
            "tags": [t.strip() for t in g.get("tags", "").split(",") if t.strip()],
        })
    return {"appid": appid, "nome": schema["nome"], "conquistas": conquistas}


class GuiaEntrada(BaseModel):
    appid: int
    api_name: str
    texto: str
    fase: str = ""
    tags: str = ""  # separadas por vírgula, ex: "perdível, online"


@app.post("/api/guia")
def salvar_guia(g: GuiaEntrada, x_admin_token: Optional[str] = Header(None)):
    """Cadastra ou atualiza o 'como conseguir' de uma conquista (só você)."""
    if not ADMIN_TOKEN or not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Token de administrador inválido.")
    with closing(db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO guias (appid, api_name, texto, fase, tags) VALUES (?, ?, ?, ?, ?)",
            (g.appid, g.api_name, g.texto, g.fase, g.tags),
        )
        con.commit()
    return {"ok": True}


# Serve o site (precisa ficar por último)
app.mount("/", StaticFiles(directory=BASE / "frontend", html=True), name="site")
