import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from time import monotonic
from urllib.parse import quote, quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


CACHE_TTL_SECONDS = 300
BROWSER_NAVIGATION_TIMEOUT_MS = 7000
BROWSER_SELECTOR_TIMEOUT_MS = 2500
BROWSER_WAIT_MS = 600
CARREFOUR_TIMEOUT_SECONDS = 5
BING_TIMEOUT_SECONDS = 3
AMERICANAS_TIMEOUT_SECONDS = 8
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



_CORRECOES_DE_TIPOS = {
    "livrso": "livros",
    "livroos": "livros",
    "playstaiton": "playstation",
    "xobx": "xbox"
}


def _corrigir_termo(termo):
    return " ".join(
        _CORRECOES_DE_TIPOS.get(palavra, palavra)
        for palavra in _normalizar_termo(termo).split()
    )


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
    termo_normalizado = _normalizar_termo(_corrigir_termo(termo))
    return _PERFIS_DE_CONSOLE.get(termo_normalizado)


def _deve_priorizar_console(termo):
    return _perfil_de_console(termo) is not None


def _termo_para_busca(termo):
    termo = _corrigir_termo(termo)
    perfil = _perfil_de_console(termo)

    if perfil:
        return perfil["busca"]

    return termo.strip()


def _variantes_de_palavra(palavra):
    """Aceita pequenas variações de singular e plural nos títulos."""
    variantes = {palavra}

    if len(palavra) >= 5 and palavra.endswith("s"):
        variantes.add(palavra[:-1])
    elif len(palavra) >= 5:
        variantes.add(f"{palavra}s")

    return variantes


def _produto_relevante(titulo, termo, priorizar_console=False):
    titulo_normalizado = _normalizar_termo(titulo)
    termo_normalizado = _normalizar_termo(_corrigir_termo(termo))

    perfil = _perfil_de_console(termo) if priorizar_console else None

    palavras = [
        palavra
        for palavra in re.findall(r"[a-z0-9]+", termo_normalizado)
        if len(palavra) >= 3 or palavra.isdigit()
    ]

    if not perfil and not all(
        any(
            variante in titulo_normalizado
            for variante in _variantes_de_palavra(palavra)
        )
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
        "tampa",
        "volante",
        "jogo",
        "jogos",
        "game",
        "games",
        "gift card",
        "cartao presente",
        "hd externo",
        "disco externo",
        "memoria externa",
        "leitor drive",
        "drive de disco",
        "assinatura",
        "playstation plus",
        "ps plus",
        "dualshock",
        "dualsense"
    }

    # Em livros, "capa" descreve a edição e não um acessório separado.
    if "livro" in titulo_normalizado:
        acessorios.discard("capa")

    if not perfil:
        # Um acessório pode ser o produto procurado, ou acompanhar o produto.
        primeiro = titulo_normalizado.split()[:1]
        return not (
            primeiro and primeiro[0] in acessorios
            and primeiro[0] not in termo_normalizado.split()
        )

    acessorios_que_podem_acompanhar_console = {
        "controle",
        "controlador",
        "controller",
        "dualsense",
        "dualshock"
    }
    tem_acessorio_exclusivo = any(
        acessorio in titulo_normalizado
        and acessorio not in termo_normalizado
        and acessorio not in acessorios_que_podem_acompanhar_console
        for acessorio in acessorios
    )

    if tem_acessorio_exclusivo:
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
    pagina.goto(
        url,
        wait_until="domcontentloaded",
        timeout=BROWSER_NAVIGATION_TIMEOUT_MS
    )
    pagina.wait_for_selector(
        'div[data-component-type="s-search-result"]',
        timeout=BROWSER_SELECTOR_TIMEOUT_MS
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

        titulo = titulo_elemento.first.text_content().strip()
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


def _buscar_mercado_livre(termo):
    slug = quote("-".join(_termo_para_busca(termo).split()), safe="")
    resposta = requests.get(f"https://lista.mercadolivre.com.br/{slug}", timeout=5)
    resposta.raise_for_status()
    pagina = BeautifulSoup(resposta.content, "html.parser")
    ofertas = []
    for card in pagina.select(".poly-card")[:40]:
        link = card.select_one("a.poly-component__title[href]")
        preco = card.select_one(".poly-price__current .andes-money-amount")
        if not link or not preco:
            continue
        titulo = link.get_text(" ", strip=True)
        inteiro = preco.select_one(".andes-money-amount__fraction")
        centavos = preco.select_one(".andes-money-amount__cents")
        if not inteiro or not _produto_relevante(titulo, termo, _deve_priorizar_console(termo)):
            continue
        valor = inteiro.get_text(strip=True).replace(".", "") + "." + (
            centavos.get_text(strip=True) if centavos else "00"
        )
        if re.fullmatch(r"\d+\.\d{2}", valor) and float(valor) > 0:
            ofertas.append({"loja": "Mercado Livre", "titulo": titulo,
                            "preco": float(valor), "url": urljoin(resposta.url, link["href"])})
    return ofertas


def _buscar_kabum(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote(termo_busca, safe="").replace("%20", "-")
    url = f"https://www.kabum.com.br/busca/{busca}"
    pagina.goto(
        url,
        wait_until="domcontentloaded",
        timeout=BROWSER_NAVIGATION_TIMEOUT_MS
    )
    pagina.wait_for_selector(
        'a[href*="/produto/"]',
        timeout=BROWSER_SELECTOR_TIMEOUT_MS
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
    pagina.goto(
        url,
        wait_until="domcontentloaded",
        timeout=BROWSER_NAVIGATION_TIMEOUT_MS
    )
    pagina.wait_for_timeout(BROWSER_WAIT_MS)

    titulo_pagina = pagina.title().lower()

    if "não é possível acessar" in titulo_pagina:
        return []

    return []


def _normalizar_vendedor_bing(vendedor):
    vendedor_normalizado = " ".join(
        re.findall(r"[a-z0-9]+", _normalizar_termo(vendedor))
    )

    nomes = {
        "mercado livre": "Mercado Livre",
        "mercadolivre": "Mercado Livre",
        "amazon": "Amazon",
        "amazon com br": "Amazon",
        "americanas": "Americanas",
        "americanas com": "Americanas",
        "americanas com br": "Americanas",
        "kabum": "KaBuM",
        "magalu": "Magalu",
        "magazine luiza": "Magalu",
        "ponto": "Ponto",
        "ponto frio": "Ponto",
        "pontofrio": "Ponto",
        "carrefour": "Carrefour",
        "pichau": "Pichau"
    }

    for nome, loja in nomes.items():
        if (
            vendedor_normalizado == nome
            or vendedor_normalizado.startswith(f"{nome} ")
        ):
            return loja

    return None


def _buscar_bing_shopping_http(termo, lojas_alvo):
    """Lê o HTML público do Bing sem abrir um navegador pesado."""
    termo_busca = _termo_para_busca(termo)
    url = f"https://www.bing.com/shop?q={quote_plus(termo_busca)}"
    resposta = requests.get(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        },
        timeout=BING_TIMEOUT_SECONDS
    )
    resposta.raise_for_status()

    soup = BeautifulSoup(resposta.text, "html.parser")
    cards = soup.select("li.br-item")
    ofertas = []
    chaves = set()

    for card in cards[:40]:
        titulo_elemento = card.select_one(".br-pdItemName")
        preco_elemento = card.select_one(".pd-price")
        vendedor_elemento = card.select_one(".br-sellersCite")

        if not titulo_elemento or not preco_elemento or not vendedor_elemento:
            continue

        titulo = titulo_elemento.get_text(" ", strip=True)
        vendedor = vendedor_elemento.get_text(" ", strip=True)
        loja = _normalizar_vendedor_bing(vendedor)
        preco = _parse_preco_brl(
            preco_elemento.get_text(" ", strip=True)
        )
        href = card.get("data-url")

        if loja not in lojas_alvo or preco is None:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        href = urljoin("https://www.bing.com", href) if href else url
        chave = (loja, titulo.lower(), preco, href)

        if chave in chaves:
            continue

        chaves.add(chave)
        ofertas.append({
            "loja": loja,
            "titulo": titulo,
            "preco": preco,
            "url": href
        })

    return ofertas


def _buscar_bing_shopping(pagina, termo, lojas_alvo):
    termo_busca = _termo_para_busca(termo)
    url = f"https://www.bing.com/shop?q={quote_plus(termo_busca)}"

    pagina.goto(
        url,
        wait_until="domcontentloaded",
        timeout=BROWSER_NAVIGATION_TIMEOUT_MS
    )
    pagina.wait_for_selector(
        "li.br-item",
        timeout=BROWSER_SELECTOR_TIMEOUT_MS
    )

    cards = pagina.locator("li.br-item")
    ofertas = []
    chaves = set()

    for indice in range(min(cards.count(), 40)):
        card = cards.nth(indice)
        titulo_elemento = card.locator(".br-pdItemName")
        preco_elemento = card.locator(".pd-price")
        vendedor_elemento = card.locator(".br-sellersCite")

        if not titulo_elemento.count():
            continue

        if not preco_elemento.count() or not vendedor_elemento.count():
            continue

        titulo = titulo_elemento.first.text_content().strip()
        vendedor = vendedor_elemento.first.inner_text().strip()
        loja = _normalizar_vendedor_bing(vendedor)
        preco = _parse_preco_brl(preco_elemento.first.inner_text())

        if loja not in lojas_alvo or preco is None:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        href = card.get_attribute("data-url")

        if href:
            href = urljoin("https://www.bing.com", href)
        else:
            href = url

        chave = (loja, titulo.lower(), preco, href)

        if chave in chaves:
            continue

        chaves.add(chave)
        ofertas.append({
            "loja": loja,
            "titulo": titulo,
            "preco": preco,
            "url": href
        })

    return ofertas


def _buscar_carrefour_api(termo):
    url = "https://www.carrefour.com.br/api/io/_v/api/intelligent-search/product_search"
    resposta = requests.get(
        url,
        params={"query": _corrigir_termo(termo)},
        headers={
            "Accept": "application/json",
            "Referer": "https://www.carrefour.com.br/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        },
        timeout=CARREFOUR_TIMEOUT_SECONDS
    )
    resposta.raise_for_status()
    dados = resposta.json()

    ofertas = []

    for produto in dados.get("products", [])[:30]:
        titulo = produto.get("productName", "").strip()

        if not titulo:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        precos = []

        for item in produto.get("items", []):
            for vendedor in item.get("sellers", []):
                oferta = vendedor.get("commertialOffer", {})
                quantidade = oferta.get("AvailableQuantity", 0) or 0

                if quantidade <= 0:
                    continue

                for campo in ("spotPrice", "Price"):
                    preco = oferta.get(campo)

                    if preco and preco > 0:
                        precos.append(float(preco))

        if not precos:
            continue

        href = produto.get("link")

        if not href:
            continue

        ofertas.append({
            "loja": "Carrefour",
            "titulo": titulo,
            "preco": min(precos),
            "url": urljoin("https://www.carrefour.com.br", href)
        })

    return ofertas


def _parse_preco_oferta(texto):
    padrao_valor = r"\d{1,3}(?:\.\d{3})*,\d{2}"

    for marcador in ("no pix", "à vista", "a vista"):
        encontrado = re.search(
            rf"({padrao_valor})\s*{re.escape(marcador)}",
            texto,
            flags=re.IGNORECASE
        )

        if encontrado:
            valor = encontrado.group(1)
            return float(valor.replace(".", "").replace(",", "."))

    texto_minusculo = texto.lower()
    indice = texto_minusculo.rfind("por")

    if indice >= 0:
        preco = _parse_preco_brl(texto[indice:])

        if preco is not None:
            return preco

    return _parse_preco_brl(texto)


def _buscar_loja_generica(
    pagina,
    termo,
    loja,
    url,
    seletor_de_cards
):
    pagina.goto(
        url,
        wait_until="domcontentloaded",
        timeout=BROWSER_NAVIGATION_TIMEOUT_MS
    )
    pagina.wait_for_timeout(BROWSER_WAIT_MS)

    corpo = pagina.locator("body").inner_text().lower()

    if any(
        mensagem in corpo
        for mensagem in (
            "verificando se você é humano",
            "executando verificação de segurança",
            "cloudflare",
            "algo deu errado"
        )
    ):
        raise RuntimeError("a loja apresentou uma verificação de segurança")

    if any(
        mensagem in corpo
        for mensagem in (
            "nenhum produto encontrado",
            "não encontramos resultados",
            "não encontramos nenhum produto"
        )
    ):
        return []

    pagina.wait_for_selector(
        seletor_de_cards,
        timeout=BROWSER_SELECTOR_TIMEOUT_MS
    )
    cards = pagina.locator(seletor_de_cards)
    ofertas = []
    chaves = set()

    for indice in range(min(cards.count(), 20)):
        card = cards.nth(indice)
        texto = card.inner_text().strip()

        if not texto:
            continue

        linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
        titulo = max(
            (
                linha
                for linha in linhas
                if len(linha) >= 15
                and _parse_preco_brl(linha) is None
                and "avaliação" not in linha.lower()
                and "parcel" not in linha.lower()
                and "frete" not in linha.lower()
            ),
            key=len,
            default=None
        )
        preco = _parse_preco_oferta(texto)
        href = card.get_attribute("href")

        if not href:
            links = card.locator("a")

            if links.count():
                href = links.first.get_attribute("href")

        if not titulo or preco is None or not href:
            continue

        if not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        chave = (titulo.lower(), preco, href)

        if chave in chaves:
            continue

        chaves.add(chave)
        ofertas.append({
            "loja": loja,
            "titulo": titulo,
            "preco": preco,
            "url": urljoin(url, href)
        })

    return ofertas


def _buscar_ponto(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote_plus(termo_busca)
    url = f"https://www.pontofrio.com.br/busca?query={busca}"

    return _buscar_loja_generica(
        pagina,
        termo,
        "Ponto",
        url,
        'a[href*="/p/"], a[href*="/produto/"]'
    )


def _buscar_carrefour(pagina, termo):
    return _buscar_carrefour_api(termo)


def _buscar_pichau(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote_plus(termo_busca)
    url = f"https://www.pichau.com.br/search?q={busca}"

    return _buscar_loja_generica(
        pagina,
        termo,
        "Pichau",
        url,
        'article, [data-testid*="product"], [class*="productCard"], a:has(h2), a:has(h3)'
    )


def _buscar_americanas(pagina, termo):
    termo_busca = _termo_para_busca(termo)
    busca = quote(termo_busca, safe="")
    url = f"https://www.americanas.com.br/busca/{busca}"

    return _buscar_loja_generica(
        pagina,
        termo,
        "Americanas",
        url,
        'a[href$="/p"], a[href*="/p?"]'
    )


def _buscar_americanas_api(termo):
    """Consulta a busca pública que a própria página da Americanas utiliza."""
    termo_busca = _termo_para_busca(termo)
    channel = json.dumps(
        {"salesChannel": "1", "regionId": ""},
        separators=(",", ":")
    )
    variaveis = {
        "first": 12,
        "after": "0",
        "sort": "score_desc",
        "term": termo_busca,
        "selectedFacets": [
            {"key": "fuzzy", "value": "0"},
            {"key": "operator", "value": "and"},
            {"key": "channel", "value": channel},
            {"key": "locale", "value": "pt-BR"}
        ],
        "sponsoredCount": 3,
        "_postalCode": ""
    }
    resposta = requests.get(
        "https://www.americanas.com.br/api/graphql",
        params={
            "operationName": "ClientManyProductsQueryWithSearchId",
            "operationHash": (
                "cb154b9b1216966884f4d325dd7f61928dc3a7ec"
            ),
            "variables": json.dumps(
                variaveis,
                separators=(",", ":")
            )
        },
        headers={
            "Accept": "application/json",
            "Referer": "https://www.americanas.com.br/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        },
        timeout=AMERICANAS_TIMEOUT_SECONDS
    )
    resposta.raise_for_status()
    dados = resposta.json()
    edges = (
        dados.get("data", {})
        .get("search", {})
        .get("products", {})
        .get("edges", [])
    )
    ofertas = []

    for edge in edges[:20]:
        produto = edge.get("node", {})
        titulo = produto.get("name", "").strip()

        if not titulo or not _produto_relevante(
            titulo,
            termo,
            _deve_priorizar_console(termo)
        ):
            continue

        precos_disponiveis = [
            oferta.get("price")
            for oferta in produto.get("offers", {}).get("offers", [])
            if oferta.get("quantity", 0) > 0
            and oferta.get("price", 0) > 0
        ]

        if not precos_disponiveis:
            continue

        href = produto.get("link")

        if not href:
            continue

        ofertas.append({
            "loja": "Americanas",
            "titulo": titulo,
            "preco": min(precos_disponiveis),
            "url": urljoin("https://www.americanas.com.br", href)
        })

    return ofertas


def _executar_provedor_em_navegador(buscar_provedor, termo):
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)

        try:
            contexto = navegador.new_context(locale="pt-BR")
            pagina = contexto.new_page()
            pagina.set_default_timeout(BROWSER_SELECTOR_TIMEOUT_MS)
            pagina.set_default_navigation_timeout(
                BROWSER_NAVIGATION_TIMEOUT_MS
            )

            try:
                return buscar_provedor(pagina, termo)
            finally:
                contexto.close()
        finally:
            navegador.close()


def _buscar_ofertas_sem_cache(termo):
    candidatas = []
    nomes_das_lojas = (
        "Mercado Livre",
        "Amazon",
        "Americanas",
        "KaBuM",
        "Magalu",
        "Ponto",
        "Carrefour",
        "Pichau"
    )
    status_por_loja = {
        nome: {"nome": nome, "status": "sem_resultado"}
        for nome in nomes_das_lojas
    }

    # As fontes principais rodam em paralelo. Assim uma loja lenta não segura
    # as outras e a API consegue devolver as primeiras ofertas rapidamente.
    provedores = [
        ("Mercado Livre", lambda: _buscar_mercado_livre(termo)),
        (
            "Amazon",
            lambda: _executar_provedor_em_navegador(_buscar_amazon, termo)
        ),
        ("Americanas", lambda: _buscar_americanas_api(termo)),
        ("Carrefour", lambda: _buscar_carrefour_api(termo))
    ]

    with ThreadPoolExecutor(max_workers=len(provedores)) as executor:
        tarefas = {
            executor.submit(buscar_provedor): nome
            for nome, buscar_provedor in provedores
        }

        for tarefa in as_completed(tarefas):
            nome = tarefas[tarefa]

            try:
                ofertas_da_loja = tarefa.result()

                if ofertas_da_loja:
                    candidatas.extend(ofertas_da_loja)
                    status_por_loja[nome]["status"] = "encontrada"
            except Exception as erro:
                print(f"[{nome}] indisponível: {erro}")
                status_por_loja[nome]["status"] = "indisponivel"

    # O Bing também serve como plano B para Amazon e Americanas quando elas
    # bloqueiam o navegador direto. Isso evita mostrar zero ofertas só porque
    # uma fonte principal ficou indisponível naquela tentativa.
    lojas_para_fallback = {
        nome
        for nome in nomes_das_lojas
        if status_por_loja[nome]["status"] != "encontrada"
    }

    if lojas_para_fallback:
        try:
            ofertas_fallback = _buscar_bing_shopping_http(
                termo,
                lojas_para_fallback
            )
        except Exception as erro:
            print(f"[Bing Shopping HTTP] indisponível: {erro}")
            ofertas_fallback = []

        for oferta in ofertas_fallback:
            candidatas.append(oferta)
            status_por_loja[oferta["loja"]]["status"] = "encontrada"

    ofertas = []
    vistas = set()
    for oferta in sorted(candidatas, key=lambda item: (item["preco"], item["url"])):
        chave = (oferta["loja"], oferta["url"])
        if chave not in vistas:
            ofertas.append(oferta)
            vistas.add(chave)
        if len(ofertas) == 3:
            break

    return {
        "ofertas": ofertas,
        "lojas": [
            status_por_loja[nome]
            for nome in nomes_das_lojas
        ],
        "termo_corrigido": _corrigir_termo(termo)
    }


def _copiar_resultado(resultado):
    return {
        "ofertas": [oferta.copy() for oferta in resultado["ofertas"]],
        "lojas": [loja.copy() for loja in resultado["lojas"]],
        "termo_corrigido": resultado.get("termo_corrigido")
    }


def buscar_ofertas(termo):
    termo_corrigido = _corrigir_termo(termo)
    chave = _normalizar_termo(termo_corrigido)
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

        resultado = _buscar_ofertas_sem_cache(termo_corrigido)

        with _cache_lock:
            _cache_resultados[chave] = (
                monotonic() + CACHE_TTL_SECONDS,
                resultado
            )

        return _copiar_resultado(resultado)
