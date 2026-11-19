import re
import unicodedata
from threading import Lock
from time import monotonic
from urllib.parse import quote, quote_plus, urljoin

from playwright.sync_api import sync_playwright


CACHE_TTL_SECONDS = 300
_cache_resultados = {}
_cache_lock = Lock()
_busca_lock = Lock()


def _parse_preco_brl(texto):
    encontrado = re.search(
        r"\d{1,3}(?:\.\d{3})*,\d{2}",
        texto
    )

    if not encontrado:
        return None

    valor = encontrado.group(0)
    valor = valor.replace(".", "").replace(",", ".")

    return float(valor)


def _parse_ultimo_preco_brl(texto):
    encontrados = re.findall(
        r"\d{1,3}(?:\.\d{3})*,\d{2}",
        texto
    )

    if not encontrados:
        return None

    valor = encontrados[-1]
    valor = valor.replace(".", "").replace(",", ".")

    return float(valor)


def _normalizar_termo(termo):
    texto = unicodedata.normalize("NFKD", termo.lower())
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return " ".join(texto.split())


_PERFIS_DE_CONSOLE = {
    "xbox": {
        "busca": "Xbox console",
        "identificadores": ("xbox",),
    },
    "xbox one": {
        "busca": "Xbox One console",
        "identificadores": ("xbox one", "xbox"),
    },
    "xbox series": {
        "busca": "Xbox Series console",
        "identificadores": ("xbox series", "xbox"),
    },
    "xbox series s": {
        "busca": "Xbox Series S console",
        "identificadores": ("xbox series s", "xbox series", "xbox"),
    },
    "xbox series x": {
        "busca": "Xbox Series X console",
        "identificadores": ("xbox series x", "xbox series", "xbox"),
    },
    "playstation 4": {
        "busca": "PlayStation 4 console",
        "identificadores": ("playstation 4", "ps4"),
    },
    "playstation 5": {
        "busca": "PlayStation 5 console",
        "identificadores": ("playstation 5", "playstation5", "ps5"),
    },
    "ps4": {
        "busca": "PlayStation 4 console",
        "identificadores": ("playstation 4", "ps4"),
    },
    "ps5": {
        "busca": "PlayStation 5 console",
        "identificadores": ("playstation 5", "playstation5", "ps5"),
    },
    "nintendo switch": {
        "busca": "Nintendo Switch console",
        "identificadores": ("nintendo switch", "switch"),
    },
    "nintendo switch oled": {
        "busca": "Nintendo Switch OLED console",
        "identificadores": ("nintendo switch oled", "nintendo switch"),
    },
}


def _perfil_de_console(termo):
    termo_normalizado = _normalizar_termo(termo)
    return _PERFIS_DE_CONSOLE.get(termo_normalizado)


def _deve_priorizar_console(termo):
    return _perfil_de_console(termo) is not None


def _termo_para_busca(termo):
    perfil = _perfil_de_console(termo)

    if perfil:
        return perfil["busca"]

    return termo.strip()


def _produto_relevante(titulo, termo, priorizar_console=False):
    titulo_normalizado = _normalizar_termo(titulo)
    termo_normalizado = _normalizar_termo(termo)

    perfil = _perfil_de_console(termo) if priorizar_console else None

    palavras = [
        palavra
        for palavra in re.findall(r"[a-z0-9]+", termo_normalizado)
        if len(palavra) >= 3 or palavra.isdigit()
    ]

    if not perfil and not all(
        palavra in titulo_normalizado
        for palavra in palavras
    ):
        return False

    acessorios = {
        "acessório",
        "acessorio",
        "adaptador",
        "bateria",
        "bolsa",
        "cabo",
        "capa",
        "carregador",
        "carregamento",
        "case",
        "controle",
        "controlador",
        "dock",
        "estojo",
        "gamepad",
        "headset",
        "joy-con",
        "joycon",
        "joystick",
        "joysticks",
        "película",
        "pelicula",
        "suporte",
        "volante",
        "jogo",
        "jogos",
        "game",
        "games",
        "gift card",
        "cartao presente",
        "assinatura",
        "playstation plus",
        "ps plus",
        "dualshock",
        "dualsense"
    }

    tem_acessorio = any(
        acessorio in titulo_normalizado
        and acessorio not in termo_normalizado
        for acessorio in acessorios
    )

    if tem_acessorio:
        return False

    if perfil and not any(
        identificador in titulo_normalizado
        for identificador in perfil["identificadores"]
    ):
        return False

    if perfil and any(
        palavra in titulo_normalizado
        for palavra in ("jogo", "jogos", "game", "games", "gift card")
    ):
        return False

    if perfil and not any(
        indicador in titulo_normalizado
        for indicador in (
            "console",
            "slim",
            "digital edition",
            "edicao digital",
            "disc edition",
            "edicao com disco",
            "com disco",
            "standard edition",
            "512gb",
            "825gb",
            "1tb",
            "2tb",
            "oled",
            "bundle"
        )
    ):
        return False

    if perfil and any(
        acessorio in titulo_normalizado
        for acessorio in (
            "controle",
            "controlador",
            "controller",
            "headset",
            "volante",
            "capa",
            "case",
            "pelicula",
            "película",
            "carregador"
        )
    ):
            return False

    return True


def _buscar_amazon(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    url = f"https://www.amazon.com.br/s?k={quote_plus(termo_busca)}"
    pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
    pagina.wait_for_selector(
        'div[data-component-type="s-search-result"]',
        timeout=15000
    )

    ofertas = []
    cards = pagina.locator(
        'div[data-component-type="s-search-result"]'
    )

    quantidade = min(cards.count(), 20)

    for indice in range(quantidade):
        card = cards.nth(indice)
        titulo_elemento = card.locator("h2 span")
        preco_elemento = card.locator(".a-price .a-offscreen")

        if not titulo_elemento.count():
            continue

        if not preco_elemento.count():
            continue

        titulo = titulo_elemento.first.inner_text().strip()
        href = card.locator("h2").first.evaluate(
            "elemento => elemento.closest('a')?.getAttribute('href')"
        )
        preco = _parse_preco_brl(
            preco_elemento.first.inner_text()
        )

        if not href or preco is None:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        ofertas.append({
            "loja": "Amazon",
            "titulo": titulo,
            "preco": preco,
            "url": urljoin("https://www.amazon.com.br", href)
        })

    return ofertas


def _buscar_kabum(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote(termo_busca, safe="").replace("%20", "-")
    url = f"https://www.kabum.com.br/busca/{busca}"
    pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
    pagina.wait_for_selector(
        'a[href*="/produto/"]',
        timeout=15000
    )

    ofertas = []
    cards = pagina.locator('a[href*="/produto/"]')
    quantidade = min(cards.count(), 20)

    for indice in range(quantidade):
        card = cards.nth(indice)
        linhas = [
            linha.strip()
            for linha in card.inner_text().splitlines()
            if linha.strip()
        ]

        titulo = next(
            (
                linha
                for linha in linhas
                if len(linha) > 20
                and "Avaliação" not in linha
                and "Desconto" not in linha
                and "No PIX" not in linha
                and "Produto" not in linha
                and "Cupom" not in linha
                and "Restam" not in linha
            ),
            None
        )

        texto_antes_do_pix = card.inner_text().split("No PIX")[0]
        preco = _parse_ultimo_preco_brl(texto_antes_do_pix)

        if not titulo or preco is None:
            continue

        href = card.get_attribute("href")

        if not href:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        ofertas.append({
            "loja": "KaBuM",
            "titulo": titulo,
            "preco": preco,
            "url": urljoin("https://www.kabum.com.br", href)
        })

    return ofertas


def _buscar_magalu(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote(termo_busca, safe="")
    url = f"https://www.magazineluiza.com.br/busca/{busca}/"
    pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
    pagina.wait_for_timeout(2500)

    titulo_pagina = pagina.title().lower()

    if "não é possível acessar" in titulo_pagina:
        return []

    return []


def _buscar_ofertas_sem_cache(termo):
    melhores_por_loja = []
    status_lojas = []

    provedores = [
        ("Amazon", _buscar_amazon),
        ("KaBuM", _buscar_kabum),
        ("Magalu", _buscar_magalu)
    ]

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)

        try:
            for nome, buscar_provedor in provedores:
                contexto = navegador.new_context(locale="pt-BR")
                pagina = contexto.new_page()

                try:
                    ofertas_da_loja = buscar_provedor(pagina, termo)

                    if ofertas_da_loja:
                        melhor_oferta = min(
                            ofertas_da_loja,
                            key=lambda oferta: oferta["preco"]
                        )
                        melhores_por_loja.append(melhor_oferta)
                        status_lojas.append({
                            "nome": nome,
                            "status": "encontrada"
                        })
                    else:
                        status_lojas.append({
                            "nome": nome,
                            "status": "sem_resultado"
                        })
                except Exception as erro:
                    print(f"[{nome}] indisponível: {erro}")
                    status_lojas.append({
                        "nome": nome,
                        "status": "indisponivel"
                    })
                finally:
                    contexto.close()
        finally:
            navegador.close()

    return {
        "ofertas": sorted(
            melhores_por_loja,
            key=lambda oferta: oferta["preco"]
        )[:3],
        "lojas": status_lojas
    }


def _copiar_resultado(resultado):
    return {
        "ofertas": [oferta.copy() for oferta in resultado["ofertas"]],
        "lojas": [loja.copy() for loja in resultado["lojas"]]
    }


def buscar_ofertas(termo):
    chave = _normalizar_termo(termo)
    agora = monotonic()

    with _cache_lock:
        resultado_em_cache = _cache_resultados.get(chave)

        if resultado_em_cache:
            validade, resultado = resultado_em_cache

            if validade > agora:
                return _copiar_resultado(resultado)

    with _busca_lock:
        agora = monotonic()

        with _cache_lock:
            resultado_em_cache = _cache_resultados.get(chave)

            if resultado_em_cache:
                validade, resultado = resultado_em_cache

                if validade > agora:
                    return _copiar_resultado(resultado)

        resultado = _buscar_ofertas_sem_cache(termo)

        with _cache_lock:
            _cache_resultados[chave] = (
                monotonic() + CACHE_TTL_SECONDS,
                resultado
            )

        return _copiar_resultado(resultado)
