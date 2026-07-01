import io
import math
import random
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


APP_DIR = Path(__file__).parent
ASSETS_DIR = APP_DIR / "assets"
TXT_EXAMPLE_PATH = ASSETS_DIR / "exemplo_atividades.txt"
XLSX_EXAMPLE_PATH = ASSETS_DIR / "exemplo_atividades.xlsx"

HEURISTIC_OPTIONS = [
    "Maior Tempo de Operação (Largest Candidate Rule - LCR)",
    "Peso Posicional Ranqueado (Ranked Positional Weight - RPW/Helgeson-Birnie)",
    "Kilbridge-Wester",
    "J-Wagon",
    "COMSOAL",
]

STATION_COLORS = [
    "#22c55e",
    "#3b82f6",
    "#e879f9",
    "#f59e0b",
    "#14b8a6",
    "#ef4444",
    "#8b5cf6",
    "#84cc16",
    "#06b6d4",
    "#f97316",
]


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
# Exemplos e manual em PDF
# ============================================================

def get_default_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Atividade": "A", "Tempo": 21, "Precedencias": ""},
            {"Atividade": "B", "Tempo": 20, "Precedencias": "A"},
            {"Atividade": "C", "Tempo": 6, "Precedencias": "B"},
            {"Atividade": "D", "Tempo": 5, "Precedencias": "C"},
            {"Atividade": "E", "Tempo": 15, "Precedencias": "D"},
            {"Atividade": "F", "Tempo": 35, "Precedencias": ""},
            {"Atividade": "G", "Tempo": 8, "Precedencias": ""},
            {"Atividade": "H", "Tempo": 10, "Precedencias": "E, G"},
            {"Atividade": "I", "Tempo": 15, "Precedencias": "H"},
            {"Atividade": "J", "Tempo": 5, "Precedencias": "D"},
            {"Atividade": "K", "Tempo": 46, "Precedencias": "F, I, J"},
            {"Atividade": "L", "Tempo": 16, "Precedencias": "K"},
        ]
    )


def build_example_txt_bytes() -> bytes:
    df = get_default_data()
    output = io.StringIO()
    df.to_csv(output, index=False, sep=";")
    return output.getvalue().encode("utf-8-sig")


def build_example_xlsx_bytes() -> bytes:
    df = get_default_data()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Atividades")
        ws = writer.sheets["Atividades"]
        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                if cell.value is not None:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[column_letter].width = min(max_length + 2, 45)
    output.seek(0)
    return output.getvalue()


def read_binary_file(path: Path) -> bytes:
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return path.read_bytes()
    return b""


def get_txt_example_bytes() -> bytes:
    file_bytes = read_binary_file(TXT_EXAMPLE_PATH)
    return file_bytes if file_bytes else build_example_txt_bytes()


def get_xlsx_example_bytes() -> bytes:
    file_bytes = read_binary_file(XLSX_EXAMPLE_PATH)
    return file_bytes if file_bytes else build_example_xlsx_bytes()


def pdf_escape(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_pdf_line(text: str, max_chars: int = 95) -> List[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_manual_pdf_bytes() -> bytes:
    sections = [
        (
            "Objetivo do sistema",
            [
                "Este sistema realiza balanceamento de linha de produção a partir de atividades, tempos de operação e relações de precedência.",
                "O resultado mostra a alocação das atividades em estações, as métricas de desempenho e um diagrama de precedências organizado por estação.",
            ],
        ),
        (
            "Entradas necessárias",
            [
                "Atividade: código ou nome da tarefa, como A, B, Corte ou Montagem.",
                "Tempo: duração da atividade. Use valores numéricos maiores que zero.",
                "Precedencias: atividades que precisam ser executadas antes. Use vírgula para separar mais de uma predecessora.",
                "Tempo de ciclo: tempo máximo disponível em cada estação de trabalho.",
            ],
        ),
        (
            "Formas de entrada",
            [
                "Digitar ou editar tabela: permite preencher os dados diretamente na tela.",
                "Importar TXT: usa arquivo com as colunas Atividade, Tempo e Precedencias, separadas por ponto e vírgula.",
                "Importar Excel: usa planilha com as mesmas três colunas. O botão para baixar modelo aparece quando esta forma de entrada é selecionada.",
            ],
        ),
        (
            "Maior Tempo de Operação (Largest Candidate Rule - LCR)",
            [
                "Esta regra ordena as atividades elegíveis pelo maior tempo de operação.",
                "Em cada estação, o sistema procura atividades cujas predecessoras já foram alocadas e que ainda cabem no tempo restante da estação.",
                "Entre as atividades elegíveis, seleciona primeiro a atividade de maior tempo. Em caso de empate, usa número de sucessores e ordem alfabética como critérios auxiliares.",
            ],
        ),
        (
            "Peso Posicional Ranqueado (RPW/Helgeson-Birnie)",
            [
                "O peso posicional de uma atividade é calculado pela soma do seu próprio tempo com os tempos de todas as suas sucessoras diretas e indiretas.",
                "Atividades com maior peso posicional recebem prioridade, pois tendem a sustentar uma parte maior da rede de precedências.",
                "A alocação respeita o tempo de ciclo e só considera atividades liberadas pelas precedências.",
            ],
        ),
        (
            "Kilbridge-Wester",
            [
                "Esta heurística organiza as atividades em colunas de precedência.",
                "Atividades sem predecessoras entram na primeira coluna. Atividades que dependem delas avançam para colunas seguintes.",
                "Na alocação, o sistema prioriza atividades das colunas mais à esquerda e usa o maior tempo de operação como critério auxiliar dentro da mesma coluna.",
            ],
        ),
        (
            "J-Wagon",
            [
                "Esta regra prioriza atividades com maior número de sucessoras na rede de precedência.",
                "A ideia é alocar cedo atividades que liberam mais tarefas posteriores.",
                "Quando há empate, o sistema usa maior tempo de operação e peso posicional como critérios auxiliares.",
            ],
        ),
        (
            "COMSOAL",
            [
                "COMSOAL é uma heurística construtiva com escolhas aleatórias entre atividades viáveis.",
                "O sistema gera várias soluções candidatas. Em cada tentativa, seleciona aleatoriamente atividades que respeitam precedência e tempo restante da estação.",
                "Ao final, mantém a melhor solução encontrada, considerando primeiro o menor número de estações e depois menor índice de suavidade.",
                "Por usar aleatoriedade, o resultado pode mudar quando a semente aleatória ou o número de repetições for alterado.",
            ],
        ),
        (
            "Premissas e limitações",
            [
                "O modelo considera uma linha simples com tempo de ciclo fixo.",
                "O sistema considera 1 trabalhador por estação.",
                "As atividades são indivisíveis. Uma atividade não é quebrada entre duas estações.",
                "Os tempos são determinísticos. Não são tratados tempos aleatórios, aprendizagem, fadiga, setups, deslocamentos ou diferenças de habilidade entre trabalhadores.",
                "As heurísticas fornecem boas soluções de forma rápida, mas não garantem a solução ótima global.",
            ],
        ),
        (
            "Saídas do sistema",
            [
                "Tabela de estações com atividades alocadas, tempo ocupado, tempo ocioso e utilização.",
                "Tabela de atividades com estação, ordem, prioridade calculada e sucessores.",
                "Métricas de balanceamento, como eficiência da linha, atraso de balanceamento, mínimo teórico de estações e índice de suavidade.",
                "Diagrama de precedências organizado por estações, com cores por estação.",
                "Arquivos de resultado em Excel e TXT.",
            ],
        ),
    ]

    title = "Manual de uso do Sistema de Balanceamento de Linha"
    pages: List[List[Tuple[str, int, bool]]] = []
    current_page: List[Tuple[str, int, bool]] = []
    lines_per_page = 45

    def add_line(text: str, font_size: int = 10, bold: bool = False) -> None:
        nonlocal current_page
        if len(current_page) >= lines_per_page:
            pages.append(current_page)
            current_page = []
        current_page.append((text, font_size, bold))

    add_line(title, 16, True)
    add_line("", 10, False)
    add_line("Aplicativo Streamlit para apoio ao ensino e à análise de balanceamento de linha.", 10, False)
    add_line("", 10, False)

    for section_title, paragraphs in sections:
        add_line(section_title, 12, True)
        for paragraph in paragraphs:
            for line in wrap_pdf_line(paragraph, 95):
                add_line(line, 10, False)
            add_line("", 10, False)
        add_line("", 10, False)

    if current_page:
        pages.append(current_page)

    objects: List[bytes] = []

    def add_object(content: bytes) -> int:
        objects.append(content)
        return len(objects)

    font_regular_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    page_ids = []
    contents_ids = []

    for page_number, page_lines in enumerate(pages, start=1):
        y = 800
        stream_lines = ["BT"]
        for text, font_size, bold in page_lines:
            font_name = "F2" if bold else "F1"
            safe_text = pdf_escape(text)
            stream_lines.append(f"/{font_name} {font_size} Tf")
            stream_lines.append(f"50 {y} Td")
            stream_lines.append(f"({safe_text}) Tj")
            stream_lines.append(f"-50 {-y} Td")
            y -= int(font_size * 1.6)
        footer = f"Página {page_number} de {len(pages)}"
        stream_lines.append("/F1 8 Tf")
        stream_lines.append("50 30 Td")
        stream_lines.append(f"({pdf_escape(footer)}) Tj")
        stream_lines.append("ET")
        stream_bytes = "\n".join(stream_lines).encode("latin-1", "replace")
        content_obj = b"<< /Length " + str(len(stream_bytes)).encode() + b" >>\nstream\n" + stream_bytes + b"\nendstream"
        content_id = add_object(content_obj)
        contents_ids.append(content_id)
        page_ids.append(None)

    pages_id_placeholder = 0
    for i, content_id in enumerate(contents_ids):
        page_obj = (
            f"<< /Type /Page /Parent {{PAGES_ID}} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_regular_id} 0 R /F2 {font_bold_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")
        page_id = add_object(page_obj)
        page_ids[i] = page_id

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_obj = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")
    pages_id = add_object(pages_obj)
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin-1"))

    for idx, obj in enumerate(objects):
        if b"{PAGES_ID}" in obj:
            objects[idx] = obj.replace(b"{PAGES_ID}", str(pages_id).encode())

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{obj_id} 0 obj\n".encode("latin-1"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref_position = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_position}\n%%EOF".encode("latin-1")
    )
    return output.getvalue()


# ============================================================
# Funções auxiliares de arquivo e limpeza
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
        "st": "Tempo",
        "precedencias": "Precedencias",
        "precedencia": "Precedencias",
        "predecessoras": "Precedencias",
        "predecessores": "Precedencias",
        "predecessors": "Precedencias",
        "predecessor": "Precedencias",
        "prec": "Precedencias",
    }

    rename = {}
    for col, norm in normalized.items():
        if norm in aliases:
            rename[col] = aliases[norm]

    df = df.rename(columns=rename)

    required = ["Atividade", "Tempo", "Precedencias"]
    for col in required:
        if col not in df.columns:
            df[col] = "" if col != "Tempo" else 0

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
            has_time = any(c in cols for c in ["tempo", "duracao", "time", "duration", "st"])
            if has_activity and has_time:
                return standardize_input_df(df)
        except Exception:
            pass
    df = pd.read_csv(io.StringIO(content), sep=";", header=0)
    return standardize_input_df(df)


def parse_excel(uploaded_file) -> pd.DataFrame:
    df = pd.read_excel(uploaded_file)
    return standardize_input_df(df)


# ============================================================
# Validação, grafo e heurísticas
# ============================================================

def build_problem(df: pd.DataFrame) -> Tuple[List[str], Dict[str, float], Dict[str, Set[str]]]:
    df = standardize_input_df(df)

    if df.empty:
        raise ValueError("A tabela está vazia. Informe pelo menos uma atividade.")

    if df["Atividade"].duplicated().any():
        duplicated = df.loc[df["Atividade"].duplicated(), "Atividade"].tolist()
        raise ValueError(f"Há atividades repetidas: {', '.join(duplicated)}.")

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
        preds = set(parse_precedence_cell(row["Precedencias"]))
        for pred in preds:
            if pred not in activity_set:
                missing_refs.append((act, pred))
        predecessors[act] = preds

    if missing_refs:
        details = "; ".join([f"{act} cita '{pred}'" for act, pred in missing_refs])
        raise ValueError(f"Há precedências que não existem na lista de atividades: {details}.")

    topological_order(activities, predecessors)
    return activities, times, predecessors


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


def topological_order(activities: List[str], predecessors: Dict[str, Set[str]]) -> List[str]:
    remaining = set(activities)
    assigned = set()
    order = []

    while remaining:
        available = sorted([a for a in remaining if predecessors[a].issubset(assigned)])
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


def compute_kilbridge_columns(activities: List[str], predecessors: Dict[str, Set[str]]) -> Dict[str, int]:
    order = topological_order(activities, predecessors)
    columns = {}
    for act in order:
        if not predecessors[act]:
            columns[act] = 1
        else:
            columns[act] = 1 + max(columns[pred] for pred in predecessors[act])
    return columns


def compute_priority_data(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
) -> Dict:
    successors = build_successors(activities, predecessors)
    cache = {}
    all_successors = {act: transitive_successors(act, successors, cache) for act in activities}
    successor_count = {act: len(all_successors[act]) for act in activities}
    positional_weight = {
        act: times[act] + sum(times[s] for s in all_successors[act])
        for act in activities
    }
    kilbridge_column = compute_kilbridge_columns(activities, predecessors)
    return {
        "successors": successors,
        "all_successors": all_successors,
        "successor_count": successor_count,
        "positional_weight": positional_weight,
        "kilbridge_column": kilbridge_column,
    }


def heuristic_key(heuristic: str) -> str:
    if heuristic.startswith("Maior Tempo"):
        return "LCR"
    if heuristic.startswith("Peso Posicional"):
        return "RPW"
    if heuristic.startswith("Kilbridge"):
        return "KILBRIDGE"
    if heuristic.startswith("J-Wagon"):
        return "JWAGON"
    if heuristic.startswith("COMSOAL"):
        return "COMSOAL"
    return "LCR"


def priority_value_for_report(activity: str, key: str, priority_data: Dict, times: Dict[str, float]) -> float:
    if key == "LCR":
        return times[activity]
    if key == "RPW":
        return priority_data["positional_weight"][activity]
    if key == "KILBRIDGE":
        return priority_data["kilbridge_column"][activity]
    if key == "JWAGON":
        return priority_data["successor_count"][activity]
    if key == "COMSOAL":
        return priority_data["positional_weight"][activity]
    return times[activity]


def choose_next_task(
    available: List[str],
    key: str,
    priority_data: Dict,
    times: Dict[str, float],
) -> str:
    successor_count = priority_data["successor_count"]
    positional_weight = priority_data["positional_weight"]
    kilbridge_column = priority_data["kilbridge_column"]

    if key == "LCR":
        return sorted(
            available,
            key=lambda a: (times[a], successor_count[a], positional_weight[a], a),
            reverse=True,
        )[0]

    if key == "RPW":
        return sorted(
            available,
            key=lambda a: (positional_weight[a], successor_count[a], times[a], a),
            reverse=True,
        )[0]

    if key == "KILBRIDGE":
        return sorted(
            available,
            key=lambda a: (kilbridge_column[a], -times[a], -successor_count[a], a),
        )[0]

    if key == "JWAGON":
        return sorted(
            available,
            key=lambda a: (successor_count[a], times[a], positional_weight[a], a),
            reverse=True,
        )[0]

    return sorted(available)[0]


def validate_cycle_time(times: Dict[str, float], cycle_time: float) -> None:
    if cycle_time <= 0:
        raise ValueError("O tempo de ciclo precisa ser maior que zero.")

    largest_time = max(times.values())
    if largest_time > cycle_time:
        largest_task = max(times, key=times.get)
        raise ValueError(
            "O tempo de ciclo é menor do que o tempo da maior atividade. "
            f"Com 1 trabalhador por estação, a atividade '{largest_task}' ({largest_time:g}) "
            f"não cabe em uma estação com ciclo {cycle_time:g}."
        )


def finish_result(
    stations: List[Dict],
    times: Dict[str, float],
    cycle_time: float,
    priority_data: Dict,
    key: str,
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

    priority = {
        act: priority_value_for_report(act, key, priority_data, times)
        for act in times
    }

    return {
        "stations": stations,
        "assignment": assignment,
        "task_order": task_order,
        "priority": priority,
        "priority_data": priority_data,
        "all_successors": priority_data["all_successors"],
        "successor_count": priority_data["successor_count"],
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


def balance_line_greedy(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    heuristic: str,
) -> Dict:
    validate_cycle_time(times, cycle_time)
    key = heuristic_key(heuristic)
    priority_data = compute_priority_data(activities, times, predecessors)

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

            task = choose_next_task(available, key, priority_data, times)
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
                "Utilizacao (%)": 100 * station_time / cycle_time,
            }
        )

    return finish_result(stations, times, cycle_time, priority_data, key)


def construct_comsoal_once(
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
                "Não foi possível construir uma solução COMSOAL. "
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


def score_stations(stations: List[Dict], cycle_time: float) -> Tuple[int, float, float]:
    smoothness = math.sqrt(sum((cycle_time - st["Tempo ocupado"]) ** 2 for st in stations))
    total_idle = sum(st["Tempo ocioso"] for st in stations)
    return len(stations), smoothness, total_idle


def balance_line_comsoal(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    iterations: int,
    seed: int,
) -> Dict:
    validate_cycle_time(times, cycle_time)
    priority_data = compute_priority_data(activities, times, predecessors)
    rng = random.Random(seed)

    best_stations = None
    best_score = None

    iterations = max(1, int(iterations))
    for _ in range(iterations):
        stations = construct_comsoal_once(activities, times, predecessors, cycle_time, rng)
        score = score_stations(stations, cycle_time)
        if best_score is None or score < best_score:
            best_score = score
            best_stations = stations

    return finish_result(best_stations, times, cycle_time, priority_data, "COMSOAL")


def balance_line(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    heuristic: str,
    comsoal_iterations: int = 300,
    comsoal_seed: int = 42,
) -> Dict:
    if heuristic_key(heuristic) == "COMSOAL":
        return balance_line_comsoal(
            activities,
            times,
            predecessors,
            cycle_time,
            comsoal_iterations,
            comsoal_seed,
        )
    return balance_line_greedy(activities, times, predecessors, cycle_time, heuristic)


# ============================================================
# Visualizações e exportação
# ============================================================

def create_station_precedence_chart(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    result: Dict,
):
    assignment = result["assignment"]
    task_order = result["task_order"]
    stations = result["stations"]

    positions = {}
    max_tasks = max(len(st["Atividades"]) for st in stations)
    for st in stations:
        station_number = st["Estacao"]
        tasks = st["Atividades"]
        count = len(tasks)
        for idx, task in enumerate(tasks, start=1):
            y = (count + 1) / 2 - idx
            positions[task] = (station_number, y)

    fig = go.Figure()

    for st in stations:
        station_number = st["Estacao"]
        color = STATION_COLORS[(station_number - 1) % len(STATION_COLORS)]
        fig.add_vrect(
            x0=station_number - 0.42,
            x1=station_number + 0.42,
            fillcolor=color,
            opacity=0.08,
            line_width=1,
            line_color=color,
            layer="below",
        )

    for act, preds in predecessors.items():
        for pred in sorted(preds):
            x0, y0 = positions[pred]
            x1, y1 = positions[act]
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1],
                    y=[y0, y1],
                    mode="lines",
                    line=dict(width=1.5, color="#64748b"),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
            fig.add_annotation(
                x=x1,
                y=y1,
                ax=x0,
                ay=y0,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1,
                arrowwidth=1.2,
                arrowcolor="#64748b",
                opacity=0.9,
            )

    for st in stations:
        station_number = st["Estacao"]
        color = STATION_COLORS[(station_number - 1) % len(STATION_COLORS)]
        tasks = st["Atividades"]
        x_values = []
        y_values = []
        text_values = []
        custom_values = []
        for task in tasks:
            x, y = positions[task]
            x_values.append(x)
            y_values.append(y)
            text_values.append(f"{task}<br>{times[task]:g}")
            custom_values.append(
                f"Atividade: {task}<br>Tempo: {times[task]:g}<br>Estação: {assignment[task]}<br>Ordem: {task_order[task]}"
            )
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="markers+text",
                marker=dict(size=42, color=color, line=dict(width=1.5, color="#1f2937")),
                text=text_values,
                textposition="middle center",
                textfont=dict(size=11, color="white"),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=custom_values,
                name=f"Estação {station_number}",
                showlegend=True,
            )
        )

    y_margin = max(1.5, max_tasks / 2 + 0.8)
    number_stations = len(stations)
    fig.update_layout(
        title="Diagrama de precedências por estação",
        height=max(450, 130 + 80 * max_tasks),
        margin=dict(l=20, r=20, t=70, b=40),
        plot_bgcolor="white",
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(1, number_stations + 1)),
            ticktext=[f"Estação {i}" for i in range(1, number_stations + 1)],
            range=[0.5, number_stations + 0.5],
            showgrid=False,
            zeroline=False,
        ),
        yaxis=dict(
            range=[-y_margin, y_margin],
            showgrid=False,
            zeroline=False,
            visible=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
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
                    "Estação": f"E{st['Estacao']}",
                    "Atividade": task,
                    "Início no ciclo": start,
                    "Fim no ciclo": finish,
                    "Duração": times[task],
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
            x=[row["Duração"]],
            base=[row["Início no ciclo"]],
            orientation="h",
            text=[row["Atividade"]],
            textposition="inside",
            name=row["Atividade"],
            hovertemplate=(
                "Estação: %{y}<br>"
                "Atividade: " + str(row["Atividade"]) + "<br>"
                "Início: " + f"{row['Início no ciclo']:g}" + "<br>"
                "Fim: " + f"{row['Fim no ciclo']:g}" + "<br>"
                "Duração: " + f"{row['Duração']:g}" + "<extra></extra>"
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
    task_rows = []
    for act in df_input["Atividade"].tolist():
        task_rows.append(
            {
                "Atividade": act,
                "Tempo": times[act],
                "Precedencias": ", ".join(sorted(predecessors[act])),
                "Estacao": result["assignment"][act],
                "Ordem na estacao": result["task_order"][act],
                "Prioridade calculada": result["priority"][act],
                "N. sucessores": result["successor_count"][act],
                "Sucessores": ", ".join(sorted(result["all_successors"][act])),
            }
        )

    tasks_df = pd.DataFrame(task_rows).sort_values(["Estacao", "Ordem na estacao"]).reset_index(drop=True)

    stations_df = pd.DataFrame(result["stations"])
    stations_df["Atividades"] = stations_df["Atividades"].apply(lambda x: ", ".join(x))
    stations_df["Tempo ocupado"] = stations_df["Tempo ocupado"].round(4)
    stations_df["Tempo ocioso"] = stations_df["Tempo ocioso"].round(4)
    stations_df["Utilizacao (%)"] = stations_df["Utilizacao (%)"].round(2)

    metrics_df = pd.DataFrame([{"Métrica": k, "Valor": v} for k, v in result["metrics"].items()])
    metrics_df["Valor"] = metrics_df["Valor"].apply(lambda x: round(x, 4) if isinstance(x, float) else x)

    return tasks_df, stations_df, metrics_df


def to_excel_bytes(
    tasks_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    gantt_df: pd.DataFrame,
    heuristic: str,
) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        metrics_df.to_excel(writer, index=False, sheet_name="Metricas")
        stations_df.to_excel(writer, index=False, sheet_name="Estacoes")
        tasks_df.to_excel(writer, index=False, sheet_name="Atividades")
        gantt_df.to_excel(writer, index=False, sheet_name="Gantt")

        info_df = pd.DataFrame(
            {
                "Campo": ["Heuristica utilizada", "Observacao"],
                "Valor": [
                    heuristic,
                    "Resultado heurístico. Não garante solução ótima global. Considera 1 trabalhador por estação.",
                ],
            }
        )
        info_df.to_excel(writer, index=False, sheet_name="Info")

        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            for column_cells in ws.columns:
                max_length = 0
                column_letter = column_cells[0].column_letter
                for cell in column_cells:
                    if cell.value is not None:
                        max_length = max(max_length, len(str(cell.value)))
                ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

    output.seek(0)
    return output.getvalue()


def to_txt_report(
    tasks_df: pd.DataFrame,
    stations_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    heuristic: str,
) -> str:
    lines = []
    lines.append("RELATORIO DE BALANCEAMENTO DE LINHA")
    lines.append(f"Heuristica utilizada: {heuristic}")
    lines.append("Premissa: 1 trabalhador por estação.")
    lines.append("")
    lines.append("METRICAS")
    for _, row in metrics_df.iterrows():
        lines.append(f"- {row['Métrica']}: {row['Valor']}")
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

with st.sidebar:
    st.header("Parâmetros")

    cycle_time = st.number_input(
        "Tempo de ciclo",
        min_value=0.01,
        value=50.0,
        step=1.0,
        help="Tempo máximo disponível em cada estação.",
    )

    heuristic = st.selectbox(
        "Heurística",
        HEURISTIC_OPTIONS,
        help="A heurística define a regra de prioridade para escolher atividades elegíveis.",
    )

    comsoal_iterations = 300
    comsoal_seed = 42
    if heuristic_key(heuristic) == "COMSOAL":
        comsoal_iterations = st.number_input(
            "Repetições COMSOAL",
            min_value=1,
            value=500,
            step=50,
            help="Quantidade de soluções aleatórias geradas. Valores maiores podem melhorar a solução, mas aumentam o tempo de execução.",
        )
        comsoal_seed = st.number_input(
            "Semente aleatória",
            min_value=0,
            value=42,
            step=1,
            help="Use a mesma semente para repetir o mesmo resultado.",
        )

    st.divider()
    st.subheader("Help")
    st.download_button(
        "Baixar manual em PDF",
        data=build_manual_pdf_bytes(),
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
        A;5;
        B;3;A
        C;4;A
        D;2;B, C
        ```
        """
    )

input_mode = st.radio(
    "Forma de entrada",
    ["Digitar/editar tabela", "Importar .txt", "Importar Excel"],
    horizontal=True,
)

df_input = None

if input_mode == "Digitar/editar tabela":
    df_input = st.data_editor(
        get_default_data(),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Atividade": st.column_config.TextColumn("Atividade", required=True),
            "Tempo": st.column_config.NumberColumn("Tempo", min_value=0.01, step=1.0, required=True),
            "Precedencias": st.column_config.TextColumn("Precedencias"),
        },
    )

elif input_mode == "Importar .txt":
    st.download_button(
        "Baixar modelo TXT",
        data=get_txt_example_bytes(),
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
        data=get_xlsx_example_bytes(),
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
    else:
        try:
            df_input = standardize_input_df(df_input)
            activities, times, predecessors = build_problem(df_input)
            result = balance_line(
                activities,
                times,
                predecessors,
                cycle_time,
                heuristic,
                comsoal_iterations=int(comsoal_iterations),
                comsoal_seed=int(comsoal_seed),
            )

            tasks_df, stations_df, metrics_df = build_output_tables(df_input, times, predecessors, result)
            gantt_df = make_gantt_df(result["stations"], times)

            st.success("Balanceamento concluído.")

            st.subheader("Resumo")
            m = result["metrics"]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Estações", int(m["Número de estações"]))
            col2.metric("Mínimo teórico", int(m["Mínimo teórico de estações"]))
            col3.metric("Eficiência", f"{m['Eficiência da linha (%)']:.2f}%")
            col4.metric("Tempo ocioso total", f"{m['Tempo ocioso total']:.2f}")

            st.info(
                f"Heurística utilizada: **{heuristic}**. "
                "O resultado é heurístico, considera 1 trabalhador por estação e não garante ótimo global."
            )

            tab1, tab2, tab3, tab4 = st.tabs(
                ["Estações", "Atividades", "Diagrama de precedências", "Gráfico de ocupação"]
            )

            with tab1:
                st.dataframe(stations_df, use_container_width=True)
                st.dataframe(metrics_df, use_container_width=True)

            with tab2:
                st.dataframe(tasks_df, use_container_width=True)

            with tab3:
                fig_precedence = create_station_precedence_chart(activities, times, predecessors, result)
                st.plotly_chart(fig_precedence, use_container_width=True)

            with tab4:
                fig_gantt = create_gantt_chart(gantt_df, cycle_time)
                if fig_gantt is not None:
                    st.plotly_chart(fig_gantt, use_container_width=True)

            st.subheader("Baixar resultados")
            excel_bytes = to_excel_bytes(tasks_df, stations_df, metrics_df, gantt_df, heuristic)
            txt_report = to_txt_report(tasks_df, stations_df, metrics_df, heuristic)

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

        except Exception as exc:
            st.error(str(exc))
