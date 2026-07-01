import io
import math
import random
import re
from collections import defaultdict
from typing import Dict, List, Set, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# Configuracao da pagina
# ============================================================

st.set_page_config(
    page_title="Balanceamento de Linha",
    page_icon="⚙️",
    layout="wide",
)

st.title("⚙️ Sistema de Balanceamento de Linha")
st.caption(
    "Informe atividades, tempos e precedencias. Escolha uma heuristica e rode o balanceamento por estacoes."
)


# ============================================================
# Dados de exemplo
# ============================================================

SAMPLE_DATA = pd.DataFrame(
    [
        {"Atividade": "A", "Tempo": 20, "Precedencias": ""},
        {"Atividade": "B", "Tempo": 6, "Precedencias": "A"},
        {"Atividade": "C", "Tempo": 5, "Precedencias": "B"},
        {"Atividade": "D", "Tempo": 21, "Precedencias": ""},
        {"Atividade": "E", "Tempo": 15, "Precedencias": "C, D"},
        {"Atividade": "F", "Tempo": 10, "Precedencias": "E"},
        {"Atividade": "G", "Tempo": 35, "Precedencias": ""},
        {"Atividade": "H", "Tempo": 8, "Precedencias": ""},
        {"Atividade": "I", "Tempo": 15, "Precedencias": "F, H"},
        {"Atividade": "J", "Tempo": 5, "Precedencias": "C"},
        {"Atividade": "K", "Tempo": 40, "Precedencias": "G, I, J"},
        {"Atividade": "L", "Tempo": 16, "Precedencias": "K"},
    ]
)

EMPTY_DATA = pd.DataFrame(
    [
        {"Atividade": "", "Tempo": None, "Precedencias": ""},
    ]
)

HEURISTIC_OPTIONS = {
    "Maior Tempo de Operacao (Largest Candidate Rule, LCR)": "LCR",
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
        return pd.DataFrame(columns=["Atividade", "Tempo", "Precedencias"])

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
        "precedencias": "Precedencias",
        "precedencia": "Precedencias",
        "predecessoras": "Precedencias",
        "predecessores": "Precedencias",
        "predecessors": "Precedencias",
        "predecessor": "Precedencias",
    }

    rename = {}
    for col, norm in normalized.items():
        if norm in aliases:
            rename[col] = aliases[norm]

    df = df.rename(columns=rename)

    required = ["Atividade", "Tempo", "Precedencias"]
    for col in required:
        if col not in df.columns:
            df[col] = "" if col != "Tempo" else None

    df = df[required]
    df["Atividade"] = df["Atividade"].apply(normalize_activity)
    df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce")
    df["Precedencias"] = df["Precedencias"].fillna("").astype(str).str.strip()
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
        ("p", "Este sistema monta uma solucao heuristica para o balanceamento de linha com atividades, tempos de operacao e relacoes de precedencia."),
        ("p", "O usuario informa o tempo de ciclo e escolhe uma heuristica. O sistema distribui as atividades em estacoes, calcula metricas e gera tabelas e graficos."),
        ("h1", "2. Hipoteses do modelo"),
        ("p", "O sistema considera uma linha com 1 trabalhador por estacao."),
        ("p", "As atividades nao podem ser divididas entre estacoes."),
        ("p", "Cada atividade tem tempo deterministico e maior que zero."),
        ("p", "As precedencias precisam formar uma rede sem ciclos."),
        ("p", "Uma atividade pode ficar na mesma estacao de sua predecessora, desde que a ordem interna seja respeitada."),
        ("p", "O tempo de cada atividade precisa ser menor ou igual ao tempo de ciclo."),
        ("p", "Os metodos sao heuristicos. Portanto, eles buscam uma boa solucao, mas nao garantem o otimo global."),
        ("h1", "3. Formato dos dados"),
        ("p", "A tabela precisa ter as colunas Atividade, Tempo e Precedencias."),
        ("p", "Em Precedencias, informe as atividades predecessoras separadas por virgula. Se nao houver predecessora, deixe em branco."),
        ("p", "Exemplo: A com tempo 20 e sem precedencia. B com tempo 6 e precedencia A. E com tempo 15 e precedencias C, D."),
        ("h1", "4. Entrada manual"),
        ("p", "Use a opcao Digitar ou editar tabela. O sistema ja abre com um exemplo preenchido. O botao Limpar tabela apaga o exemplo para permitir inserir novos dados."),
        ("h1", "5. Importacao por TXT"),
        ("p", "Use a opcao Importar TXT. Baixe o modelo TXT, edite o arquivo e importe novamente. O separador recomendado e ponto e virgula."),
        ("h1", "6. Importacao por Excel"),
        ("p", "Use a opcao Importar Excel. Baixe o modelo Excel, edite a planilha e importe novamente."),
        ("h1", "7. Heuristicas disponiveis"),
        ("h2", "7.1 Maior Tempo de Operacao (Largest Candidate Rule, LCR)"),
        ("p", "Ordena as atividades candidatas pelo maior tempo de operacao. Em cada estacao, seleciona a maior atividade elegivel que ainda cabe no tempo restante."),
        ("p", "A ideia e alocar primeiro atividades longas para reduzir a chance de sobras grandes no fim do balanceamento."),
        ("h2", "7.2 Peso Posicional Ranqueado (RPW/Helgeson-Birnie)"),
        ("p", "Calcula o peso posicional de cada atividade como o tempo da atividade somado aos tempos de todos os seus sucessores diretos e indiretos."),
        ("p", "Em cada estacao, seleciona a atividade elegivel com maior peso posicional que ainda cabe no tempo restante."),
        ("h2", "7.3 Kilbridge-Wester"),
        ("p", "Agrupa as atividades em colunas ou niveis de precedencia. Atividades mais proximas do inicio da rede recebem prioridade antes das atividades de colunas posteriores."),
        ("p", "No app, entre atividades elegiveis, o metodo prioriza a menor coluna. Em caso de empate, usa maior tempo e maior numero de sucessores."),
        ("h2", "7.4 J-Wagon"),
        ("p", "Prioriza atividades com maior numero de sucessores na rede de precedencia. A logica e antecipar atividades que liberam mais trabalho posterior."),
        ("p", "No app, o desempate usa maior numero de sucessores imediatos, maior tempo de operacao e maior peso posicional."),
        ("h2", "7.5 COMSOAL"),
        ("p", "Constroi solucoes aleatorias viaveis. Em cada passo, forma uma lista de atividades elegiveis que respeitam as precedencias e cabem no tempo restante da estacao."),
        ("p", "O metodo sorteia uma atividade dessa lista, completa a estacao e repete o processo. O app executa varias tentativas e guarda a melhor solucao encontrada."),
        ("p", "A semente aleatoria permite repetir o mesmo resultado quando necessario."),
        ("h1", "8. Resultados"),
        ("p", "O sistema mostra a quantidade de estacoes, minimo teorico, eficiencia, tempo ocioso, atraso de balanceamento e indice de suavidade."),
        ("p", "Tambem gera a tabela de estacoes, a tabela de atividades, o diagrama de precedencias por estacao e o grafico de ocupacao por estacao."),
        ("h1", "9. Diagrama de precedencias por estacao"),
        ("p", "O diagrama usa cores para identificar as estacoes. Para facilitar a leitura, a visualizacao principal mostra as ligacoes entre estacoes e omite ligacoes internas da mesma estacao."),
        ("p", "Mesmo quando uma ligacao interna nao aparece no desenho, a precedencia continua sendo respeitada pelo calculo."),
        ("h1", "10. Downloads"),
        ("p", "O usuario pode baixar os resultados em Excel e em TXT apos rodar o balanceamento."),
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
        raise ValueError("A tabela esta vazia. Informe pelo menos uma atividade.")

    if df["Atividade"].duplicated().any():
        dup = df.loc[df["Atividade"].duplicated(), "Atividade"].tolist()
        raise ValueError(f"Ha atividades repetidas: {', '.join(dup)}.")

    if df["Tempo"].isna().any() or (df["Tempo"] <= 0).any():
        invalid = df.loc[df["Tempo"].isna() | (df["Tempo"] <= 0), "Atividade"].tolist()
        raise ValueError(
            "Todas as atividades precisam ter tempo numerico maior que zero. "
            f"Verifique: {', '.join(invalid)}."
        )

    activities = df["Atividade"].astype(str).tolist()
    activity_set = set(activities)
    times = {row["Atividade"]: float(row["Tempo"]) for _, row in df.iterrows()}

    predecessors: Dict[str, Set[str]] = {}
    missing_refs = []
    for _, row in df.iterrows():
        act = row["Atividade"]
        preds = set(parse_precedence_cell(row["Precedencias"]))
        for pred in preds:
            if pred not in activity_set:
                missing_refs.append((act, pred))
        predecessors[act] = preds

    if missing_refs:
        details = "; ".join([f"{act} cita '{pred}'" for act, pred in missing_refs])
        raise ValueError(f"Ha precedencias que nao existem na lista de atividades: {details}.")

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
                "Foi detectado um ciclo nas precedencias. Revise a rede, pois uma atividade "
                "nao pode depender direta ou indiretamente dela mesma."
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
            "O tempo de ciclo e menor do que o tempo da maior atividade. "
            f"Com 1 trabalhador por estacao, a atividade '{largest_task}' ({largest_time:g}) "
            f"nao cabe em uma estacao com ciclo {cycle_time:g}."
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
                "Nao foi possivel alocar as atividades restantes. Verifique precedencias e tempo de ciclo. "
                f"Atividades bloqueadas: {', '.join(blocked)}."
            )

        stations.append(
            {
                "Estacao": len(stations) + 1,
                "Atividades": station_tasks,
                "Tempo ocupado": station_time,
                "Tempo ocioso": cycle_time - station_time,
                "Utilizacao (%)": 100 * station_time / cycle_time,
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
                "Nao foi possivel alocar as atividades restantes pelo COMSOAL. "
                f"Atividades bloqueadas: {', '.join(blocked)}."
            )

        stations.append(
            {
                "Estacao": len(stations) + 1,
                "Atividades": station_tasks,
                "Tempo ocupado": station_time,
                "Tempo ocioso": cycle_time - station_time,
                "Utilizacao (%)": 100 * station_time / cycle_time,
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
        priority_label = "Tempo de operacao"
    elif heuristic_code == "RPW":
        priority = graph_info["positional_weight"]
        priority_label = "Peso posicional"
    elif heuristic_code == "KW":
        priority = graph_info["levels"]
        priority_label = "Coluna de precedencia"
    elif heuristic_code == "JWAGON":
        priority = graph_info["successor_count"]
        priority_label = "Numero de sucessores"
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
            "Numero de estacoes": number_stations,
            "Minimo teorico de estacoes": theoretical_min,
            "Tempo ocioso total": idle_time,
            "Eficiencia da linha (%)": 100 * efficiency,
            "Atraso de balanceamento (%)": 100 * balance_delay,
            "Indice de suavidade": smoothness_index,
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

def make_station_precedence_chart(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    assignment: Dict[str, int],
    stations: List[Dict],
    show_internal_edges: bool = False,
):
    levels = precedence_levels(activities, predecessors)
    nstations = len(stations)

    position = {}
    same_cell_count = defaultdict(int)
    same_cell_index = defaultdict(int)
    for act in activities:
        key = (assignment[act], levels[act])
        same_cell_count[key] += 1

    for st in stations:
        station_number = st["Estacao"]
        tasks = sorted(st["Atividades"], key=lambda a: (levels[a], st["Atividades"].index(a)))
        for task in tasks:
            key = (station_number, levels[task])
            idx = same_cell_index[key]
            count = same_cell_count[key]
            same_cell_index[key] += 1
            offset = 0 if count == 1 else (idx - (count - 1) / 2) * 0.18
            x = levels[task]
            y = nstations - station_number + 1 + offset
            position[task] = (x, y)

    fig = go.Figure()

    for act, preds in predecessors.items():
        for pred in sorted(preds):
            if not show_internal_edges and assignment.get(pred) == assignment.get(act):
                continue
            x1, y1 = position[pred]
            x2, y2 = position[act]
            fig.add_annotation(
                x=x2,
                y=y2,
                ax=x1,
                ay=y1,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                text="",
                showarrow=True,
                arrowhead=3,
                arrowsize=1,
                arrowwidth=1.4,
                arrowcolor="#475569",
                standoff=20,
                startstandoff=20,
            )

    for st in stations:
        station_number = st["Estacao"]
        tasks = st["Atividades"]
        color = STATION_COLORS[(station_number - 1) % len(STATION_COLORS)]
        x_values = [position[t][0] for t in tasks]
        y_values = [position[t][1] for t in tasks]
        text_values = [f"{t}<br>{times[t]:g}" for t in tasks]
        hover_values = [
            f"Atividade: {t}<br>Tempo: {times[t]:g}<br>Estacao: {station_number}<br>Precedencias: {', '.join(sorted(predecessors[t])) if predecessors[t] else 'nenhuma'}"
            for t in tasks
        ]
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="markers+text",
                text=text_values,
                textposition="middle center",
                hovertext=hover_values,
                hoverinfo="text",
                marker=dict(
                    size=54,
                    color=color,
                    line=dict(color="#111827", width=1.5),
                ),
                textfont=dict(color="white", size=12),
                name=f"Estacao {station_number}",
            )
        )

    max_level = max(levels.values()) if levels else 1
    fig.update_layout(
        title="Diagrama de precedencias por estacao",
        height=max(520, 120 * nstations),
        margin=dict(l=50, r=30, t=70, b=50),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(
        title="Nivel de precedencia",
        range=[0.5, max_level + 0.7],
        dtick=1,
        showgrid=True,
        gridcolor="#e5e7eb",
        zeroline=False,
    )
    fig.update_yaxes(
        title="Estacao",
        tickmode="array",
        tickvals=[nstations - st["Estacao"] + 1 for st in stations],
        ticktext=[f"Estacao {st['Estacao']}" for st in stations],
        range=[0.3, nstations + 0.7],
        showgrid=True,
        gridcolor="#f1f5f9",
        zeroline=False,
    )
    return fig


def make_gantt_df(stations: List[Dict], times: Dict[str, float]) -> pd.DataFrame:
    rows = []
    for st in stations:
        current = 0.0
        for task in st["Atividades"]:
            start = current
            finish = current + times[task]
            rows.append(
                {
                    "Estacao": f"E{st['Estacao']}",
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
            y=[row["Estacao"]],
            x=[row["Duracao"]],
            base=[row["Inicio no ciclo"]],
            orientation="h",
            text=[row["Atividade"]],
            textposition="inside",
            name=row["Atividade"],
            hovertemplate=(
                "Estacao: %{y}<br>"
                "Atividade: " + str(row["Atividade"]) + "<br>"
                "Inicio: " + f"{row['Inicio no ciclo']:g}" + "<br>"
                "Fim: " + f"{row['Fim no ciclo']:g}" + "<br>"
                "Duracao: " + f"{row['Duracao']:g}" + "<extra></extra>"
            ),
        )

    fig.update_layout(
        title="Distribuicao das atividades por estacao",
        barmode="stack",
        showlegend=False,
        height=140 + 60 * gantt_df["Estacao"].nunique(),
        xaxis_title="Tempo dentro do ciclo",
        yaxis_title="Estacao",
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
                "Precedencias": ", ".join(sorted(predecessors[act])),
                "Estacao": result["assignment"][act],
                "Ordem na estacao": result["task_order"][act],
                result["priority_label"]: result["priority"][act],
                "Sucessores imediatos": graph_info["immediate_successor_count"][act],
                "Sucessores totais": graph_info["successor_count"][act],
                "Peso posicional": graph_info["positional_weight"][act],
                "Nivel de precedencia": graph_info["levels"][act],
                "Lista de sucessores": ", ".join(sorted(graph_info["all_successors"][act])),
            }
        )

    tasks_df = pd.DataFrame(task_rows).sort_values(
        ["Estacao", "Ordem na estacao"]
    ).reset_index(drop=True)

    stations_df = pd.DataFrame(result["stations"])
    stations_df["Atividades"] = stations_df["Atividades"].apply(lambda x: ", ".join(x))
    stations_df["Tempo ocupado"] = stations_df["Tempo ocupado"].round(4)
    stations_df["Tempo ocioso"] = stations_df["Tempo ocioso"].round(4)
    stations_df["Utilizacao (%)"] = stations_df["Utilizacao (%)"].round(2)

    metrics_df = pd.DataFrame(
        [{"Metrica": k, "Valor": v} for k, v in result["metrics"].items()]
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
        metrics_df.to_excel(writer, index=False, sheet_name="Metricas")
        stations_df.to_excel(writer, index=False, sheet_name="Estacoes")
        tasks_df.to_excel(writer, index=False, sheet_name="Atividades")
        gantt_df.to_excel(writer, index=False, sheet_name="Grafico_Estacoes")

        info_rows = [
            {"Campo": "Heuristica utilizada", "Valor": heuristic_label},
            {"Campo": "Observacao", "Valor": "Resultado heuristico. Nao garante solucao otima global."},
            {"Campo": "Restricao", "Valor": "Modelo com 1 trabalhador por estacao."},
        ]
        if result["heuristic_code"] == "COMSOAL":
            info_rows.append({"Campo": "Tentativas COMSOAL", "Valor": result["comsoal_iterations"]})
            info_rows.append({"Campo": "Semente aleatoria", "Valor": result["random_seed"]})
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
    lines.append("RELATORIO DE BALANCEAMENTO DE LINHA")
    lines.append(f"Heuristica utilizada: {heuristic_label}")
    lines.append("Restricao: 1 trabalhador por estacao")
    if result["heuristic_code"] == "COMSOAL":
        lines.append(f"Tentativas COMSOAL: {result['comsoal_iterations']}")
        lines.append(f"Semente aleatoria: {result['random_seed']}")
    lines.append("")
    lines.append("METRICAS")
    for _, row in metrics_df.iterrows():
        lines.append(f"- {row['Metrica']}: {row['Valor']}")
    lines.append("")
    lines.append("ESTACOES")
    for _, row in stations_df.iterrows():
        lines.append(
            f"E{row['Estacao']}: {row['Atividades']} | "
            f"tempo ocupado={row['Tempo ocupado']} | "
            f"tempo ocioso={row['Tempo ocioso']} | "
            f"utilizacao={row['Utilizacao (%)']}%"
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
        value=47.0,
        step=1.0,
        help="Tempo maximo disponivel em cada estacao.",
    )

    heuristic_label = st.selectbox(
        "Heuristica",
        list(HEURISTIC_OPTIONS.keys()),
        help="A heuristica define a regra de prioridade para escolher atividades elegiveis.",
    )
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
            help="Quantidade de solucoes aleatorias testadas.",
        )
        random_seed = st.number_input(
            "Semente aleatoria",
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
        - **Precedencias**: atividades que precisam vir antes. Separe por vírgula. Se não houver predecessoras, deixe em branco.

        Exemplo:

        ```text
        Atividade;Tempo;Precedencias
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

    df_input = st.data_editor(
        st.session_state["manual_df"],
        num_rows="dynamic",
        use_container_width=True,
        key=f"manual_editor_{st.session_state['manual_editor_version']}",
        column_config={
            "Atividade": st.column_config.TextColumn("Atividade", required=False),
            "Tempo": st.column_config.NumberColumn("Tempo", min_value=0.01, step=1.0, required=False),
            "Precedencias": st.column_config.TextColumn("Precedencias"),
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
            st.success("Balanceamento concluido.")
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
    col1.metric("Estacoes", int(m["Numero de estacoes"]))
    col2.metric("Minimo teorico", int(m["Minimo teorico de estacoes"]))
    col3.metric("Eficiencia", f"{m['Eficiencia da linha (%)']:.2f}%")
    col4.metric("Tempo ocioso total", f"{m['Tempo ocioso total']:.2f}")

    st.info(
        f"Heuristica utilizada: **{heuristic_label}**. "
        "Resultado heuristico, sem garantia de otimo global. Modelo com 1 trabalhador por estacao."
    )

    tab1, tab2, tab3, tab4 = st.tabs(
        ["Estacoes", "Atividades", "Diagrama de precedencias", "Grafico"]
    )

    with tab1:
        st.dataframe(stations_df, use_container_width=True)
        st.dataframe(metrics_df, use_container_width=True)

    with tab2:
        st.dataframe(tasks_df, use_container_width=True)

    with tab3:
        show_internal_edges = st.checkbox(
            "Mostrar tambem precedencias internas da mesma estacao",
            value=False,
            help="Desmarcado, o desenho fica mais parecido com o Flexible Line Balancing, destacando apenas ligacoes entre estacoes.",
        )
        fig_prec = make_station_precedence_chart(
            activities,
            times,
            predecessors,
            result["assignment"],
            result["stations"],
            show_internal_edges=show_internal_edges,
        )
        st.plotly_chart(fig_prec, use_container_width=True)
        if not show_internal_edges:
            st.caption(
                "As precedencias internas da mesma estacao foram omitidas apenas no desenho. "
                "Elas continuam sendo respeitadas no calculo."
            )

    with tab4:
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
        "Baixar relatorio em TXT",
        data=txt_report.encode("utf-8"),
        file_name="relatorio_balanceamento_linha.txt",
        mime="text/plain",
        use_container_width=True,
    )
