from __future__ import annotations

import hashlib
import tempfile
from html import escape
from pathlib import Path

import streamlit as st

from bpa_core import (
    BpaFile, HEADER_FIELDS, BPAC_FIELDS, BPAI_FIELDS, extract_field,
    set_field, norm_cnes, norm_fl, norm_seq,
)

st.set_page_config(page_title="Editor BPA", page_icon="📋", layout="wide")
st.markdown("""
<style>
:root { --ink:#203d32; --green:#216347; --line:#d8e7de; --muted:#506d5e; }
[data-testid="stAppViewContainer"] { background:#f2f7f3; color:var(--ink); }
.block-container { padding:5rem 2rem 3rem; max-width:1380px; }
[data-testid="stSidebar"] { background:#e8f2eb; border-right:1px solid var(--line); }
.bpa-header { background:linear-gradient(120deg,#174b38,#287657); color:white; padding:1.8rem 2rem; border-radius:20px; margin-bottom:1.5rem; box-shadow:0 10px 30px #174b3814; }
.bpa-header h1 { color:white; margin:.5rem 0 0; padding:0; font-size:1.9rem; letter-spacing:-.04em; }
.bpa-header p { margin:.4rem 0 0; color:#e0f1e6; }
.eyebrow { display:inline-block; border:1px solid #ffffff40; background:#ffffff12; padding:.25rem .65rem; border-radius:20px; color:#e0f1e6; font-size:.7rem; letter-spacing:.1em; text-transform:uppercase; }
.welcome { background:white; border:1px solid var(--line); border-radius:18px; padding:2rem; color:var(--muted); line-height:1.7; }
.welcome h2 { color:var(--ink); padding:0; margin:0 0 .5rem; font-size:1.25rem; }
[data-testid="stVerticalBlockBorderWrapper"] > div { border-color:var(--line) !important; border-radius:12px; }
[data-testid="stVerticalBlockBorderWrapper"] { background:white; border-radius:12px; }
[data-testid="stTextInput"] input { background:#f7faf8; color:var(--ink); }
[data-testid="stWidgetLabel"] p { color:var(--muted); }
button[kind="primary"] { background:#216347; border-color:#216347; color:white; }
@media(max-width:700px) { .block-container { padding:5rem .75rem 2rem; } .bpa-header,.welcome { padding:1.25rem; } }
</style>
<div class="bpa-header"><span class="eyebrow">Gestão de arquivos BPA</span><h1>Editor BPA</h1><p>Consulte e edite sua produção ambulatorial em um só lugar.</p></div>
""", unsafe_allow_html=True)


def load_file(upload):
    data = upload.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("digest") != digest:
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp.write(data)
            path = Path(temp.name)
        try:
            bpa = BpaFile(str(path))
        finally:
            path.unlink(missing_ok=True)
        if not any(line.startswith("01#BPA#") for line in bpa.lines):
            raise ValueError("Cabeçalho BPA (01#BPA#) não encontrado no arquivo.")
        if not any(bpa.record_type(line) in ("02", "03") for line in bpa.lines):
            raise ValueError("O arquivo não contém registros BPA-C ou BPA-I.")
        st.session_state.update(bpa=bpa, digest=digest, filename=upload.name, selected=None, revision=0, edited_records=set(), save_notice=False)
    return st.session_state.bpa


def render_fields(line, fields, prefix, columns=3):
    values = {}
    for start in range(0, len(fields), columns):
        cols = st.columns(columns)
        for col, field in zip(cols, fields[start:start + columns]):
            with col:
                values[field.key] = st.text_input(
                    field.label, value=extract_field(line, field), max_chars=field.size,
                    disabled=field.read_only, help=field.desc or None,
                    key=f"{prefix}_{field.key}",
                )
    return values


def apply_fields(line, fields, values):
    for field in fields:
        value = values[field.key]
        if not field.read_only and value != extract_field(line, field):
            line = set_field(line, field, value)
    return line


def document_provided(value):
    value = value.strip()
    return bool(value) and any(char != '0' for char in value)


def save_changes(bpa, index, header_index, record_values, header_values):
    line = bpa.lines[index]
    typ = bpa.record_type(line)
    cnes = norm_cnes(record_values['prd_cnes'])
    fl = norm_fl(record_values['prd_flh'])
    seq = norm_seq(record_values['prd_seq'], typ)
    if not all((cnes, fl, seq)):
        raise ValueError("Informe CNES, folha e sequência.")
    if bpa.has_other_key(typ, cnes, fl, seq, index):
        raise ValueError(f"Já existe outro registro deste tipo com CNES {cnes}, folha {fl} e sequência {seq}.")
    if typ == '03':
        if document_provided(record_values['prd_cnspac']) and document_provided(record_values['prd_cpf_pcnte']):
            raise ValueError("Informe apenas um documento do paciente: CPF ou CNS.")
        for key, label in [('prd_situacao_rua', 'Pessoa em situação de rua'), ('prd_sem_cpf', 'Pessoa sem CPF/Registro Civil')]:
            value = record_values[key].strip().upper()
            if value not in ('', 'S', 'N'):
                raise ValueError(f"{label}: use S, N ou deixe em branco.")
            record_values[key] = value
    record_values.update(prd_cnes=cnes, prd_flh=fl, prd_seq=seq)
    fields = BPAC_FIELDS if typ == '02' else BPAI_FIELDS
    new_line = apply_fields(line, fields, record_values)
    new_header = apply_fields(bpa.lines[header_index], HEADER_FIELDS, header_values)
    # Verifica a codificação antes de alterar a sessão, sem substituir caracteres.
    new_line.encode(bpa.encoding)
    new_header.encode(bpa.encoding)
    bpa.lines[index], bpa.lines[header_index] = new_line, new_header
    bpa.recalc_header()


def export_bytes(bpa):
    result = bpa.newline.join(line.encode(bpa.encoding) for line in bpa.lines) + bpa.newline
    return result + (b'\x1a' if bpa.has_ctrl_z else b'')


with st.sidebar:
    st.header("Arquivo BPA")
    upload = st.file_uploader("Selecione o arquivo", help="São aceitos arquivos BPA com qualquer extensão.")
    st.caption("O arquivo original permanece no seu computador. Baixe uma cópia após editar.")

if upload is None:
    st.markdown('<div class="welcome"><h2>Bem-vindo ao Editor BPA</h2>Selecione um arquivo na barra lateral para consultar registros BPA-I e BPA-C, editar seus dados e baixar o resultado.</div>', unsafe_allow_html=True)
    st.stop()
try:
    bpa = load_file(upload)
except (ValueError, OSError) as exc:
    st.error(f"Não foi possível abrir o arquivo: {exc}")
    st.stop()

st.session_state.setdefault("edited_records", set())
st.session_state.setdefault("save_notice", False)

production = [(i, line) for i, line in enumerate(bpa.lines) if bpa.record_type(line) in ('02', '03')]
with st.sidebar:
    st.success(f"Arquivo carregado: {upload.name}")
    st.metric("Registros de produção", len(production))
    download_area = st.container()

st.subheader("Consultar registro")
with st.container(border=True):
    with st.form("search"):
        cols = st.columns([2, 2, 1, 1, 1])
        typ = cols[0].selectbox("Tipo", ["BPA-I", "BPA-C"])
        cnes = cols[1].text_input("CNES", max_chars=7)
        fl = cols[2].text_input("Folha", max_chars=3)
        seq = cols[3].text_input("Sequência", max_chars=2)
        cols[4].write("")
        search = cols[4].form_submit_button("Consultar", type="primary", use_container_width=True)
    if search:
        try:
            rt = '03' if typ == 'BPA-I' else '02'
            cn, f, s = norm_cnes(cnes), norm_fl(fl), norm_seq(seq, rt)
            if not all((cn, f, s)):
                raise ValueError("Informe CNES, folha e sequência.")
            matches = bpa.find_record_indices(rt, cn, f, s)
            if not matches:
                raise ValueError("Nenhum registro encontrado para os dados informados.")
            st.session_state.selected = matches[0]
            st.session_state.save_notice = False
            st.session_state.revision += 1
            if len(matches) > 1:
                st.warning(f"Foram encontrados {len(matches)} registros com essa chave. O primeiro será exibido.")
        except ValueError as exc:
            st.error(str(exc))

index = st.session_state.selected
if index is not None:
    line = bpa.lines[index]
    rt = bpa.record_type(line)
    fields = BPAC_FIELDS if rt == '02' else BPAI_FIELDS
    header_index = next(i for i, item in enumerate(bpa.lines) if item.startswith('01#BPA#'))
    fl, seq = bpa.get_fl_seq(line, rt)
    st.markdown(f"### {'BPA-C' if rt == '02' else 'BPA-I'} · CNES {escape(line[2:9])} · Folha {escape(fl)} / Sequência {escape(seq)}")
    st.caption("Altere os campos necessários e aplique as alterações antes de baixar o arquivo.")
    prefix = f"edit_{index}_{st.session_state.revision}"
    with st.form("edit_record"):
        tab_record, tab_header = st.tabs(["Dados do registro", "Cabeçalho do arquivo"])
        with tab_record:
            if rt == '03':
                patient_keys = ('prd_nmpac', 'prd_dtnasc', 'prd_cnspac', 'prd_cpf_pcnte')
                by_key = {field.key: field for field in fields}
                with st.container(border=True):
                    st.markdown("#### Identificação do paciente")
                    record_values = render_fields(line, [by_key[key] for key in patient_keys], prefix, columns=2)
                st.markdown("#### Demais dados do registro")
                record_values.update(render_fields(line, [field for field in fields if field.key not in patient_keys], prefix))
            else:
                record_values = render_fields(line, fields, prefix)
        with tab_header:
            st.caption("Linhas, folhas e campo de controle são recalculados automaticamente.")
            header_values = render_fields(bpa.lines[header_index], HEADER_FIELDS, prefix + '_header')
        submitted = st.form_submit_button("Aplicar alterações", type="primary")
        if submitted:
            try:
                previous_line = bpa.lines[index]
                save_changes(bpa, index, header_index, record_values, header_values)
                if bpa.lines[index] != previous_line:
                    st.session_state.edited_records.add(index)
                st.session_state.save_notice = True
                st.session_state.revision += 1
                st.rerun()
            except (ValueError, UnicodeEncodeError) as exc:
                st.error(f"Não foi possível aplicar as alterações: {exc}")
    if st.session_state.revision > 1:
        st.success("Alterações aplicadas à cópia em edição. Baixe o arquivo na barra lateral.")
