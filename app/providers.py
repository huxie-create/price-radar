import re
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
    return " ".join(termo.lower().split())


def _deve_priorizar_console(termo):
    termo_normalizado = _normalizar_termo(termo)

    buscas_de_console = {
        "xbox",
        "xbox one",
        "xbox series",
        "xbox series s",
        "xbox series x"
    }

    return termo_normalizado in buscas_de_console


def _termo_para_busca(termo):
    if _deve_priorizar_console(termo):
        return f"{termo.strip()} console"

    return termo.strip()


def _produto_relevante(titulo, termo, priorizar_console=False):
    titulo_normalizado = titulo.lower()
    termo_normalizado = termo.lower()

    palavras = [
        palavra
        for palavra in re.findall(r"[a-z0-9]+", termo_normalizado)
        if len(palavra) >= 3
    ]

    if not all(palavra in titulo_normalizado for palavra in palavras):
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
        "volante"
    }

    tem_acessorio = any(
        acessorio in titulo_normalizado
        and acessorio not in termo_normalizado
        for acessorio in acessorios
    )

    if tem_acessorio:
        return False

    if priorizar_console:
        indicadores_de_console = {
            "console",
            "xbox one",
            "xbox series s",
            "xbox series x"
        }

        if not any(
            indicador in titulo_normalizado
            for indicador in indicadores_de_console
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
                except Exception as erro:
                    print(f"[{nome}] indisponível: {erro}")
                finally:
                    contexto.close()
        finally:
            navegador.close()

    return sorted(
        melhores_por_loja,
        key=lambda oferta: oferta["preco"]
    )[:3]


def buscar_ofertas(termo):
    chave = _normalizar_termo(termo)
    agora = monotonic()

    with _cache_lock:
        resultado_em_cache = _cache_resultados.get(chave)

        if resultado_em_cache:
            validade, ofertas = resultado_em_cache

            if validade > agora:
                return [oferta.copy() for oferta in ofertas]

    with _busca_lock:
        agora = monotonic()

        with _cache_lock:
            resultado_em_cache = _cache_resultados.get(chave)

            if resultado_em_cache:
                validade, ofertas = resultado_em_cache

                if validade > agora:
                    return [oferta.copy() for oferta in ofertas]

        ofertas = _buscar_ofertas_sem_cache(termo)

        with _cache_lock:
            _cache_resultados[chave] = (
                monotonic() + CACHE_TTL_SECONDS,
                ofertas
            )

        return [oferta.copy() for oferta in ofertas]
