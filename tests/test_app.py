from fastapi.testclient import TestClient

from app import main
from app.providers import (
    _deve_priorizar_console,
    _parse_preco_brl,
    _produto_relevante,
    _termo_para_busca
)


def test_parse_preco_brl():
    assert _parse_preco_brl("Por apenas R$ 1.999,90") == 1999.90


def test_busca_curta_por_xbox_prioriza_console():
    assert _deve_priorizar_console("Xbox") is True
    assert _termo_para_busca("Xbox") == "Xbox console"


def test_busca_por_playstation_5_prioriza_console():
    assert _deve_priorizar_console("PlayStation 5") is True
    assert _termo_para_busca("PlayStation 5") == "PlayStation 5 console"


def test_filtro_rejeita_controle_quando_busca_console():
    titulo = "Controlador sem fio Xbox Series X"

    assert _produto_relevante(
        titulo,
        "Xbox",
        priorizar_console=True
    ) is False


def test_filtro_aceita_console_quando_busca_xbox():
    titulo = "Console Microsoft Xbox Series S 512GB"

    assert _produto_relevante(
        titulo,
        "Xbox",
        priorizar_console=True
    ) is True


def test_filtro_rejeita_jogo_quando_busca_playstation_5():
    titulo = "Jogo Marvel Spider-Man 2 PS5"

    assert _produto_relevante(
        titulo,
        "PlayStation 5",
        priorizar_console=True
    ) is False


def test_filtro_rejeita_produto_de_jogo_com_nome_do_console():
    titulo = "Grand Theft Auto VI - PlayStation 5"

    assert _produto_relevante(
        titulo,
        "PlayStation 5",
        priorizar_console=True
    ) is False


def test_filtro_aceita_console_playstation_5():
    titulo = "Sony PlayStation 5 Slim 1TB Edição Digital"

    assert _produto_relevante(
        titulo,
        "PlayStation 5",
        priorizar_console=True
    ) is True


def test_inicio_retorna_pagina():
    with TestClient(main.app) as cliente:
        resposta = cliente.get("/")

    assert resposta.status_code == 200
    assert "PriceRadar" in resposta.text


def test_health_retorna_status_ok():
    with TestClient(main.app) as cliente:
        resposta = cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


def test_buscar_rejeita_termo_muito_curto():
    with TestClient(main.app) as cliente:
        resposta = cliente.get(
            "/buscar",
            params={"termo": "X"}
        )

    assert resposta.status_code == 422


def test_buscar_retorna_ofertas(monkeypatch):
    ofertas = [
        {
            "loja": "Amazon",
            "titulo": "Console Xbox Series S",
            "preco": 1999.90,
            "url": "https://example.com/xbox"
        }
    ]
    resultado = {
        "ofertas": ofertas,
        "lojas": [
            {"nome": "Amazon", "status": "encontrada"},
            {"nome": "KaBuM", "status": "indisponivel"},
            {"nome": "Magalu", "status": "sem_resultado"}
        ]
    }

    monkeypatch.setattr(
        main,
        "buscar_ofertas",
        lambda termo: resultado
    )

    with TestClient(main.app) as cliente:
        resposta = cliente.get(
            "/buscar",
            params={"termo": "Xbox"}
        )

    assert resposta.status_code == 200
    assert resposta.json() == resultado


def test_cadastrar_produto(monkeypatch):
    monkeypatch.setattr(
        main,
        "salvar_produto",
        lambda nome, url, loja, preco: 42
    )

    produto = {
        "nome": "Console Xbox Series S",
        "url": "https://example.com/xbox",
        "loja": "Loja de teste",
        "preco": 1999.90
    }

    with TestClient(main.app) as cliente:
        resposta = cliente.post("/produtos", json=produto)

    assert resposta.status_code == 200
    assert resposta.json() == {
        "id": 42,
        **produto
    }


def test_comparar_ordena_do_menor_para_o_maior(monkeypatch):
    produtos = [
        {"id": 1, "nome": "Xbox", "url": "a", "loja": "A", "preco": 2500.0},
        {"id": 2, "nome": "Xbox", "url": "b", "loja": "B", "preco": 2200.0}
    ]

    monkeypatch.setattr(main, "buscar_produtos", lambda: produtos)

    with TestClient(main.app) as cliente:
        resposta = cliente.get(
            "/comparar",
            params={"nome": "Xbox"}
        )

    assert resposta.status_code == 200
    assert resposta.json()[0]["preco"] == 2200.0


def test_melhor_preco_retorna_404_quando_nao_encontra(monkeypatch):
    monkeypatch.setattr(
        main,
        "buscar_melhor_preco",
        lambda nome: None
    )

    with TestClient(main.app) as cliente:
        resposta = cliente.get(
            "/melhor-preco",
            params={"nome": "Produto inexistente"}
        )

    assert resposta.status_code == 404
    assert resposta.json()["detail"] == "Produto não encontrado"

