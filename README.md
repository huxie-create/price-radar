# PriceRadar

Aplicação web para pesquisar produtos e comparar preços em lojas online.

O usuário digita o nome de um produto e o PriceRadar pesquisa ofertas, filtra acessórios que não correspondem ao produto principal e mostra as melhores opções encontradas.

## Demonstração

O projeto possui uma interface web simples e uma API criada com FastAPI.

Fluxo principal:

1. O usuário informa um produto, como `Xbox` ou `Nintendo Switch OLED`.
2. O backend pesquisa as lojas configuradas usando Playwright.
3. Os resultados são filtrados para evitar controles, capas, cabos e outros acessórios quando a intenção é encontrar o console.
4. A aplicação escolhe a menor oferta disponível em cada loja.
5. As ofertas são ordenadas pelo preço e exibidas na tela.

## Tecnologias

- Python
- FastAPI
- Playwright
- SQLite
- HTML, CSS e JavaScript
- Uvicorn

## Lojas

O projeto possui provedores para:

- Amazon
- KaBuM
- Magalu

As lojas podem bloquear automações ou alterar o HTML da página. Por isso, em alguns momentos a aplicação pode retornar menos de três ofertas.

## Como executar no Windows

Abra o PowerShell dentro da pasta do projeto.

### 1. Criar o ambiente virtual

```powershell
python -m venv .venv
```

### 2. Ativar o ambiente virtual

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o ambiente já estiver ativado, pule esta etapa.

### 3. Instalar as dependências

```powershell
pip install -r requirements.txt
```

### 4. Instalar o navegador usado pelo Playwright

```powershell
python -m playwright install chromium
```

### 5. Iniciar a aplicação

```powershell
python -m uvicorn app.main:app --reload
```

Depois, abra no navegador:

```text
http://127.0.0.1:8000/
```

## Documentação da API

Com a aplicação executando, a documentação interativa está disponível em:

```text
http://127.0.0.1:8000/docs
```

### Buscar ofertas

```text
GET /buscar?termo=Xbox
```

### Cadastrar produto

```text
POST /produtos
```

Exemplo de corpo:

```json
{
  "nome": "Nintendo Switch OLED",
  "url": "https://exemplo.com/produto",
  "loja": "Loja de exemplo",
  "preco": 1999.90
}
```

### Listar produtos cadastrados

```text
GET /produtos
```

### Encontrar o menor preço salvo

```text
GET /melhor-preco?nome=Nintendo%20Switch%20OLED
```

### Comparar preços salvos

```text
GET /comparar?nome=Nintendo%20Switch%20OLED
```

### Verificar saúde da aplicação

```text
GET /health
```

Resposta esperada:

```json
{
  "status": "ok"
}
```

## Segurança e desempenho

- As buscas aceitam termos entre 2 e 100 caracteres.
- Resultados iguais ficam em cache por 5 minutos para evitar abrir vários navegadores para a mesma pesquisa.
- O endpoint de teste de URL fica desativado por padrão, evitando que a aplicação pública acesse endereços arbitrários.
- Para habilitar esse endpoint apenas durante o desenvolvimento, use no PowerShell:

```powershell
$env:ENABLE_TEST_URL = "true"
```

## Testes

Os testes verificam os filtros de produtos, a interpretação de buscas por console e as principais rotas da API sem depender de uma busca real nas lojas.

Para executar:

```powershell
python -m pytest -q
```

O projeto também possui uma rotina do GitHub Actions que executa os testes automaticamente a cada push ou pull request.

## Executar com Docker

O projeto possui uma imagem baseada no ambiente oficial do Playwright, que já inclui o Chromium necessário para as buscas.

```powershell
docker build -t price-radar .
docker run --rm -p 8000:8000 price-radar
```

Depois, acesse `http://localhost:8000/`.

## Estrutura do projeto

```text
price-radar/
├── app/
│   ├── database.py       # Funções do banco SQLite
│   ├── main.py           # Rotas da API e entrada da aplicação
│   ├── providers.py      # Buscas nas lojas
│   ├── scraper.py        # Leitura de páginas com Playwright
│   └── templates/
│       └── index.html    # Interface web
├── tests/                # Testes automatizados
├── .gitignore
├── README.md
└── requirements.txt
```

## Observações importantes

- Os preços podem mudar entre a busca e a abertura da oferta.
- Frete, impostos e condições de pagamento podem não estar incluídos no preço exibido.
- A busca depende da disponibilidade das páginas das lojas.
- O projeto é um MVP educacional e de portfólio.
- Para uma versão de produção, o ideal é usar APIs oficiais, criar cache, limitar requisições e monitorar alterações nas páginas.

## Próximos passos

- Adicionar testes automatizados para os filtros e endpoints.
- Mostrar na interface quando uma loja estiver indisponível.
- Adicionar cache para evitar abrir o navegador em toda pesquisa.
- Criar uma imagem Docker para facilitar o deploy.
- Substituir scraping por APIs oficiais quando houver acesso.

