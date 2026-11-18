import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.database import (
    criar_tabela,
    salvar_produto,
    buscar_produtos,
    buscar_melhor_preco
)

from app.providers import buscar_ofertas


app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
TESTAR_URL_HABILITADO = os.getenv(
    "ENABLE_TEST_URL",
    "false"
).lower() in {"1", "true", "yes"}

if TESTAR_URL_HABILITADO:
    from app.scraper import ler_pagina

criar_tabela()


class Produto(BaseModel):
    nome: str
    url: str
    loja: str
    preco: float


@app.get("/")
def inicio():
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/produtos")
def cadastrar_produto(produto: Produto):
    produto_id = salvar_produto(
        produto.nome,
        produto.url,
        produto.loja,
        produto.preco
    )

    return {
        "id": produto_id,
        **produto.model_dump()
    }


@app.get("/produtos")
def listar_produtos():
    return buscar_produtos()


@app.get("/melhor-preco")
def melhor_preco(
    nome: str = Query(..., min_length=2, max_length=100)
):
    produto = buscar_melhor_preco(nome)

    if produto is None:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado"
        )

    return produto


@app.get("/comparar")
def comparar(
    nome: str = Query(..., min_length=2, max_length=100)
):
    ofertas = [
        produto
        for produto in buscar_produtos()
        if produto["nome"].lower() == nome.lower()
    ]

    if not ofertas:
        raise HTTPException(
            status_code=404,
            detail="Produto não encontrado"
        )

    return sorted(
        ofertas,
        key=lambda produto: produto["preco"]
    )


if TESTAR_URL_HABILITADO:
    @app.get("/testar-url", include_in_schema=False)
    def testar_url(url: str):
        return ler_pagina(url)


@app.get("/buscar")
def buscar(
    termo: str = Query(..., min_length=2, max_length=100)
):
    return buscar_ofertas(termo)
