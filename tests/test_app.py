from fastapi.testclient import TestClient

from app import main
from app.providers import (
    _buscar_americanas_api,
    _deve_priorizar_console,
    _corrigir_termo,
    _parse_preco_oferta,
    _parse_preco_brl,
    _normalizar_vendedor_bing,
    _produto_relevante,
    _termo_para_busca
)


def test_parse_preco_brl():
    assert _parse_preco_brl("Por apenas R$ 1.999,90") == 1999.90


def test_anuncios_repetidos_nao_ocupam_tres_vagas():
    from app.providers import _tres_menores_distintas

    ofertas = [
        dict(loja=loja, titulo=titulo, preco=preco, url=str(i))
        for i, (loja, titulo, preco) in enumerate([
            ("Magalu", "SSD Netcore NETNV128ME4", 176.64),
            ("Magalu", "SSD 128 GB NETNV128ME4 com garantia", 176.64),
            ("Magalu", "SSD Netcore NETNV128ME4", 176.64),
            ("KaBuM", "SSD Alltek", 177.39),
            ("KaBuM", "SSD Winmemory", 222.18),
        ])
    ]
    assert _tres_menores_distintas(ofertas[::-1]) == [ofertas[i] for i in (0, 3, 4)]


def test_parse_preco_oferta_prioriza_preco_no_pix():
    texto = (
        "Console PlayStation 5\n"
        "R$ 4.999,90\n"
        "R$ 4.606,55 no Pix\n"
        "em 10x de R$ 484,90"
    )

    assert _parse_preco_oferta(texto) == 4606.55


def test_busca_curta_por_xbox_prioriza_console():
    assert _deve_priorizar_console("Xbox") is True
    assert _termo_para_busca("Xbox") == "Xbox console"


def test_corrige_erros_comuns_no_termo():
    assert _corrigir_termo("playstaiton 5") == "playstation 5"
    assert _corrigir_termo("xobx") == "xbox"
    assert _corrigir_termo("livrso") == "livros"


def test_normaliza_nomes_das_lojas_no_bing_shopping():
    assert _normalizar_vendedor_bing("Magazine Luiza") == "Magalu"
    assert _normalizar_vendedor_bing("KaBuM!") == "KaBuM"
    assert _normalizar_vendedor_bing("Ponto Frio") == "Ponto"
    assert _normalizar_vendedor_bing("Amazon.com.br") == "Amazon"
    assert _normalizar_vendedor_bing("Americanas.com") == "Americanas"


def test_filtro_aceita_singular_quando_busca_plural():
    titulo = "Livro O Hobbit Edição Especial"

    assert _produto_relevante(titulo, "Livros") is True


def test_filtro_aceita_capa_como_parte_de_um_livro():
    titulo = "Livro de ficção Capa Brochura"

    assert _produto_relevante(titulo, "Livros") is True


def test_busca_americanas_api_retorna_oferta(monkeypatch):
    class RespostaFake:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "search": {
                        "products": {
                            "edges": [{
                                "node": {
                                    "name": "Livro de ficção Capa Brochura",
                                    "link": "/livro-ficcao/p",
                                    "offers": {
                                        "offers": [{
                                            "price": 39.90,
                                            "quantity": 10
                                        }]
                                    }
                                }
                            }]
                        }
                    }
                }
            }

    monkeypatch.setattr(
        "app.providers.requests.get",
        lambda *args, **kwargs: RespostaFake()
    )

    ofertas = _buscar_americanas_api("livros")

    assert ofertas[0]["loja"] == "Americanas"
    assert ofertas[0]["preco"] == 39.90


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


def test_filtro_aceita_console_com_controle_incluso():
    titulo = "Console PlayStation 5 Slim com Controle DualSense"

    assert _produto_relevante(
        titulo,
        "PlayStation 5",
        priorizar_console=True
    ) is True


def test_filtro_rejeita_acessorio_compatível_com_console():
    titulo = "HD Externo Portátil 500GB Compatível com Console PlayStation 5"

    assert _produto_relevante(
        titulo,
        "PlayStation 5",
        priorizar_console=True
    ) is False


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

