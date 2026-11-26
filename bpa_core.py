# -*- coding: utf-8 -*-
"""
EDITOR DE ARQUIVO BPA (layout interno SIA/BPA)

Funções principais:
- Solicita o arquivo BPA, independentemente da extensão (.JUL, .AGO, etc.).
- Solicita se o item a consultar/alterar é BPA-I ou BPA-C.
- Solicita FL (folha) e SEQ (sequência).
- Localiza e exibe em abas:
    * Cabeçalho do arquivo (registro 01)
    * Registro selecionado BPA-C (02) ou BPA-I (03)
- Permite editar os campos e salvar novamente no arquivo.
- Mantém FL/SEQ editáveis, com validação de colisão antes de salvar.
- Recalcula automaticamente no cabeçalho:
    * quantidade de linhas de produção;
    * quantidade de folhas gravadas;
    * campo de controle.
- Cria backup automático antes do primeiro salvamento sobre o arquivo original.

Observação:
O programa edita registros existentes. Não inclui nem exclui linhas de produção.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

APP_TITLE = "Editor de Arquivo BPA"
ENCODINGS_TO_TRY = ["cp850", "cp1252", "latin-1"]


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    start: int  # posição 1-based inclusiva
    end: int    # posição 1-based inclusiva
    required: str = ""
    desc: str = ""
    kind: str = "CHAR"
    read_only: bool = False

    @property
    def size(self) -> int:
        return self.end - self.start + 1


def F(key, label, start, end, req="", desc="", kind="CHAR", ro=False):
    return FieldDef(key, label, start, end, req, desc, kind, ro)


# ------------------------------------------------------------
# Layouts conforme Layout da Interface Texto do BPA e do SIA
# ------------------------------------------------------------
HEADER_FIELDS = [
    F("cbc_hdr", "Indicador do registro", 1, 2, "SIM", "01 = cabeçalho", "NUM", True),
    F("cbc_id", "Identificador", 3, 7, "SIM", "#BPA#", "CHAR", True),
    F("cbc_mvm", "Ano/mês de processamento", 8, 13, "SIM", "Formato AAAAMM", "NUM"),
    F("cbc_lin", "Número de linhas do BPA", 14, 19, "SIM", "Recalculado automaticamente ao salvar", "NUM", True),
    F("cbc_flh", "Quantidade de folhas do BPA", 20, 25, "SIM", "Recalculada automaticamente ao salvar", "NUM", True),
    F("cbc_smt_vrf", "Campo de controle", 26, 29, "SIM", "Recalculado automaticamente: (soma procedimentos + quantidades) % 1111 + 1111", "NUM", True),
    F("cbc_rsp", "Órgão de origem", 30, 59, "SIM", "Nome do órgão responsável pela informação", "CHAR"),
    F("cbc_sgl", "Sigla do órgão de origem", 60, 65, "SIM", "Órgão responsável pela digitação", "CHAR"),
    F("cbc_cgccpf", "CGC/CPF do responsável", 66, 79, "SIM", "Somente números; completar com zeros à esquerda", "NUM"),
    F("cbc_dst", "Órgão de destino", 80, 119, "SIM", "Nome do órgão de saúde destino", "CHAR"),
    F("cbc_dst_in", "Destino M/E", 120, 120, "SIM", "E = Estadual; M = Municipal", "CHAR"),
    F("cbc_versao", "Versão", 121, 130, "SIM", "Informação livre", "CHAR"),
]


BPAC_FIELDS = [
    F("prd_ident", "Indicador do registro", 1, 2, "SIM", "02 = BPA Consolidado", "NUM", True),
    F("prd_cnes", "CNES", 3, 9, "SIM", "Código CNES, 7 posições", "NUM"),
    F("prd_cmp", "Competência", 10, 15, "SIM", "Formato AAAAMM", "NUM"),
    F("prd_cbo", "CBO do profissional", 16, 21, "", "Classificação Brasileira de Ocupações", "CHAR"),
    F("prd_flh", "FL - Folha", 22, 24, "SIM", "Domínio 001..999", "NUM"),
    F("prd_seq", "SEQ - Sequência", 25, 26, "", "Domínio 01..20", "NUM"),
    F("prd_pa", "Procedimento", 27, 36, "", "Código do procedimento ambulatorial, 10 dígitos", "NUM"),
    F("prd_idade", "Idade", 37, 39, "", "0 a 130 anos", "NUM"),
    F("prd_qt", "Quantidade", 40, 45, "", "Quantidade de procedimentos produzidos", "NUM"),
    F("prd_org", "Origem", 46, 48, "", "BPA, PNI, SIE, SIB, MIN, PAC, SCL ou EXT", "CHAR"),
]


BPAI_FIELDS = [
    F("prd_ident", "Indicador do registro", 1, 2, "SIM", "03 = BPA Individualizado", "NUM", True),
    F("prd_cnes", "CNES", 3, 9, "SIM", "Código CNES, 7 posições", "NUM"),
    F("prd_cmp", "Competência", 10, 15, "SIM", "Formato AAAAMM", "NUM"),
    F("prd_cnsmed", "CNS do profissional", 16, 30, "SIM", "CNS do profissional com dígito verificador válido", "NUM"),
    F("prd_cbo", "CBO do profissional", 31, 36, "SIM", "Classificação Brasileira de Ocupações", "CHAR"),
    F("prd_dtaten", "Data do atendimento", 37, 44, "", "Formato AAAAMMDD", "NUM"),
    F("prd_flh", "FL - Folha", 45, 47, "SIM", "Domínio 001..999", "NUM"),
    F("prd_seq", "SEQ - Sequência", 48, 49, "", "Domínio 01..99", "NUM"),
    F("prd_pa", "Procedimento", 50, 59, "", "Código do procedimento ambulatorial, 10 dígitos", "NUM"),
    F("prd_cnspac", "CNS do paciente", 60, 74, "COND.", "Obrigatório quando o procedimento exigir. CPF e CNS podem ser mantidos quando informados.", "NUM"),
    F("prd_sexo", "Sexo", 75, 75, "", "M = Masculino; F = Feminino", "CHAR"),
    F("prd_ibge", "Município de residência (IBGE)", 76, 81, "", "Código IBGE", "NUM"),
    F("prd_cid", "CID-10", 82, 85, "", "CID-10", "CHAR"),
    F("prd_idade", "Idade", 86, 88, "", "0 a 130 anos", "NUM"),
    F("prd_qt", "Quantidade", 89, 94, "", "Quantidade de procedimentos produzidos", "NUM"),
    F("prd_caten", "Caráter de atendimento", 95, 96, "", "Quando preenchido, somente números", "NUM"),
    F("prd_naut", "Nº autorização do estabelecimento", 97, 109, "", "Quando preenchido, somente números", "NUM"),
    F("prd_org", "Origem", 110, 112, "", "BPA, PNI, SIE, SIB, MIN, PAC, SCL ou EXT", "CHAR"),
    F("prd_nmpac", "Nome do paciente", 113, 142, "", "Nome completo do paciente", "CHAR"),
    F("prd_dtnasc", "Data de nascimento", 143, 150, "", "Formato AAAAMMDD", "NUM"),
    F("prd_raca", "Raça/Cor", 151, 152, "SIM", "01 Branca; 02 Preta; 03 Parda; 04 Amarela; 05 Indígena; 99 Sem informação", "NUM"),
    F("prd_etnia", "Etnia", 153, 156, "COND.", "Preencher somente se raça/cor = 05", "NUM"),
    F("prd_nac", "Nacionalidade", 157, 159, "", "Código de nacionalidade", "NUM"),
    F("prd_srv", "Serviço", 160, 162, "COND.", "Obrigatório quando o procedimento exigir", "NUM"),
    F("prd_clf", "Classificação", 163, 165, "COND.", "Obrigatório quando o procedimento exigir", "NUM"),
    F("prd_equipe_seq", "Sequência da equipe", 166, 173, "", "Código da sequência da equipe", "NUM"),
    F("prd_equipe_area", "Área da equipe", 174, 177, "", "Código da área da equipe", "NUM"),
    F("prd_cnpj", "CNPJ empresa OPM", 178, 191, "", "Empresa que realizou manutenção/adaptação da OPM", "NUM"),
    F("prd_cep_pcnte", "CEP do paciente", 192, 199, "", "CEP do paciente", "NUM"),
    F("prd_lograd_pcnte", "Código do logradouro", 200, 202, "", "Código do logradouro do paciente", "NUM"),
    F("prd_end_pcnte", "Endereço", 203, 232, "", "Endereço do paciente", "CHAR"),
    F("prd_compl_pcnte", "Complemento", 233, 242, "", "Complemento do endereço", "CHAR"),
    F("prd_num_pcnte", "Número do endereço", 243, 247, "", "Número do endereço; layout admite SN / 00", "CHAR"),
    F("prd_bairro_pcnte", "Bairro", 248, 277, "", "Bairro do paciente", "CHAR"),
    F("prd_ddtel_pcnte", "Telefone", 278, 288, "", "Quando preenchido, somente números", "NUM"),
    F("prd_email_pcnte", "E-mail", 289, 328, "", "E-mail do paciente", "CHAR"),
    F("prd_ine", "INE", 329, 338, "SIM", "Identificação Nacional de Equipes", "NUM"),
    F("prd_cpf_pcnte", "CPF do paciente", 339, 349, "COND.", "Obrigatório quando o procedimento exigir. CPF e CNS podem ser mantidos quando informados.", "NUM"),
    F("prd_situacao_rua", "Pessoa em situação de rua", 350, 350, "", "N = Não; S = Sim; válido a partir de 12/2024", "CHAR"),
    F("prd_sem_cpf", "Pessoa sem CPF/Registro Civil", 351, 351, "", "N = Não; S = Sim; válido a partir de 07/2026", "CHAR"),
]


# ----------------------------
# Utilidades
# ----------------------------
def detect_encoding(raw: bytes) -> str:
    for enc in ENCODINGS_TO_TRY:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "latin-1"


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def extract_field(line: str, field: FieldDef) -> str:
    if field.start > len(line):
        return ""
    return line[field.start - 1:min(field.end, len(line))].rstrip()


def fit_value(value: str, field: FieldDef) -> str:
    value = (value or "").replace("\r", " ").replace("\n", " ")
    if len(value) > field.size:
        raise ValueError(f"{field.label}: máximo de {field.size} caracteres.")
    if field.kind.upper() == "NUM" and value.strip():
        if not value.strip().isdigit():
            raise ValueError(f"{field.label}: informe somente números.")
        return value.strip().rjust(field.size, "0")
    return value.ljust(field.size, " ")


def set_field(line: str, field: FieldDef, value: str) -> str:
    fitted = fit_value(value, field)
    if field.start > len(line) and not value.strip():
        return line
    if len(line) < field.end:
        line = line.ljust(field.end, " ")
    return line[:field.start - 1] + fitted + line[field.end:]


def norm_fl(value: str) -> str:
    d = only_digits(value)
    if not d:
        return ""
    n = int(d)
    if not 1 <= n <= 999:
        raise ValueError("FL deve estar entre 001 e 999.")
    return str(n).zfill(3)


def norm_seq(value: str, record_type: str) -> str:
    d = only_digits(value)
    if not d:
        return ""
    n = int(d)
    max_seq = 20 if record_type == "02" else 99
    if not 1 <= n <= max_seq:
        tipo = "BPA-C" if record_type == "02" else "BPA-I"
        raise ValueError(f"SEQ do {tipo} deve estar entre 01 e {max_seq:02d}.")
    return str(n).zfill(2)


def norm_cnes(value: str) -> str:
    d = only_digits(value)
    if not d:
        return ""
    if len(d) > 7:
        raise ValueError("CNES deve possuir no máximo 7 dígitos.")
    return d.zfill(7)


class BpaFile:
    def __init__(self, path: str):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        self.encoding = detect_encoding(self.raw)
        self.newline = b"\r\n" if b"\r\n" in self.raw else (b"\n" if b"\n" in self.raw else os.linesep.encode())
        self.has_ctrl_z = self.raw.endswith(b"\x1a") or self.raw.rstrip(b"\r\n").endswith(b"\x1a")

        content = self.raw
        if self.has_ctrl_z:
            content = content.rstrip(b"\r\n")
            if content.endswith(b"\x1a"):
                content = content[:-1]

        raw_lines = content.split(self.newline)
        if raw_lines and raw_lines[-1] == b"":
            raw_lines.pop()
        self.lines = [x.decode(self.encoding, errors="replace") for x in raw_lines]
        self.backup_created = False

    @staticmethod
    def record_type(line: str) -> str:
        return line[:2] if len(line) >= 2 else ""

    @staticmethod
    def get_fl_seq(line: str, record_type: str) -> tuple[str, str]:
        if record_type == "02":
            return line[21:24].strip(), line[24:26].strip()
        if record_type == "03":
            return line[44:47].strip(), line[47:49].strip()
        return "", ""

    def find_record_indices(self, record_type: str, cnes: str, fl: str, seq: str) -> list[int]:
        result = []
        for idx, line in enumerate(self.lines):
            if self.record_type(line) != record_type:
                continue
            line_cnes = line[2:9].strip() if len(line) >= 9 else ""
            line_fl, line_seq = self.get_fl_seq(line, record_type)
            if line_cnes == cnes and line_fl == fl and line_seq == seq:
                result.append(idx)
        return result

    def has_other_key(self, record_type: str, cnes: str, fl: str, seq: str, exclude_idx: int) -> bool:
        return any(idx != exclude_idx for idx in self.find_record_indices(record_type, cnes, fl, seq))

    def recalc_header(self):
        production = [(i, l) for i, l in enumerate(self.lines) if self.record_type(l) in ("02", "03")]
        line_count = len(production)

        # Considera uma folha distinta por tipo de BPA + CNES + número da folha,
        # pois a numeração de folhas pode se repetir entre estabelecimentos e tipos.
        sheets = set()
        total_control = 0

        for _, line in production:
            typ = self.record_type(line)
            cnes = line[2:9].strip() if len(line) >= 9 else ""
            fl, _ = self.get_fl_seq(line, typ)
            if fl:
                sheets.add((typ, cnes, fl))

            if typ == "02":
                proc = line[26:36].strip() if len(line) >= 36 else ""
                qtd = line[39:45].strip() if len(line) >= 45 else ""
            else:
                proc = line[49:59].strip() if len(line) >= 59 else ""
                qtd = line[88:94].strip() if len(line) >= 94 else ""

            if proc.isdigit():
                total_control += int(proc)
            if qtd.isdigit():
                total_control += int(qtd)

        sheet_count = len(sheets)
        control = (total_control % 1111) + 1111

        for i, line in enumerate(self.lines):
            if self.record_type(line) == "01":
                if len(line) < 29:
                    line = line.ljust(29)
                line = (
                    line[:13]
                    + str(line_count).zfill(6)
                    + str(sheet_count).zfill(6)
                    + str(control).zfill(4)
                    + line[29:]
                )
                self.lines[i] = line
                break

    def create_backup(self):
        if self.backup_created:
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.backup_{stamp}")
        shutil.copy2(self.path, backup)
        self.backup_created = True

    def save(self, target: Path | None = None):
        if target is None:
            self.create_backup()
            target = self.path
        self.recalc_header()
        data = self.newline.join(line.encode(self.encoding, errors="replace") for line in self.lines)
        data += self.newline
        if self.has_ctrl_z:
            data += b"\x1a"
        target.write_bytes(data)


# ----------------------------
# Interface
# ----------------------------
