from playwright.sync_api import sync_playwright


def ler_pagina(url):
    url = url.strip().replace("\\", "")

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)

        try:
            pagina = navegador.new_page()

            pagina.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30000
            )

            pagina.wait_for_timeout(3000)

            titulo = pagina.title()

            elemento_preco = pagina.locator(
                'meta[itemprop="price"]'
            )

            preco = None

            if elemento_preco.count() > 0:
                valor = elemento_preco.get_attribute("content")

                if valor:
                    preco = float(valor)

            return {
                "status": 200,
                "titulo": titulo,
                "preco": preco
            }

        finally:
            navegador.close()
            