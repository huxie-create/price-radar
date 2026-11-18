import sqlite3


def criar_tabela():
    conexao = sqlite3.connect("produtos.db")

    conexao.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            url TEXT NOT NULL,
            loja TEXT NOT NULL,
            preco REAL NOT NULL
        )
    """)

    conexao.commit()
    conexao.close()


def salvar_produto(nome, url, loja, preco):
    conexao = sqlite3.connect("produtos.db")

    cursor = conexao.execute(
        """
        INSERT INTO produtos (nome, url, loja, preco)
        VALUES (?, ?, ?, ?)
        """,
        (nome, url, loja, preco)
    )

    conexao.commit()
    produto_id = cursor.lastrowid
    conexao.close()

    return produto_id


def buscar_produtos():
    conexao = sqlite3.connect("produtos.db")

    cursor = conexao.execute(
        """
        SELECT id, nome, url, loja, preco
        FROM produtos
        ORDER BY id
        """
    )

    linhas = cursor.fetchall()
    conexao.close()

    return [
        {
            "id": linha[0],
            "nome": linha[1],
            "url": linha[2],
            "loja": linha[3],
            "preco": linha[4]
        }
        for linha in linhas
    ]


def buscar_melhor_preco(nome):
    conexao = sqlite3.connect("produtos.db")

    cursor = conexao.execute(
        """
        SELECT id, nome, url, loja, preco
        FROM produtos
        WHERE LOWER(nome) = LOWER(?)
        ORDER BY preco ASC
        LIMIT 1
        """,
        (nome,)
    )

    linha = cursor.fetchone()
    conexao.close()

    if linha is None:
        return None

    return {
        "id": linha[0],
        "nome": linha[1],
        "url": linha[2],
        "loja": linha[3],
        "preco": linha[4]
    }