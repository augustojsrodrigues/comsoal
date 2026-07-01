import html
import io
import json
import math
import random
import re
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# Configuração da página
# ============================================================

st.set_page_config(
    page_title="Balanceamento de Linha",
    page_icon="⚙️",
    layout="wide",
)

st.title("⚙️ Sistema de Balanceamento de Linha")
st.caption(
    "Informe atividades, tempos e precedências. Escolha uma heurística e rode o balanceamento por estações."
)


# ============================================================
# Dados de exemplo
# ============================================================

SAMPLE_DATA = pd.DataFrame(
    [
        {"Atividade": "A", "Tempo": 12, "Precedências": ""},
        {"Atividade": "B", "Tempo": 10, "Precedências": "A"},
        {"Atividade": "C", "Tempo": 8, "Precedências": "A"},
        {"Atividade": "D", "Tempo": 15, "Precedências": "B"},
        {"Atividade": "E", "Tempo": 7, "Precedências": "B, C"},
        {"Atividade": "F", "Tempo": 12, "Precedências": "C"},
        {"Atividade": "G", "Tempo": 9, "Precedências": "D"},
        {"Atividade": "H", "Tempo": 10, "Precedências": "D, E"},
        {"Atividade": "I", "Tempo": 6, "Precedências": "E"},
        {"Atividade": "J", "Tempo": 11, "Precedências": "F"},
        {"Atividade": "K", "Tempo": 8, "Precedências": "G, H"},
        {"Atividade": "L", "Tempo": 14, "Precedências": "H, I"},
        {"Atividade": "M", "Tempo": 7, "Precedências": "J"},
        {"Atividade": "N", "Tempo": 10, "Precedências": "K, L"},
        {"Atividade": "O", "Tempo": 8, "Precedências": "M, N"},
        {"Atividade": "P", "Tempo": 6, "Precedências": "O"},
        {"Atividade": "Q", "Tempo": 9, "Precedências": "I, J"},
        {"Atividade": "R", "Tempo": 5, "Precedências": "L, Q"},
    ]
)

EMPTY_DATA = pd.DataFrame(
    [
        {"Atividade": "", "Tempo": None, "Precedências": ""},
    ]
)

HEURISTIC_OPTIONS = {
    "Maior Tempo de Operação (Largest Candidate Rule, LCR)": "LCR",
    "Peso Posicional Ranqueado (Ranked Positional Weight, RPW/Helgeson-Birnie)": "RPW",
    "Kilbridge-Wester": "KW",
    "J-Wagon": "JWAGON",
    "COMSOAL": "COMSOAL",
}

STATION_COLORS = [
    "#22c55e",
    "#3b82f6",
    "#d946ef",
    "#f59e0b",
    "#14b8a6",
    "#ef4444",
    "#8b5cf6",
    "#84cc16",
    "#06b6d4",
    "#f97316",
]


def reset_outputs_and_go_home() -> None:
    keys_to_remove = [
        "last_solution",
        "node_offsets",
        "station_filter_diagram",
        "show_internal_edges_diagram",
        "show_labels_diagram",
    ]
    for key in keys_to_remove:
        st.session_state.pop(key, None)
    st.session_state["result_page"] = "Estações"
    st.session_state["input_mode"] = "Digitar ou editar tabela"



# ============================================================
# Funcoes auxiliares de arquivo
# ============================================================

def normalize_column_name(col: str) -> str:
    col = str(col).strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "â": "a",
        "ã": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for old, new in replacements.items():
        col = col.replace(old, new)
    col = re.sub(r"[^a-z0-9]+", "_", col)
    return col.strip("_")


def normalize_activity(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_precedence_cell(value) -> List[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value).strip()
    if text == "" or text.lower() in {"-", "nenhuma", "none", "nan"}:
        return []
    parts = re.split(r"[,;|\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def standardize_input_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["Atividade", "Tempo", "Precedências"])

    df = df.copy()
    original_columns = list(df.columns)
    normalized = {col: normalize_column_name(col) for col in original_columns}

    aliases = {
        "atividade": "Atividade",
        "atividades": "Atividade",
        "task": "Atividade",
        "tarefa": "Atividade",
        "codigo": "Atividade",
        "id": "Atividade",
        "tempo": "Tempo",
        "duracao": "Tempo",
        "time": "Tempo",
        "duration": "Tempo",
        "precedencias": "Precedências",
        "precedencia": "Precedências",
        "predecessoras": "Precedências",
        "predecessores": "Precedências",
        "predecessors": "Precedências",
        "predecessor": "Precedências",
    }

    rename = {}
    for col, norm in normalized.items():
        if norm in aliases:
            rename[col] = aliases[norm]

    df = df.rename(columns=rename)

    required = ["Atividade", "Tempo", "Precedências"]
    for col in required:
        if col not in df.columns:
            df[col] = "" if col != "Tempo" else None

    df = df[required]
    df["Atividade"] = df["Atividade"].apply(normalize_activity)
    df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce")
    df["Precedências"] = df["Precedências"].fillna("").astype(str).str.strip()
    df = df[df["Atividade"] != ""].reset_index(drop=True)
    return df


def parse_txt(uploaded_file) -> pd.DataFrame:
    content = uploaded_file.read().decode("utf-8-sig")
    for sep in [";", ",", "\t"]:
        try:
            df = pd.read_csv(io.StringIO(content), sep=sep)
            cols = [normalize_column_name(c) for c in df.columns]
            has_activity = any(c in cols for c in ["atividade", "atividades", "tarefa", "task"])
            has_time = any(c in cols for c in ["tempo", "duracao", "time", "duration"])
            if has_activity and has_time:
                return standardize_input_df(df)
        except Exception:
            pass
    df = pd.read_csv(io.StringIO(content), sep=";", header=0)
    return standardize_input_df(df)


def parse_excel(uploaded_file) -> pd.DataFrame:
    df = pd.read_excel(uploaded_file)
    return standardize_input_df(df)


def example_txt_bytes() -> bytes:
    output = io.StringIO()
    SAMPLE_DATA.to_csv(output, index=False, sep=";")
    return output.getvalue().encode("utf-8")


def example_excel_bytes() -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        SAMPLE_DATA.to_excel(writer, index=False, sheet_name="Atividades")
        ws = writer.sheets["Atividades"]
        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column_letter].width = min(max_length + 4, 45)
    output.seek(0)
    return output.getvalue()


# ============================================================
# Manual PDF gerado no proprio app
# ============================================================

def pdf_escape(text: str) -> str:
    text = str(text)
    encoded = text.encode("cp1252", errors="replace")
    out = []
    for b in encoded:
        ch = chr(b)
        if ch in ["\\", "(", ")"]:
            out.append("\\" + ch)
        elif b < 32 or b > 126:
            out.append(f"\\{b:03o}")
        else:
            out.append(ch)
    return "".join(out)


def wrap_text(text: str, max_chars: int = 92) -> List[str]:
    words = str(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = word if current == "" else current + " " + word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def make_manual_pdf_bytes() -> bytes:
    content_lines = [
        ("title", "Manual do Sistema de Balanceamento de Linha"),
        ("h1", "1. Objetivo"),
        ("p", "Este sistema monta uma solução heurística para o balanceamento de linha com atividades, tempos de operação e relações de precedência."),
        ("p", "O usuário informa o tempo de ciclo e escolhe uma heurística. O sistema distribui as atividades em estações, calcula métricas e gera tabelas e gráficos."),
        ("h1", "2. Hipóteses do modelo"),
        ("p", "O sistema considera uma linha com 1 trabalhador por estação."),
        ("p", "As atividades não podem ser divididas entre estações."),
        ("p", "Cada atividade tem tempo determinístico e maior que zero."),
        ("p", "As precedências precisam formar uma rede sem ciclos."),
        ("p", "Uma atividade pode ficar na mesma estação de sua predecessora, desde que a ordem interna seja respeitada."),
        ("p", "O tempo de cada atividade precisa ser menor ou igual ao tempo de ciclo."),
        ("p", "Os métodos são heurísticos. Portanto, eles buscam uma boa solução, mas não garantem o ótimo global."),
        ("h1", "3. Formato dos dados"),
        ("p", "A tabela precisa ter as colunas Atividade, Tempo e Precedências."),
        ("p", "Em Precedências, informe as atividades predecessoras separadas por vírgula. Se não houver predecessora, deixe em branco."),
        ("p", "Exemplo: A com tempo 20 e sem precedência. B com tempo 6 e precedência A. E com tempo 15 e precedências C, D."),
        ("h1", "4. Entrada manual"),
        ("p", "Use a opção Digitar ou editar tabela. O sistema já abre com um exemplo preenchido. O botão Limpar tabela apaga o exemplo para permitir inserir novos dados."),
        ("h1", "5. Importação por TXT"),
        ("p", "Use a opção Importar TXT. Baixe o modelo TXT, edite o arquivo e importe novamente. O separador recomendado é ponto e vírgula."),
        ("h1", "6. Importação por Excel"),
        ("p", "Use a opção Importar Excel. Baixe o modelo Excel, edite a planilha e importe novamente."),
        ("h1", "7. Heurísticas disponíveis"),
        ("h2", "7.1 Maior Tempo de Operação (Largest Candidate Rule, LCR)"),
        ("p", "Ordena as atividades candidatas pelo maior tempo de operação. Em cada estação, seleciona a maior atividade elegível que ainda cabe no tempo restante."),
        ("p", "A ideia é alocar primeiro atividades longas para reduzir a chance de sobras grandes no fim do balanceamento."),
        ("h2", "7.2 Peso Posicional Ranqueado (RPW/Helgeson-Birnie)"),
        ("p", "Calcula o peso posicional de cada atividade como o tempo da atividade somado aos tempos de todos os seus sucessores diretos e indiretos."),
        ("p", "Em cada estação, seleciona a atividade elegível com maior peso posicional que ainda cabe no tempo restante."),
        ("h2", "7.3 Kilbridge-Wester"),
        ("p", "Agrupa as atividades em colunas ou níveis de precedência. Atividades mais próximas do inicio da rede recebem prioridade antes das atividades de colunas posteriores."),
        ("p", "No app, entre atividades elegíveis, o metodo prioriza a menor coluna. Em caso de empate, usa maior tempo e maior número de sucessores."),
        ("h2", "7.4 J-Wagon"),
        ("p", "Prioriza atividades com maior número de sucessores na rede de precedência. A lógica e antecipar atividades que liberam mais trabalho posterior."),
        ("p", "No app, o desempate usa maior número de sucessores imediatos, maior tempo de operação e maior peso posicional."),
        ("h2", "7.5 COMSOAL"),
        ("p", "Constrói soluções aleatórias viáveis. Em cada passo, forma uma lista de atividades elegíveis que respeitam as precedências e cabem no tempo restante da estação."),
        ("p", "O método sorteia uma atividade dessa lista, completa a estação e repete o processo. O app executa várias tentativas e guarda a melhor solução encontrada."),
        ("p", "A semente aleatoria permite repetir o mesmo resultado quando necessário."),
        ("h1", "8. Resultados"),
        ("p", "O sistema mostra a quantidade de estações, mínimo teórico, eficiência, tempo ocioso, atraso de balanceamento e índice de suavidade."),
        ("p", "Também gera a tabela de estações, a tabela de atividades, o diagrama de precedências por estação e o gráfico de ocupação por estação."),
        ("h1", "9. Diagrama de precedências por estação"),
        ("p", "O diagrama usa cores para identificar as estações e posiciona as atividades em colunas por estação, em uma forma parecida com softwares de balanceamento de linha."),
        ("p", "Por padrão, o diagrama mostra todas as relações de precedência, inclusive as ligações internas da mesma estação."),
        ("p", "O usuário pode ocultar as ligações internas se desejar uma visualizacao mais limpa, sem alterar o calculo."),
        ("p", "O tamanho dos nós é ajustado automaticamente de acordo com a quantidade de atividades visíveis."),
        ("p", "Também é possível ajustar a posição vertical dos nós para melhorar a leitura do desenho."),
        ("p", "Em exemplos grandes, use o filtro de estações, zoom e o mouse sobre os nós para ler as atividades sem poluir o gráfico."),
        ("h1", "10. Downloads"),
        ("p", "O usuário pode baixar os resultados em Excel e em TXT após rodar o balanceamento."),
    ]

    pages = []
    page_lines = []
    y = 760

    def add_line(text, font="F1", size=10, leading=14):
        nonlocal y, page_lines, pages
        if y < 70:
            pages.append(page_lines)
            page_lines = []
            y = 760
        page_lines.append((text, font, size, y))
        y -= leading

    for kind, text in content_lines:
        if kind == "title":
            add_line(text, "F2", 16, 24)
            add_line("", "F1", 10, 12)
        elif kind == "h1":
            add_line("", "F1", 10, 8)
            add_line(text, "F2", 13, 18)
        elif kind == "h2":
            add_line(text, "F2", 11, 16)
        else:
            for wrapped in wrap_text(text, 92):
                add_line(wrapped, "F1", 10, 14)

    if page_lines:
        pages.append(page_lines)

    objects = []

    def add_object(obj: str) -> int:
        objects.append(obj)
        return len(objects)

    font1 = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font2 = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    page_object_ids = []
    content_object_ids = []

    for page in pages:
        stream_parts = ["BT"]
        for text, font, size, y_pos in page:
            if text == "":
                continue
            stream_parts.append(f"/{font} {size} Tf")
            stream_parts.append(f"50 {y_pos} Td ({pdf_escape(text)}) Tj")
            stream_parts.append(f"-50 {-y_pos} Td")
        stream_parts.append("ET")
        stream = "\n".join(stream_parts)
        content_obj = f"<< /Length {len(stream.encode('latin-1', errors='replace'))} >>\nstream\n{stream}\nendstream"
        content_id = add_object(content_obj)
        content_object_ids.append(content_id)
        page_id = add_object("PLACEHOLDER_PAGE")
        page_object_ids.append(page_id)

    kids = " ".join([f"{pid} 0 R" for pid in page_object_ids])
    pages_id = add_object(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    for index, page_id in enumerate(page_object_ids):
        content_id = content_object_ids[index]
        page_obj = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects[page_id - 1] = page_obj

    pdf = bytearray()
    pdf.extend(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{i} 0 obj\n".encode("latin-1"))
        pdf.extend(obj.encode("latin-1", errors="replace"))
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("latin-1")
    )
    return bytes(pdf)


# ============================================================
# Validacao, grafo e heuristicas
# ============================================================

def build_problem(df: pd.DataFrame) -> Tuple[List[str], Dict[str, float], Dict[str, Set[str]]]:
    df = standardize_input_df(df)

    if df.empty:
        raise ValueError("A tabela está vazia. Informe pelo menos uma atividade.")

    if df["Atividade"].duplicated().any():
        dup = df.loc[df["Atividade"].duplicated(), "Atividade"].tolist()
        raise ValueError(f"Há atividades repetidas: {', '.join(dup)}.")

    if df["Tempo"].isna().any() or (df["Tempo"] <= 0).any():
        invalid = df.loc[df["Tempo"].isna() | (df["Tempo"] <= 0), "Atividade"].tolist()
        raise ValueError(
            "Todas as atividades precisam ter tempo numérico maior que zero. "
            f"Verifique: {', '.join(invalid)}."
        )

    activities = df["Atividade"].astype(str).tolist()
    activity_set = set(activities)
    times = {row["Atividade"]: float(row["Tempo"]) for _, row in df.iterrows()}

    predecessors: Dict[str, Set[str]] = {}
    missing_refs = []
    for _, row in df.iterrows():
        act = row["Atividade"]
        preds = set(parse_precedence_cell(row["Precedências"]))
        for pred in preds:
            if pred not in activity_set:
                missing_refs.append((act, pred))
        predecessors[act] = preds

    if missing_refs:
        details = "; ".join([f"{act} cita '{pred}'" for act, pred in missing_refs])
        raise ValueError(f"Há precedências que não existem na lista de atividades: {details}.")

    topological_order(activities, predecessors)
    return activities, times, predecessors


def topological_order(activities: List[str], predecessors: Dict[str, Set[str]]) -> List[str]:
    order_index = {a: i for i, a in enumerate(activities)}
    remaining = set(activities)
    assigned = set()
    order = []

    while remaining:
        available = [a for a in remaining if predecessors[a].issubset(assigned)]
        available = sorted(available, key=lambda a: order_index[a])
        if not available:
            raise ValueError(
                "Foi detectado um ciclo nas precedências. Revise a rede, pois uma atividade "
                "não pode depender direta ou indiretamente dela mesma."
            )
        for act in available:
            order.append(act)
            assigned.add(act)
            remaining.remove(act)
    return order


def build_successors(activities: List[str], predecessors: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    successors = {a: set() for a in activities}
    for act, preds in predecessors.items():
        for pred in preds:
            successors[pred].add(act)
    return successors


def transitive_successors(
    activity: str,
    successors: Dict[str, Set[str]],
    cache: Dict[str, Set[str]],
) -> Set[str]:
    if activity in cache:
        return cache[activity]
    all_succ = set()
    for succ in successors.get(activity, set()):
        all_succ.add(succ)
        all_succ |= transitive_successors(succ, successors, cache)
    cache[activity] = all_succ
    return all_succ


def precedence_levels(activities: List[str], predecessors: Dict[str, Set[str]]) -> Dict[str, int]:
    order = topological_order(activities, predecessors)
    levels = {}
    for act in order:
        if not predecessors[act]:
            levels[act] = 1
        else:
            levels[act] = 1 + max(levels[p] for p in predecessors[act])
    return levels


def analyze_graph(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
) -> Dict:
    successors = build_successors(activities, predecessors)
    cache = {}
    all_successors = {act: transitive_successors(act, successors, cache) for act in activities}
    successor_count = {act: len(all_successors[act]) for act in activities}
    immediate_successor_count = {act: len(successors[act]) for act in activities}
    positional_weight = {
        act: times[act] + sum(times[s] for s in all_successors[act])
        for act in activities
    }
    levels = precedence_levels(activities, predecessors)
    return {
        "successors": successors,
        "all_successors": all_successors,
        "successor_count": successor_count,
        "immediate_successor_count": immediate_successor_count,
        "positional_weight": positional_weight,
        "levels": levels,
    }


def choose_next_task(
    available: List[str],
    heuristic_code: str,
    times: Dict[str, float],
    graph_info: Dict,
) -> str:
    if heuristic_code == "LCR":
        return sorted(
            available,
            key=lambda a: (-times[a], -graph_info["successor_count"][a], -graph_info["positional_weight"][a], a),
        )[0]

    if heuristic_code == "RPW":
        return sorted(
            available,
            key=lambda a: (-graph_info["positional_weight"][a], -graph_info["successor_count"][a], -times[a], a),
        )[0]

    if heuristic_code == "KW":
        return sorted(
            available,
            key=lambda a: (graph_info["levels"][a], -times[a], -graph_info["successor_count"][a], a),
        )[0]

    if heuristic_code == "JWAGON":
        return sorted(
            available,
            key=lambda a: (
                -graph_info["successor_count"][a],
                -graph_info["immediate_successor_count"][a],
                -times[a],
                -graph_info["positional_weight"][a],
                a,
            ),
        )[0]

    return sorted(available)[0]


def validate_cycle_time(times: Dict[str, float], cycle_time: float) -> None:
    if cycle_time <= 0:
        raise ValueError("O tempo de ciclo precisa ser maior que zero.")
    largest_task = max(times, key=times.get)
    largest_time = times[largest_task]
    if largest_time > cycle_time:
        raise ValueError(
            "O tempo de ciclo é menor do que o tempo da maior atividade. "
            f"Com 1 trabalhador por estação, a atividade '{largest_task}' ({largest_time:g}) "
            f"não cabe em uma estação com ciclo {cycle_time:g}."
        )


def construct_solution_by_rule(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    heuristic_code: str,
    graph_info: Dict,
) -> List[Dict]:
    unassigned = set(activities)
    assigned = set()
    stations = []

    while unassigned:
        station_tasks = []
        station_time = 0.0

        while True:
            remaining_time = cycle_time - station_time
            available = [
                a
                for a in unassigned
                if predecessors[a].issubset(assigned) and times[a] <= remaining_time + 1e-9
            ]
            if not available:
                break

            task = choose_next_task(available, heuristic_code, times, graph_info)
            station_tasks.append(task)
            station_time += times[task]
            unassigned.remove(task)
            assigned.add(task)

        if not station_tasks:
            blocked = sorted(unassigned)
            raise ValueError(
                "Não foi possível alocar as atividades restantes. Verifique precedências e tempo de ciclo. "
                f"Atividades bloqueadas: {', '.join(blocked)}."
            )

        stations.append(
            {
                "Estacao": len(stations) + 1,
                "Atividades": station_tasks,
                "Tempo ocupado": station_time,
                "Tempo ocioso": cycle_time - station_time,
                "Utilização (%)": 100 * station_time / cycle_time,
            }
        )

    return stations


def construct_solution_comsoal(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    rng: random.Random,
) -> List[Dict]:
    unassigned = set(activities)
    assigned = set()
    stations = []

    while unassigned:
        station_tasks = []
        station_time = 0.0

        while True:
            remaining_time = cycle_time - station_time
            candidates = [
                a
                for a in unassigned
                if predecessors[a].issubset(assigned) and times[a] <= remaining_time + 1e-9
            ]
            if not candidates:
                break
            task = rng.choice(sorted(candidates))
            station_tasks.append(task)
            station_time += times[task]
            unassigned.remove(task)
            assigned.add(task)

        if not station_tasks:
            blocked = sorted(unassigned)
            raise ValueError(
                "Não foi possível alocar as atividades restantes pelo COMSOAL. "
                f"Atividades bloqueadas: {', '.join(blocked)}."
            )

        stations.append(
            {
                "Estacao": len(stations) + 1,
                "Atividades": station_tasks,
                "Tempo ocupado": station_time,
                "Tempo ocioso": cycle_time - station_time,
                "Utilização (%)": 100 * station_time / cycle_time,
            }
        )

    return stations


def solution_score(stations: List[Dict], cycle_time: float) -> Tuple[int, float, float]:
    smoothness = math.sqrt(sum((cycle_time - st["Tempo ocupado"]) ** 2 for st in stations))
    max_idle = max(st["Tempo ocioso"] for st in stations)
    return len(stations), smoothness, max_idle


def finalize_result(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    stations: List[Dict],
    graph_info: Dict,
    heuristic_code: str,
    comsoal_iterations: int = 0,
    random_seed: int = 0,
) -> Dict:
    total_time = sum(times.values())
    number_stations = len(stations)
    theoretical_min = math.ceil(total_time / cycle_time)
    total_available_time = number_stations * cycle_time
    idle_time = total_available_time - total_time
    efficiency = total_time / total_available_time if total_available_time else 0
    balance_delay = 1 - efficiency
    smoothness_index = math.sqrt(sum((cycle_time - st["Tempo ocupado"]) ** 2 for st in stations))

    assignment = {}
    task_order = {}
    for st in stations:
        for idx, task in enumerate(st["Atividades"], start=1):
            assignment[task] = st["Estacao"]
            task_order[task] = idx

    if heuristic_code == "LCR":
        priority = {act: times[act] for act in activities}
        priority_label = "Tempo de operação"
    elif heuristic_code == "RPW":
        priority = graph_info["positional_weight"]
        priority_label = "Peso posicional"
    elif heuristic_code == "KW":
        priority = graph_info["levels"]
        priority_label = "Coluna de precedência"
    elif heuristic_code == "JWAGON":
        priority = graph_info["successor_count"]
        priority_label = "Número de sucessores"
    else:
        priority = {act: 0 for act in activities}
        priority_label = "Sorteio COMSOAL"

    return {
        "stations": stations,
        "assignment": assignment,
        "task_order": task_order,
        "priority": priority,
        "priority_label": priority_label,
        "graph_info": graph_info,
        "heuristic_code": heuristic_code,
        "comsoal_iterations": comsoal_iterations,
        "random_seed": random_seed,
        "metrics": {
            "Tempo total das atividades": total_time,
            "Tempo de ciclo": cycle_time,
            "Número de estações": number_stations,
            "Mínimo teórico de estações": theoretical_min,
            "Tempo ocioso total": idle_time,
            "Eficiência da linha (%)": 100 * efficiency,
            "Atraso de balanceamento (%)": 100 * balance_delay,
            "Índice de suavidade": smoothness_index,
        },
    }


def balance_line(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    heuristic_code: str,
    comsoal_iterations: int = 200,
    random_seed: int = 42,
) -> Dict:
    validate_cycle_time(times, cycle_time)
    graph_info = analyze_graph(activities, times, predecessors)

    if heuristic_code == "COMSOAL":
        best_stations = None
        best_score = None
        iterations = max(1, int(comsoal_iterations))
        base_rng = random.Random(int(random_seed))
        for _ in range(iterations):
            rng = random.Random(base_rng.randint(0, 10**9))
            candidate = construct_solution_comsoal(activities, times, predecessors, cycle_time, rng)
            score = solution_score(candidate, cycle_time)
            if best_score is None or score < best_score:
                best_score = score
                best_stations = candidate
        return finalize_result(
            activities,
            times,
            predecessors,
            cycle_time,
            best_stations,
            graph_info,
            heuristic_code,
            comsoal_iterations=iterations,
            random_seed=int(random_seed),
        )

    stations = construct_solution_by_rule(
        activities,
        times,
        predecessors,
        cycle_time,
        heuristic_code,
        graph_info,
    )
    return finalize_result(
        activities,
        times,
        predecessors,
        cycle_time,
        stations,
        graph_info,
        heuristic_code,
    )


# ============================================================
# Visualizacoes e exportacao
# ============================================================

def make_interactive_precedence_html(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    assignment: Dict[str, int],
    stations: List[Dict],
    show_internal_edges: bool = True,
    selected_stations: List[int] = None,
    show_labels: bool = True,
) -> Tuple[str, int]:
    """Cria um diagrama interativo com nós arrastáveis.

    O desenho usa colunas por estação. O usuário pode clicar em uma atividade e
    arrastar para cima ou para baixo. As setas acompanham o movimento no próprio
    navegador.
    """
    if selected_stations is None or len(selected_stations) == 0:
        selected_stations = [st["Estacao"] for st in stations]

    selected_station_set = set(int(s) for s in selected_stations)
    visible_stations = [st for st in stations if st["Estacao"] in selected_station_set]
    visible_stations = sorted(visible_stations, key=lambda item: item["Estacao"])

    topo_order = topological_order(activities, predecessors)
    visible_activities = [a for a in topo_order if assignment.get(a) in selected_station_set]

    if not visible_activities or not visible_stations:
        empty_html = """
        <div style='font-family: Arial, sans-serif; padding: 20px; color: #475569;'>
            Selecione ao menos uma estação para exibir o diagrama.
        </div>
        """
        return empty_html, 180

    n_visible = len(visible_activities)
    station_tasks = {
        st["Estacao"]: [a for a in visible_activities if assignment.get(a) == st["Estacao"]]
        for st in visible_stations
    }
    max_tasks_station = max(max(len(tasks), 1) for tasks in station_tasks.values())

    if n_visible <= 40:
        node_size = 30
        font_size = 14
        y_gap = 78
        height = max(620, max_tasks_station * y_gap + 190)
    elif n_visible <= 100:
        node_size = 23
        font_size = 11
        y_gap = 54
        height = max(720, max_tasks_station * y_gap + 190)
    elif n_visible <= 250:
        node_size = 16
        font_size = 9
        y_gap = 34
        height = max(850, min(1300, max_tasks_station * y_gap + 190))
    else:
        node_size = 10
        font_size = 7
        y_gap = 22
        height = max(950, min(1550, max_tasks_station * y_gap + 190))

    if not show_labels:
        font_size = max(1, font_size - 2)

    station_gap = 270 if n_visible <= 120 else 230
    station_width = int(station_gap * 0.72)
    station_x = {st["Estacao"]: idx * station_gap for idx, st in enumerate(visible_stations)}

    nodes = []
    original_x = {}
    station_defs = []

    for st in visible_stations:
        station_number = st["Estacao"]
        color = STATION_COLORS[(station_number - 1) % len(STATION_COLORS)]
        station_defs.append(
            {
                "number": station_number,
                "label": f"Estação {station_number}",
                "x": station_x[station_number],
                "color": color,
            }
        )

    for st in visible_stations:
        station_number = st["Estacao"]
        tasks = station_tasks[station_number]
        color = STATION_COLORS[(station_number - 1) % len(STATION_COLORS)]
        k = len(tasks)
        for local_idx, act in enumerate(tasks):
            y = (local_idx - (k - 1) / 2) * y_gap
            x = station_x[station_number]
            original_x[act] = x
            preds_text = ", ".join(sorted(predecessors[act])) if predecessors[act] else "nenhuma"
            label = act if show_labels else ""
            node_title = (
                f"Atividade: {html.escape(str(act))}<br>"
                f"Tempo: {times[act]:g}<br>"
                f"Estação: {station_number}<br>"
                f"Precedências: {html.escape(preds_text)}"
            )
            nodes.append(
                {
                    "id": act,
                    "label": label,
                    "title": node_title,
                    "x": x,
                    "y": y,
                    "size": node_size,
                    "color": {
                        "background": color,
                        "border": "#111827",
                        "highlight": {"background": color, "border": "#020617"},
                    },
                    "font": {"size": font_size, "color": "#ffffff", "face": "Arial"},
                    "borderWidth": 2,
                    "shape": "circle",
                    "mass": 1,
                }
            )

    edges = []
    for act in visible_activities:
        for pred in sorted(predecessors[act]):
            if pred not in original_x:
                continue
            if not show_internal_edges and assignment.get(pred) == assignment.get(act):
                continue
            edges.append(
                {
                    "from": pred,
                    "to": act,
                    "arrows": "to",
                    "color": {"color": "#475569", "highlight": "#0f172a"},
                    "width": 1.2,
                }
            )

    container_height = int(height)
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    station_defs_json = json.dumps(station_defs, ensure_ascii=False)
    original_x_json = json.dumps(original_x, ensure_ascii=False)

    html_doc = f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #ffffff; }}
    #diagram-wrapper {{ width: 100%; }}
    #diagram-help {{
        font-size: 13px;
        color: #475569;
        padding: 6px 4px 10px 4px;
    }}
    #network {{
        height: {container_height}px;
        width: 100%;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        background: #ffffff;
    }}
</style>
</head>
<body>
<div id="diagram-wrapper">
    <div id="diagram-help">Clique em uma atividade e arraste para cima ou para baixo. Use a roda do mouse para aproximar ou afastar.</div>
    <div id="network"></div>
</div>
<script>
const nodes = new vis.DataSet({nodes_json});
const edges = new vis.DataSet({edges_json});
const stationDefs = {station_defs_json};
const originalX = {original_x_json};
const stationWidth = {station_width};
const container = document.getElementById('network');
const data = {{ nodes: nodes, edges: edges }};
const options = {{
    autoResize: true,
    layout: {{ improvedLayout: false }},
    physics: {{ enabled: false }},
    interaction: {{
        dragNodes: true,
        dragView: true,
        zoomView: true,
        hover: true,
        tooltipDelay: 80,
        multiselect: true,
        navigationButtons: true,
        keyboard: true
    }},
    nodes: {{
        shape: 'circle',
        chosen: true
    }},
    edges: {{
        arrows: {{ to: {{ enabled: true, scaleFactor: 0.75 }} }},
        smooth: {{ enabled: true, type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.35 }},
        selectionWidth: 2,
        hoverWidth: 2
    }}
}};
const network = new vis.Network(container, data, options);

network.on('beforeDrawing', function(ctx) {{
    const topLeft = network.DOMtoCanvas({{x: 0, y: 0}});
    const bottomRight = network.DOMtoCanvas({{x: container.clientWidth, y: container.clientHeight}});
    ctx.save();
    stationDefs.forEach(function(st) {{
        ctx.globalAlpha = 0.08;
        ctx.fillStyle = st.color;
        ctx.fillRect(st.x - stationWidth / 2, topLeft.y, stationWidth, bottomRight.y - topLeft.y);
        ctx.globalAlpha = 1;
        ctx.fillStyle = '#475569';
        ctx.textAlign = 'center';
        ctx.font = '16px Arial';
        ctx.fillText(st.label, st.x, bottomRight.y - 22);
    }});
    ctx.restore();
}});

network.on('dragging', function(params) {{
    if (!params.nodes || params.nodes.length === 0) {{ return; }}
    params.nodes.forEach(function(id) {{
        const current = nodes.get(id);
        nodes.update({{id: id, x: originalX[id], y: current.y}});
    }});
}});

network.on('dragEnd', function(params) {{
    if (!params.nodes || params.nodes.length === 0) {{ return; }}
    params.nodes.forEach(function(id) {{
        const current = nodes.get(id);
        nodes.update({{id: id, x: originalX[id], y: current.y}});
    }});
}});

setTimeout(function() {{ network.fit({{animation: false}}); }}, 250);
</script>
</body>
</html>
"""
    return html_doc, container_height + 56


def make_gantt_df(stations: List[Dict], times: Dict[str, float]) -> pd.DataFrame:
    rows = []
    for st in stations:
        current = 0.0
        for task in st["Atividades"]:
            start = current
            finish = current + times[task]
            rows.append(
                {
                    "Estação": f"E{st['Estacao']}",
                    "Atividade": task,
                    "Inicio no ciclo": start,
                    "Fim no ciclo": finish,
                    "Duracao": times[task],
                }
            )
            current = finish
    return pd.DataFrame(rows)


def create_gantt_chart(gantt_df: pd.DataFrame, cycle_time: float):
    if gantt_df.empty:
        return None

    fig = go.Figure()
    for _, row in gantt_df.iterrows():
        fig.add_bar(
            y=[row["Estação"]],
            x=[row["Duracao"]],
            base=[row["Inicio no ciclo"]],
            orientation="h",
            text=[row["Atividade"]],
            textposition="inside",
            name=row["Atividade"],
            hovertemplate=(
                "Estação: %{y}<br>"
                "Atividade: " + str(row["Atividade"]) + "<br>"
                "Inicio: " + f"{row['Inicio no ciclo']:g}" + "<br>"
                "Fim: " + f"{row['Fim no ciclo']:g}" + "<br>"
                "Duração: " + f"{row['Duracao']:g}" + "<extra></extra>"
            ),
        )

    fig.update_layout(
        title="Distribuição das atividades por estação",
        barmode="stack",
        showlegend=False,
        height=140 + 60 * gantt_df["Estação"].nunique(),
        xaxis_title="Tempo dentro do ciclo",
        yaxis_title="Estação",
    )
    fig.update_xaxes(range=[0, cycle_time])
    fig.update_yaxes(autorange="reversed")
    return fig


def build_output_tables(
    df_input: pd.DataFrame,
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    result: Dict,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    graph_info = result["graph_info"]
    task_rows = []
    for act in df_input["Atividade"].tolist():
        task_rows.append(
            {
                "Atividade": act,
                "Tempo": times[act],
                "Precedências": ", ".join(sorted(predecessors[act])),
                "Estação": result["assignment"][act],
                "Ordem na estação": result["task_order"][act],
                result["priority_label"]: result["priority"][act],
                "Sucessores imediatos": graph_info["immediate_successor_count"][act],
                "Sucessores totais": graph_info["successor_count"][act],
                "Peso posicional": graph_info["positional_weight"][act],
                "Nível de precedência": graph_info["levels"][act],
                "Lista de sucessores": ", ".join(sorted(graph_info["all_successors"][act])),
            }
        )

    tasks_df = pd.DataFrame(task_rows).sort_values(
        ["Estação", "Ordem na estação"]
    ).reset_index(drop=True)

    stations_df = pd.DataFrame(result["stations"]).rename(columns={"Estacao": "Estação"})
    stations_df["Atividades"] = stations_df["Atividades"].apply(lambda x: ", ".join(x))
    stations_df["Tempo ocupado"] = stations_df["Tempo ocupado"].round(4)
    stations_df["Tempo ocioso"] = stations_df["Tempo ocioso"].round(4)
    stations_df["Utilização (%)"] = stations_df["Utilização (%)"].round(2)

    metrics_df = pd.DataFrame(
        [{"Métrica": k, "Valor": v} for k, v in result["metrics"].items()]
    )
    metrics_df["Valor"] = metrics_df["Valor"].apply(
        lambda x: round(x, 4) if isinstance(x, float) else x
    )

    return tasks_df, stations_df, metrics_df


def to_excel_bytes(
    tasks_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    gantt_df: pd.DataFrame,
    heuristic_label: str,
    result: Dict,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        metrics_df.to_excel(writer, index=False, sheet_name="Métricas")
        stations_df.to_excel(writer, index=False, sheet_name="Estações")
        tasks_df.to_excel(writer, index=False, sheet_name="Atividades")
        gantt_df.to_excel(writer, index=False, sheet_name="Gráfico_Estações")

        info_rows = [
            {"Campo": "Heurística utilizada", "Valor": heuristic_label},
            {"Campo": "Observação", "Valor": "Resultado heurístico. Não garante solução ótima global."},
            {"Campo": "Restrição", "Valor": "Modelo com 1 trabalhador por estação."},
        ]
        if result["heuristic_code"] == "COMSOAL":
            info_rows.append({"Campo": "Tentativas COMSOAL", "Valor": result["comsoal_iterations"]})
            info_rows.append({"Campo": "Semente aleatória", "Valor": result["random_seed"]})
        pd.DataFrame(info_rows).to_excel(writer, index=False, sheet_name="Info")

        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for column_cells in ws.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter
                for cell in column_cells:
                    if cell.value is not None:
                        max_length = max(max_length, len(str(cell.value)))
                ws.column_dimensions[column_letter].width = min(max_length + 2, 55)

    output.seek(0)
    return output.getvalue()


def to_txt_report(
    tasks_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    heuristic_label: str,
    result: Dict,
) -> str:
    lines = []
    lines.append("RELATÓRIO DE BALANCEAMENTO DE LINHA")
    lines.append(f"Heurística utilizada: {heuristic_label}")
    lines.append("Restrição: 1 trabalhador por estação")
    if result["heuristic_code"] == "COMSOAL":
        lines.append(f"Tentativas COMSOAL: {result['comsoal_iterations']}")
        lines.append(f"Semente aleatória: {result['random_seed']}")
    lines.append("")
    lines.append("MÉTRICAS")
    for _, row in metrics_df.iterrows():
        lines.append(f"- {row['Métrica']}: {row['Valor']}")
    lines.append("")
    lines.append("ESTAÇÕES")
    for _, row in stations_df.iterrows():
        lines.append(
            f"E{row['Estação']}: {row['Atividades']} | "
            f"tempo ocupado={row['Tempo ocupado']} | "
            f"tempo ocioso={row['Tempo ocioso']} | "
            f"utilização={row['Utilização (%)']}%"
        )
    lines.append("")
    lines.append("ATIVIDADES")
    lines.append(tasks_df.to_string(index=False))
    return "\n".join(lines)


# ============================================================
# Interface
# ============================================================

if "manual_df" not in st.session_state:
    st.session_state["manual_df"] = SAMPLE_DATA.copy()

if "manual_editor_version" not in st.session_state:
    st.session_state["manual_editor_version"] = 0

with st.sidebar:
    st.header("Parâmetros")

    cycle_time = st.number_input(
        "Tempo de ciclo",
        min_value=0.01,
        value=40.0,
        step=1.0,
        help="Tempo máximo disponível em cada estação.",
    )

    heuristic_label = st.selectbox(
        "Heurística",
        list(HEURISTIC_OPTIONS.keys()),
        help="A heurística define a regra de prioridade para escolher atividades elegíveis.",
        key="heuristic_choice",
    )

    if "previous_heuristic_choice" not in st.session_state:
        st.session_state["previous_heuristic_choice"] = heuristic_label
    elif st.session_state["previous_heuristic_choice"] != heuristic_label:
        st.session_state["previous_heuristic_choice"] = heuristic_label
        reset_outputs_and_go_home()
        st.rerun()

    heuristic_code = HEURISTIC_OPTIONS[heuristic_label]

    comsoal_iterations = 200
    random_seed = 42
    if heuristic_code == "COMSOAL":
        comsoal_iterations = st.number_input(
            "Tentativas COMSOAL",
            min_value=1,
            max_value=10000,
            value=500,
            step=50,
            help="Quantidade de soluções aleatórias testadas.",
        )
        random_seed = st.number_input(
            "Semente aleatória",
            min_value=0,
            max_value=999999,
            value=42,
            step=1,
            help="Use a mesma semente para repetir o resultado.",
        )

    st.divider()
    st.download_button(
        "Help: baixar manual em PDF",
        data=make_manual_pdf_bytes(),
        file_name="manual_usuario_balanceamento_linha.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

with st.expander("Como preencher os dados", expanded=True):
    st.markdown(
        """
        A tabela precisa ter três colunas:

        - **Atividade**: código ou nome da atividade. Exemplo: `A`, `B`, `Corte`, `Montagem`.
        - **Tempo**: duração da atividade. Use número maior que zero.
        - **Precedências**: atividades que precisam vir antes. Separe por vírgula. Se não houver predecessoras, deixe em branco.

        Exemplo:

        ```text
        Atividade;Tempo;Precedências
        A;20;
        B;6;A
        C;5;B
        E;15;C, D
        ```
        """
    )

input_mode = st.radio(
    "Forma de entrada",
    ["Digitar ou editar tabela", "Importar TXT", "Importar Excel"],
    horizontal=True,
    key="input_mode",
)

df_input = None

if input_mode == "Digitar ou editar tabela":
    c1, c2, c3 = st.columns([1, 1, 4])
    with c1:
        if st.button("Carregar exemplo", use_container_width=True):
            st.session_state["manual_df"] = SAMPLE_DATA.copy()
            st.session_state["manual_editor_version"] += 1
            st.rerun()
    with c2:
        if st.button("Limpar tabela", use_container_width=True):
            st.session_state["manual_df"] = EMPTY_DATA.copy()
            st.session_state["manual_editor_version"] += 1
            st.rerun()

    st.session_state["manual_df"] = standardize_input_df(st.session_state["manual_df"])

    df_input = st.data_editor(
        st.session_state["manual_df"],
        num_rows="dynamic",
        use_container_width=True,
        key=f"manual_editor_{st.session_state['manual_editor_version']}",
        column_config={
            "Atividade": st.column_config.TextColumn("Atividade", required=False),
            "Tempo": st.column_config.NumberColumn("Tempo", min_value=0.01, step=1.0, required=False),
            "Precedências": st.column_config.TextColumn("Precedências"),
        },
    )
    st.session_state["manual_df"] = df_input.copy()

elif input_mode == "Importar TXT":
    st.download_button(
        "Baixar modelo TXT",
        data=example_txt_bytes(),
        file_name="exemplo_atividades.txt",
        mime="text/plain",
        use_container_width=True,
    )
    uploaded_txt = st.file_uploader(
        "Importe um arquivo TXT no formato do modelo",
        type=["txt", "csv"],
    )
    if uploaded_txt is not None:
        try:
            df_input = parse_txt(uploaded_txt)
            st.success("Arquivo TXT carregado com sucesso.")
            st.dataframe(df_input, use_container_width=True)
        except Exception as exc:
            st.error(f"Erro ao ler o arquivo: {exc}")

elif input_mode == "Importar Excel":
    st.download_button(
        "Baixar modelo Excel",
        data=example_excel_bytes(),
        file_name="exemplo_atividades.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    uploaded_xlsx = st.file_uploader(
        "Importe uma planilha Excel no formato do modelo",
        type=["xlsx", "xls"],
    )
    if uploaded_xlsx is not None:
        try:
            df_input = parse_excel(uploaded_xlsx)
            st.success("Planilha carregada com sucesso.")
            st.dataframe(df_input, use_container_width=True)
        except Exception as exc:
            st.error(f"Erro ao ler a planilha: {exc}")

run = st.button("Rodar balanceamento", type="primary", use_container_width=True)

if run:
    if df_input is None or standardize_input_df(df_input).empty:
        st.warning("Informe os dados manualmente ou importe um arquivo antes de rodar.")
        st.session_state.pop("last_solution", None)
    else:
        try:
            df_clean = standardize_input_df(df_input)
            activities, times, predecessors = build_problem(df_clean)
            result = balance_line(
                activities,
                times,
                predecessors,
                cycle_time,
                heuristic_code,
                comsoal_iterations=int(comsoal_iterations),
                random_seed=int(random_seed),
            )
            tasks_df, stations_df, metrics_df = build_output_tables(
                df_clean, times, predecessors, result
            )
            gantt_df = make_gantt_df(result["stations"], times)
            st.session_state["last_solution"] = {
                "df_clean": df_clean,
                "activities": activities,
                "times": times,
                "predecessors": predecessors,
                "result": result,
                "tasks_df": tasks_df,
                "stations_df": stations_df,
                "metrics_df": metrics_df,
                "gantt_df": gantt_df,
                "heuristic_label": heuristic_label,
            }
            for key in ["station_filter_diagram", "show_internal_edges_diagram", "show_labels_diagram"]:
                st.session_state.pop(key, None)
            st.session_state["result_page"] = "Estações"
            st.success("Balanceamento concluído.")
        except Exception as exc:
            st.session_state.pop("last_solution", None)
            st.error(str(exc))

if "last_solution" in st.session_state:
    data = st.session_state["last_solution"]
    activities = data["activities"]
    times = data["times"]
    predecessors = data["predecessors"]
    result = data["result"]
    tasks_df = data["tasks_df"]
    stations_df = data["stations_df"]
    metrics_df = data["metrics_df"]
    gantt_df = data["gantt_df"]
    heuristic_label = data["heuristic_label"]

    st.subheader("Resumo")
    m = result["metrics"]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Estações", int(m["Número de estações"]))
    col2.metric("Mínimo teórico", int(m["Mínimo teórico de estações"]))
    col3.metric("Eficiência", f"{m['Eficiência da linha (%)']:.2f}%")
    col4.metric("Tempo ocioso total", f"{m['Tempo ocioso total']:.2f}")

    st.info(
        f"Heurística utilizada: **{heuristic_label}**. "
        "Resultado heurístico, sem garantia de ótimo global. Modelo com 1 trabalhador por estação."
    )

    result_pages = ["Estações", "Atividades", "Diagrama de precedências", "Gráfico"]
    if "result_page" not in st.session_state or st.session_state["result_page"] not in result_pages:
        st.session_state["result_page"] = "Estações"

    result_page = st.radio(
        "Página dos resultados",
        result_pages,
        horizontal=True,
        key="result_page",
    )

    if result_page == "Estações":
        st.dataframe(stations_df, use_container_width=True)
        st.dataframe(metrics_df, use_container_width=True)

    elif result_page == "Atividades":
        st.dataframe(tasks_df, use_container_width=True)

    elif result_page == "Diagrama de precedências":
        station_numbers = [st["Estacao"] for st in result["stations"]]
        selected_stations = st.multiselect(
            "Estações exibidas no diagrama",
            options=station_numbers,
            default=station_numbers,
            help="Em problemas grandes, selecione apenas algumas estações para melhorar a leitura.",
            key="station_filter_diagram",
        )
        cdiag1, cdiag2 = st.columns(2)
        with cdiag1:
            show_internal_edges = st.checkbox(
                "Mostrar precedências internas da mesma estação",
                value=True,
                help="Marcado, o diagrama mostra também as relações entre atividades alocadas na mesma estação.",
                key="show_internal_edges_diagram",
            )
        with cdiag2:
            show_labels = st.checkbox(
                "Mostrar rótulos nos nós",
                value=len(activities) <= 80,
                help="Para exemplos muito grandes, deixe desmarcado e use o mouse sobre os nós.",
                key="show_labels_diagram",
            )

        diagram_html, diagram_height = make_interactive_precedence_html(
            activities,
            times,
            predecessors,
            result["assignment"],
            result["stations"],
            show_internal_edges=show_internal_edges,
            selected_stations=selected_stations,
            show_labels=show_labels,
        )
        components.html(diagram_html, height=diagram_height, scrolling=True)

        if not show_internal_edges:
            st.caption(
                "As precedências internas da mesma estação foram ocultadas apenas no desenho. "
                "Elas continuam sendo respeitadas no cálculo."
            )
        if len(activities) >= 120:
            st.caption(
                "Para redes grandes, use zoom, hover e filtro de estações para analisar partes da rede. "
                "Os nós podem ser arrastados para melhorar a leitura."
            )

    elif result_page == "Gráfico":
        fig = create_gantt_chart(gantt_df, m["Tempo de ciclo"])
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Baixar resultados")
    excel_bytes = to_excel_bytes(
        tasks_df,
        stations_df,
        metrics_df,
        gantt_df,
        heuristic_label,
        result,
    )
    txt_report = to_txt_report(tasks_df, stations_df, metrics_df, heuristic_label, result)

    dl1, dl2 = st.columns(2)
    dl1.download_button(
        "Baixar resultado em Excel",
        data=excel_bytes,
        file_name="resultado_balanceamento_linha.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
    dl2.download_button(
        "Baixar relatório em TXT",
        data=txt_report.encode("utf-8"),
        file_name="relatorio_balanceamento_linha.txt",
        mime="text/plain",
        use_container_width=True,
    )
