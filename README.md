# Sistema de Balanceamento de Linha - Streamlit

Aplicação em Streamlit para balanceamento de linha com entrada manual ou por arquivo, escolha de heurística, geração de estações, métricas, gráfico de distribuição e diagrama de precedências.

## O que o sistema faz

O usuário informa:

- atividades;
- tempo de cada atividade;
- precedências;
- tempo de ciclo;
- heurística desejada.

O sistema retorna:

- alocação das atividades por estação;
- tempo ocupado e ocioso por estação;
- eficiência da linha;
- atraso de balanceamento;
- mínimo teórico de estações;
- índice de suavidade;
- diagrama de precedências;
- gráfico de distribuição das atividades por estação;
- arquivos de resultado para download.

## Heurísticas disponíveis

1. **RPW - Peso Posicional / Helgeson-Birnie**  
   Prioriza a atividade com maior peso posicional, calculado como o tempo da atividade somado aos tempos de todos os seus sucessores.

2. **LCR - Maior tempo de processamento**  
   Prioriza, entre as atividades elegíveis, aquela com maior tempo de processamento.

3. **MFT - Maior número de sucessores**  
   Prioriza, entre as atividades elegíveis, aquela que possui maior número de atividades sucessoras.

## Estrutura dos arquivos

```text
balanceamento_linha_streamlit/
├── app.py
├── requirements.txt
├── README.md
├── .streamlit/
│   └── config.toml
└── assets/
    ├── exemplo_atividades.txt
    ├── exemplo_atividades.xlsx
    └── manual_usuario_balanceamento_linha.pdf
```

## Formato dos dados de entrada

A tabela deve ter três colunas:

| Atividade | Tempo | Precedencias |
|---|---:|---|
| A | 5 | |
| B | 3 | A |
| C | 4 | A |
| D | 2 | B, C |

Use vírgula para separar mais de uma predecessora.

Exemplo em `.txt`:

```text
Atividade;Tempo;Precedencias
A;5;
B;3;A
C;4;A
D;2;B, C
```

## Como rodar localmente

Crie um ambiente virtual, instale as dependências e execute:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Como colocar no GitHub e puxar no Streamlit Cloud

1. Crie um repositório no GitHub.
2. Envie todos os arquivos desta pasta.
3. No Streamlit Cloud, escolha o repositório.
4. Em **Main file path**, informe:

```text
app.py
```

5. Clique em Deploy.

## Observações importantes

- O sistema considera **1 trabalhador por estação**.
- O tempo de ciclo é igual para todas as estações.
- Cada atividade é indivisível, ou seja, não pode ser quebrada entre estações.
- Cada atividade é alocada em apenas uma estação.
- Os tempos são determinísticos.
- Não são considerados setups, deslocamentos, fadiga, ergonomia, disponibilidade de ferramentas, restrições de operadores ou múltiplos produtos.
- O resultado é heurístico e não garante a solução ótima global.
- Se o tempo de ciclo for menor que o tempo da maior atividade, o sistema não consegue gerar solução viável.
