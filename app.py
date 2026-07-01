import io
import math
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


APP_DIR = Path(__file__).parent
ASSETS_DIR = APP_DIR / "assets"
MANUAL_PATH = ASSETS_DIR / "manual_usuario_balanceamento_linha.pdf"
TXT_EXAMPLE_PATH = ASSETS_DIR / "exemplo_atividades.txt"
XLSX_EXAMPLE_PATH = ASSETS_DIR / "exemplo_atividades.xlsx"


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
# Funções auxiliares de arquivo e limpeza
# ============================================================

def read_binary_file(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    return b""


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
    # Aceita separadores: vírgula, ponto e vírgula, barra vertical ou quebra de linha
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
            df[col] = "" if col != "Tempo" else 0

    df = df[required]
    df["Atividade"] = df["Atividade"].apply(normalize_activity)
    df["Tempo"] = pd.to_numeric(df["Tempo"], errors="coerce")
    df["Precedencias"] = df["Precedencias"].fillna("").astype(str).str.strip()
    df = df[df["Atividade"] != ""].reset_index(drop=True)
    return df


def parse_txt(uploaded_file) -> pd.DataFrame:
    content = uploaded_file.read().decode("utf-8-sig")
    # Tenta detectar separador automaticamente. O modelo usa ponto e vírgula.
    for sep in [";", ",", "\t"]:
        try:
            df = pd.read_csv(io.StringIO(content), sep=sep)
            cols = [normalize_column_name(c) for c in df.columns]
            if any(c in cols for c in ["atividade", "tarefa", "task"]) and any(
                c in cols for c in ["tempo", "duracao", "time", "duration"]
            ):
                return standardize_input_df(df)
        except Exception:
            pass
    # Fallback: linhas no formato Atividade;Tempo;Precedencias
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
        preds = set(parse_precedence_cell(row["Precedencias"]))
        for pred in preds:
            if pred not in activity_set:
                missing_refs.append((act, pred))
        predecessors[act] = preds

    if missing_refs:
        details = "; ".join([f"{act} cita '{pred}'" for act, pred in missing_refs])
        raise ValueError(f"Há precedências que não existem na lista de atividades: {details}.")

    # Verifica ciclos por ordenação topológica
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


def compute_priority(
    heuristic: str,
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
) -> Tuple[Dict[str, float], Dict[str, Set[str]], Dict[str, int]]:
    successors = build_successors(activities, predecessors)
    cache = {}
    all_successors = {
        act: transitive_successors(act, successors, cache) for act in activities
    }
    successor_count = {act: len(all_successors[act]) for act in activities}

    if heuristic.startswith("RPW"):
        # Peso posicional = tempo da atividade + soma dos tempos de todos os sucessores.
        priority = {
            act: times[act] + sum(times[s] for s in all_successors[act])
            for act in activities
        }
    elif heuristic.startswith("LCR"):
        # Largest Candidate Rule = maior tempo de processamento.
        priority = {act: times[act] for act in activities}
    elif heuristic.startswith("MFT"):
        # Most Following Tasks = maior número de sucessores.
        priority = {act: float(successor_count[act]) for act in activities}
    else:
        raise ValueError("Heurística não reconhecida.")

    return priority, all_successors, successor_count


def choose_next_task(
    available: List[str],
    heuristic: str,
    priority: Dict[str, float],
    times: Dict[str, float],
    successor_count: Dict[str, int],
) -> str:
    if heuristic.startswith("RPW"):
        return sorted(
            available,
            key=lambda a: (priority[a], successor_count[a], times[a], a),
            reverse=True,
        )[0]

    if heuristic.startswith("LCR"):
        return sorted(
            available,
            key=lambda a: (times[a], successor_count[a], priority[a], a),
            reverse=True,
        )[0]

    if heuristic.startswith("MFT"):
        return sorted(
            available,
            key=lambda a: (successor_count[a], times[a], priority[a], a),
            reverse=True,
        )[0]

    return available[0]


def balance_line(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    cycle_time: float,
    heuristic: str,
) -> Dict:
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

    priority, all_successors, successor_count = compute_priority(
        heuristic, activities, times, predecessors
    )

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

            task = choose_next_task(
                available,
                heuristic,
                priority,
                times,
                successor_count,
            )
            station_tasks.append(task)
            station_time += times[task]
            unassigned.remove(task)
            assigned.add(task)

        if not station_tasks:
            # Proteção contra travamento, caso algum erro lógico passe pela validação.
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

    total_time = sum(times.values())
    number_stations = len(stations)
    theoretical_min = math.ceil(total_time / cycle_time)
    total_available_time = number_stations * cycle_time
    idle_time = total_available_time - total_time
    efficiency = total_time / total_available_time if total_available_time else 0
    balance_delay = 1 - efficiency
    smoothness_index = math.sqrt(
        sum((cycle_time - st["Tempo ocupado"]) ** 2 for st in stations)
    )

    assignment = {}
    task_order = {}
    for st in stations:
        for idx, task in enumerate(st["Atividades"], start=1):
            assignment[task] = st["Estacao"]
            task_order[task] = idx

    return {
        "stations": stations,
        "assignment": assignment,
        "task_order": task_order,
        "priority": priority,
        "all_successors": all_successors,
        "successor_count": successor_count,
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


# ============================================================
# Visualizações e exportação
# ============================================================

def make_precedence_dot(
    activities: List[str],
    times: Dict[str, float],
    predecessors: Dict[str, Set[str]],
    assignment: Dict[str, int] = None,
) -> str:
    assignment = assignment or {}
    lines = [
        "digraph G {",
        "  graph [rankdir=LR, bgcolor=\"transparent\"];",
        "  node [shape=box, style=\"rounded,filled\", fontname=\"Arial\", fillcolor=\"#EEF2FF\", color=\"#334155\"];",
        "  edge [color=\"#475569\", arrowsize=0.8];",
    ]

    for act in activities:
        station_label = f"\\nE{assignment[act]}" if act in assignment else ""
        label = f"{act}\\nTempo={times[act]:g}{station_label}"
        lines.append(f'  "{act}" [label="{label}"];')

    for act, preds in predecessors.items():
        for pred in sorted(preds):
            lines.append(f'  "{pred}" -> "{act}";')

    lines.append("}")
    return "\n".join(lines)


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

    tasks_df = pd.DataFrame(task_rows).sort_values(
        ["Estacao", "Ordem na estacao"]
    ).reset_index(drop=True)

    stations_df = pd.DataFrame(result["stations"])
    stations_df["Atividades"] = stations_df["Atividades"].apply(lambda x: ", ".join(x))
    stations_df["Tempo ocupado"] = stations_df["Tempo ocupado"].round(4)
    stations_df["Tempo ocioso"] = stations_df["Tempo ocioso"].round(4)
    stations_df["Utilizacao (%)"] = stations_df["Utilizacao (%)"].round(2)

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
                    "Resultado heurístico. Não garante solução ótima global.",
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
                ws.column_dimensions[column_letter].width = min(max_length + 2, 45)

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

default_data = pd.DataFrame(
    [
        {"Atividade": "A", "Tempo": 5, "Precedencias": ""},
        {"Atividade": "B", "Tempo": 3, "Precedencias": "A"},
        {"Atividade": "C", "Tempo": 4, "Precedencias": "A"},
        {"Atividade": "D", "Tempo": 2, "Precedencias": "B, C"},
        {"Atividade": "E", "Tempo": 6, "Precedencias": "C"},
        {"Atividade": "F", "Tempo": 3, "Precedencias": "D, E"},
        {"Atividade": "G", "Tempo": 2, "Precedencias": "F"},
    ]
)

with st.sidebar:
    st.header("Parâmetros")

    cycle_time = st.number_input(
        "Tempo de ciclo",
        min_value=0.01,
        value=10.0,
        step=1.0,
        help="Tempo máximo disponível em cada estação.",
    )

    heuristic = st.selectbox(
        "Heurística",
        [
            "RPW - Peso Posicional / Helgeson-Birnie",
            "LCR - Maior tempo de processamento",
            "MFT - Maior número de sucessores",
        ],
        help="A heurística define a regra de prioridade para escolher atividades elegíveis.",
    )

    st.divider()
    st.subheader("Downloads de apoio")

    st.download_button(
        "⬇️ Baixar modelo .txt",
        data=read_binary_file(TXT_EXAMPLE_PATH),
        file_name="exemplo_atividades.txt",
        mime="text/plain",
        use_container_width=True,
    )

    st.download_button(
        "⬇️ Baixar modelo Excel",
        data=read_binary_file(XLSX_EXAMPLE_PATH),
        file_name="exemplo_atividades.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.download_button(
        "Help - baixar manual em PDF",
        data=read_binary_file(MANUAL_PATH),
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
        default_data,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Atividade": st.column_config.TextColumn("Atividade", required=True),
            "Tempo": st.column_config.NumberColumn("Tempo", min_value=0.01, step=1.0, required=True),
            "Precedencias": st.column_config.TextColumn("Precedencias"),
        },
    )

elif input_mode == "Importar .txt":
    uploaded_txt = st.file_uploader(
        "Importe um arquivo .txt no formato do modelo",
        type=["txt", "csv"],
    )
    if uploaded_txt is not None:
        try:
            df_input = parse_txt(uploaded_txt)
            st.success("Arquivo .txt carregado com sucesso.")
            st.dataframe(df_input, use_container_width=True)
        except Exception as exc:
            st.error(f"Erro ao ler o arquivo: {exc}")

elif input_mode == "Importar Excel":
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
            result = balance_line(activities, times, predecessors, cycle_time, heuristic)

            tasks_df, stations_df, metrics_df = build_output_tables(
                df_input, times, predecessors, result
            )
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
                "O resultado é heurístico e não garante ótimo global."
            )

            tab1, tab2, tab3, tab4 = st.tabs(
                ["Estações", "Atividades", "Diagrama de precedências", "Gráfico"]
            )

            with tab1:
                st.dataframe(stations_df, use_container_width=True)
                st.dataframe(metrics_df, use_container_width=True)

            with tab2:
                st.dataframe(tasks_df, use_container_width=True)

            with tab3:
                dot = make_precedence_dot(
                    activities,
                    times,
                    predecessors,
                    result["assignment"],
                )
                st.graphviz_chart(dot, use_container_width=True)

            with tab4:
                fig = create_gantt_chart(gantt_df, cycle_time)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("Baixar resultados")
            excel_bytes = to_excel_bytes(
                tasks_df,
                stations_df,
                metrics_df,
                gantt_df,
                heuristic,
            )
            txt_report = to_txt_report(tasks_df, stations_df, metrics_df, heuristic)

            dl1, dl2 = st.columns(2)
            dl1.download_button(
                "⬇️ Baixar resultado em Excel",
                data=excel_bytes,
                file_name="resultado_balanceamento_linha.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            dl2.download_button(
                "⬇️ Baixar relatório em .txt",
                data=txt_report.encode("utf-8"),
                file_name="relatorio_balanceamento_linha.txt",
                mime="text/plain",
                use_container_width=True,
            )

        except Exception as exc:
            st.error(str(exc))
